"""Retrieval and generation clients for the disaster-document RAG service."""
import json
import random
import time
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError

from .config import Settings
from .schema import Citation


@dataclass
class RetrievedChunk:
    text: str
    document_id: str
    source_key: str
    page: int
    score: float
    language: str

    def citation(self) -> Citation:
        return Citation(document_id=self.document_id, source_key=self.source_key, page=self.page,
                        excerpt=self.text[:500], score=round(self.score, 4))


class DisasterRag:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_region)
        self._last_embedding_at = 0.0

    @cached_property
    def local_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install sentence-transformers to use EMBEDDING_PROVIDER=local") from exc
        return SentenceTransformer(self.settings.local_embedding_model, device="cpu")

    def embed(self, text: str, kind: str = "passage") -> list[float]:
        """Embed one chunk without bursting the Bedrock request-per-minute quota."""
        if self.settings.embedding_provider == "local":
            # E5 is trained with distinct prefixes for documents and search queries.
            vector = self.local_embedder.encode(f"{kind}: {text}", normalize_embeddings=True)
            return vector.tolist()
        if self.settings.embedding_provider != "bedrock":
            raise ValueError("EMBEDDING_PROVIDER must be 'bedrock' or 'local'")
        elapsed = time.monotonic() - self._last_embedding_at
        if elapsed < self.settings.embedding_min_interval_seconds:
            time.sleep(self.settings.embedding_min_interval_seconds - elapsed)

        for attempt in range(1, self.settings.embedding_max_attempts + 1):
            try:
                response = self.bedrock.invoke_model(
                    modelId=self.settings.bedrock_embedding_model_id,
                    body=json.dumps({"inputText": text, "dimensions": self.settings.embedding_dimensions, "normalize": True}),
                    accept="application/json", contentType="application/json")
                self._last_embedding_at = time.monotonic()
                return json.loads(response["body"].read())["embedding"]
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in {"ThrottlingException", "ServiceUnavailableException"} or attempt == self.settings.embedding_max_attempts:
                    raise
                # Exponential backoff with jitter prevents synchronized retries.
                delay = min(60.0, 2.0 ** attempt) + random.uniform(0, 1)
                print(f"Bedrock is throttling embeddings; waiting {delay:.1f}s before retry {attempt}/{self.settings.embedding_max_attempts}.")
                time.sleep(delay)

    @cached_property
    def chroma_collection(self):
        """Disk-backed vector store for the current local-first RAG deployment."""
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("Install the application requirements to use the local Chroma store") from exc
        return chromadb.PersistentClient(path=self.settings.chroma_path).get_or_create_collection(
            name=f"{self.settings.chroma_collection}-{self.settings.embedding_provider}", metadata={"hnsw:space": "cosine"})

    def retrieve(self, question: str, filters: dict[str, str] | None = None) -> list[RetrievedChunk]:
        where: dict[str, Any] | None = None
        if filters:
            conditions = [{key: value} for key, value in filters.items()]
            where = conditions[0] if len(conditions) == 1 else {"$and": conditions}
        result = self.chroma_collection.query(query_embeddings=[self.embed(question, "query")], n_results=self.settings.retrieval_k,
                                              where=where, include=["documents", "metadatas", "distances"])
        return [RetrievedChunk(text=text, document_id=metadata["document_id"], source_key=metadata["source_key"],
                               page=int(metadata["page"]), language=metadata["language"], score=1 - float(distance))
                for text, metadata, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0])]

    def index_records(self, records: list[dict[str, Any]]) -> None:
        """Upsert chunks into Chroma. IDs make repeat ingestion idempotent."""
        if not records:
            return
        self.chroma_collection.upsert(
            ids=[record["id"] for record in records], documents=[record["text"] for record in records],
            embeddings=[self.embed(record["text"], "passage") for record in records],
            metadatas=[{key: value for key, value in record.items() if key not in {"id", "text"}} for record in records])

    def _answer_with_bedrock(self, system: str, prompt: str) -> str:
        response = self.bedrock.converse(
            modelId=self.settings.bedrock_chat_model_id, system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 900, "temperature": 0.1})
        return response["output"]["message"]["content"][0]["text"]

    def _answer_with_ollama(self, system: str, prompt: str) -> str:
        try:
            response = httpx.post(
                f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
                json={"model": self.settings.ollama_model, "system": system, "prompt": prompt,
                      "stream": False, "options": {"temperature": 0.1}},
                timeout=self.settings.ollama_timeout_seconds)
            response.raise_for_status()
            return response.json()["response"]
        except (httpx.HTTPError, KeyError) as exc:
            raise RuntimeError(
                f"Local Ollama model '{self.settings.ollama_model}' is unavailable. "
                "Start Ollama and run: ollama pull " + self.settings.ollama_model
            ) from exc

    def answer(
        self,
        question: str,
        language: str,
        chunks: list[RetrievedChunk],
    ) -> str:

        context = "\n\n".join(
            f"[Document: {c.source_key}; page {c.page}]\n{c.text}"
            for c in chunks
        )

        requested_language = (
            "Marathi (Devanagari)"
            if language == "mr"
            else "English"
        )

        system = (
            "You are a disaster-risk information assistant. "
            "Answer ONLY from supplied document excerpts. "
            "If the excerpts do not establish an answer, say so plainly. "
            "Do not invent emergency advice, locations, dates, "
            "thresholds, or contacts. "
            f"Reply in {requested_language}. "
            "Cite claims as [source_key p.N]."
        )

        prompt = (
            f"Question: {question}\n\n"
            f"Excerpts:\n"
            f"{context[:self.settings.max_context_characters]}"
        )

        # ---------------------------------------------------------------
        # 1. Ollama-only mode
        # ---------------------------------------------------------------
        if self.settings.answer_provider == "ollama":
            print("Answer provider: Ollama")
            return self._answer_with_ollama(system, prompt)

        # ---------------------------------------------------------------
        # 2. Bedrock-only mode
        # ---------------------------------------------------------------
        if self.settings.answer_provider == "bedrock":
            print("Answer provider: Bedrock")
            return self._answer_with_bedrock(system, prompt)

        # ---------------------------------------------------------------
        # 3. Automatic fallback mode
        #    Bedrock -> Ollama
        # ---------------------------------------------------------------
        if self.settings.answer_provider == "auto":

            print("Answer provider: Bedrock (primary)")

            try:
                return self._answer_with_bedrock(
                    system,
                    prompt,
                )

            except Exception as exc:

                print(
                    "Bedrock answer generation failed."
                )

                print(
                    f"Bedrock error: "
                    f"{type(exc).__name__}: {exc}"
                )

                print(
                    "Falling back to Ollama..."
                )

                try:
                    return self._answer_with_ollama(
                        system,
                        prompt,
                    )

                except Exception as ollama_exc:

                    print(
                        "Ollama fallback also failed."
                    )

                    raise RuntimeError(
                        "Both Bedrock and Ollama answer generation failed.\n"
                        f"Bedrock error: "
                        f"{type(exc).__name__}: {exc}\n"
                        f"Ollama error: "
                        f"{type(ollama_exc).__name__}: "
                        f"{ollama_exc}"
                    ) from ollama_exc

        raise ValueError(
            "ANSWER_PROVIDER must be "
            "'bedrock', 'ollama', or 'auto'"
        )