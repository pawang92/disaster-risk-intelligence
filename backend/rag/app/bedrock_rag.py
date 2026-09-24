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
    """A document chunk retrieved from the vector database."""

    text: str
    document_id: str
    source_key: str
    page: int
    score: float
    language: str

    def citation(self) -> Citation:
        """Convert the retrieved chunk into a citation."""
        return Citation(
            document_id=self.document_id,
            source_key=self.source_key,
            page=self.page,
            excerpt=self.text[:500],
            score=round(self.score, 4),
        )

class DisasterRag:
    """Production Retrieval Augmented Generation service."""

    def __init__(self, settings: Settings):
        self.settings = settings

        self._last_embedding_at = 0.0

        # Bedrock client is initialized only when Bedrock is actually used.
        self._bedrock = None

    # ------------------------------------------------------------------
    # BEDROCK CLIENT
    # ------------------------------------------------------------------

    @property
    def bedrock(self):
        """Create the Bedrock client lazily."""
        if self._bedrock is None:
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.aws_region,
            )

        return self._bedrock

    # ------------------------------------------------------------------
    # LOCAL EMBEDDING MODEL
    # ------------------------------------------------------------------

    @cached_property
    def local_embedder(self):
        """Load the local multilingual embedding model once."""

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install it using: pip install sentence-transformers"
            ) from exc

        print(
            "Loading local embedding model: "
            f"{self.settings.local_embedding_model}"
        )

        return SentenceTransformer(
            self.settings.local_embedding_model,
            device="cpu",
        )

    # ------------------------------------------------------------------
    # EMBEDDING
    # ------------------------------------------------------------------

    def embed(
        self,
        text: str,
        kind: str = "passage",
    ) -> list[float]:
        """Generate an embedding for a document passage or query."""

        if kind not in {"passage", "query"}:
            raise ValueError(
                "Embedding kind must be 'passage' or 'query'."
            )

        # --------------------------------------------------------------
        # LOCAL EMBEDDINGS
        # --------------------------------------------------------------

        if self.settings.embedding_provider == "local":

            formatted_text = f"{kind}: {text}"

            vector = self.local_embedder.encode(
                formatted_text,
                normalize_embeddings=True,
            )

            return vector.tolist()

        # --------------------------------------------------------------
        # BEDROCK EMBEDDINGS
        # --------------------------------------------------------------

        if self.settings.embedding_provider != "bedrock":
            raise ValueError(
                "EMBEDDING_PROVIDER must be 'local' or 'bedrock'."
            )

        elapsed = (
            time.monotonic()
            - self._last_embedding_at
        )

        if (
            elapsed
            < self.settings.embedding_min_interval_seconds
        ):
            time.sleep(
                self.settings.embedding_min_interval_seconds
                - elapsed
            )

        for attempt in range(
            1,
            self.settings.embedding_max_attempts + 1,
        ):
            try:
                response = self.bedrock.invoke_model(
                    modelId=(
                        self.settings
                        .bedrock_embedding_model_id
                    ),
                    body=json.dumps(
                        {
                            "inputText": text,
                            "dimensions": (
                                self.settings
                                .embedding_dimensions
                            ),
                            "normalize": True,
                        }
                    ),
                    accept="application/json",
                    contentType="application/json",
                )

                self._last_embedding_at = (
                    time.monotonic()
                )

                body = json.loads(
                    response["body"].read()
                )

                return body["embedding"]

            except ClientError as exc:

                error_code = (
                    exc.response
                    .get("Error", {})
                    .get("Code")
                )

                retryable_errors = {
                    "ThrottlingException",
                    "ServiceUnavailableException",
                }

                if (
                    error_code not in retryable_errors
                    or attempt
                    == self.settings.embedding_max_attempts
                ):
                    raise

                delay = (
                    min(
                        60.0,
                        2.0 ** attempt,
                    )
                    + random.uniform(0, 1)
                )

                print(
                    "Bedrock embedding request throttled. "
                    f"Retrying in {delay:.1f}s "
                    f"({attempt}/"
                    f"{self.settings.embedding_max_attempts})."
                )

                time.sleep(delay)

        raise RuntimeError(
            "Unable to generate document embedding."
        )

    # ------------------------------------------------------------------
    # CHROMA VECTOR STORE
    # ------------------------------------------------------------------

    @cached_property
    def chroma_collection(self):
        """Return the persistent Chroma collection."""

        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is not installed. "
                "Install it using: pip install chromadb"
            ) from exc

        client = chromadb.PersistentClient(
            path=self.settings.chroma_path
        )

        collection_name = (
            f"{self.settings.chroma_collection}"
            f"-{self.settings.embedding_provider}"
        )

        print(
            f"Using Chroma collection: {collection_name}"
        )

        return client.get_or_create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
            },
        )

    # ------------------------------------------------------------------
    # RETRIEVAL
    # ------------------------------------------------------------------

    def retrieve(
        self,
        question: str,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve the most relevant document chunks."""

        where: dict[str, Any] | None = None

        if filters:

            conditions = [
                {key: value}
                for key, value in filters.items()
            ]

            if len(conditions) == 1:
                where = conditions[0]
            else:
                where = {
                    "$and": conditions,
                }

        query_embedding = self.embed(
            question,
            kind="query",
        )

        result = self.chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=self.settings.retrieval_k,
            where=where,
            include=[
                "documents",
                "metadatas",
                "distances",
            ],
        )

        if not result["documents"]:
            return []

        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]

        chunks: list[RetrievedChunk] = []

        for text, metadata, distance in zip(
            documents,
            metadatas,
            distances,
        ):
            chunks.append(
                RetrievedChunk(
                    text=text,
                    document_id=metadata["document_id"],
                    source_key=metadata["source_key"],
                    page=int(metadata["page"]),
                    language=metadata["language"],
                    score=1.0 - float(distance),
                )
            )

        return chunks

    # ------------------------------------------------------------------
    # INDEX DOCUMENTS
    # ------------------------------------------------------------------

    def index_records(
        self,
        records: list[dict[str, Any]],
    ) -> None:
        """Index document chunks into Chroma."""

        if not records:
            return

        embeddings = [
            self.embed(
                record["text"],
                kind="passage",
            )
            for record in records
        ]

        self.chroma_collection.upsert(
            ids=[
                record["id"]
                for record in records
            ],
            documents=[
                record["text"]
                for record in records
            ],
            embeddings=embeddings,
            metadatas=[
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"id", "text"}
                }
                for record in records
            ],
        )

        print(
            f"Indexed {len(records)} chunks "
            f"using {self.settings.embedding_provider} embeddings."
        )

    # ------------------------------------------------------------------
    # GROK LLM
    # ------------------------------------------------------------------

    def _answer_with_grok(
        self,
        system: str,
        prompt: str,
    ) -> str:
        """Generate a grounded answer using xAI Grok."""

        api_key = self.settings.grok_api_key

        if not api_key:
            raise RuntimeError(
                "GROK_API_KEY is not configured. "
                "Add it to .env.local."
            )

        url = (
            f"{self.settings.grok_base_url.rstrip('/')}"
            "/responses"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.settings.grok_model,
            "input": [
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }

        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.settings.grok_timeout_seconds,
            )

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:

            try:
                error_details = (
                    exc.response.json()
                )
            except Exception:
                error_details = exc.response.text

            raise RuntimeError(
                "Grok API request failed. "
                f"HTTP {exc.response.status_code}: "
                f"{error_details}"
            ) from exc

        except httpx.RequestError as exc:

            raise RuntimeError(
                f"Unable to connect to Grok API: {exc}"
            ) from exc

        try:
            data = response.json()

        except ValueError as exc:

            raise RuntimeError(
                "Grok returned an invalid JSON response."
            ) from exc

        answer = data.get("output_text")

        if answer:
            return answer

        # Defensive fallback for response formats where
        # output_text is not directly available.
        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")

                if text:
                    return text

        raise RuntimeError(
            "Grok returned an empty response."
        )


    def _answer_with_bedrock(
        self,
        system: str,
        prompt: str,
    ) -> str:
        """Generate an answer using AWS Bedrock."""

        response = self.bedrock.converse(
            modelId=self.settings.bedrock_chat_model_id,
            system=[
                {
                    "text": system,
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": prompt,
                        }
                    ],
                }
            ],
            inferenceConfig={
                "maxTokens": 900,
                "temperature": 0.1,
            },
        )

        return (
            response["output"]
            ["message"]
            ["content"][0]
            ["text"]
        )
    def _build_context(
        self,
        chunks: list[RetrievedChunk],
    ) -> str:
        """Build the grounded context sent to the LLM."""

        return "\n\n".join(
            (
                f"[Document: {chunk.source_key}; "
                f"page {chunk.page}]\n"
                f"{chunk.text}"
            )
            for chunk in chunks
        )
    def _build_system_prompt(
        self,
        language: str,
    ) -> str:
        """Build the system prompt for grounded RAG generation."""

        requested_language = (
            "Marathi (Devanagari)"
            if language == "mr"
            else "English"
        )

        return (
            "You are a disaster-risk information assistant. "

            "Your answers must be grounded ONLY in the "
            "provided document excerpts. "

            "Do not use external knowledge to fill gaps. "

            "If the documents do not contain enough information "
            "to answer the question, clearly state that the "
            "available documents do not provide sufficient information. "

            "Do not invent locations, dates, statistics, thresholds, "
            "emergency procedures, or contact information. "

            f"Respond in {requested_language}. "

            "Keep the answer clear, factual, and concise. "

            "For claims supported by the documents, cite the source "
            "using the format [source_key p.N]."
        )

    def answer( self, question: str, language: str, chunks: list[RetrievedChunk],) -> str:
        """Generate the final RAG answer."""
        if not chunks:
            return (
                "The available documents do not contain enough "
                "information to answer this question."
            )
        context = self._build_context(
            chunks
        )
        system_prompt = self._build_system_prompt(
            language
        )
        prompt = (
            f"Question:\n"
            f"{question}\n\n"
            f"Document excerpts:\n"
            f"{context[:self.settings.max_context_characters]}"
        )

        # --------------------------------------------------------------
        # Primary provider: Grok
        # --------------------------------------------------------------

        if self.settings.answer_provider == "grok":
            print("Answer provider: Grok")
            return self._answer_with_grok(
                system_prompt,
                prompt,
            )

        if self.settings.answer_provider == "bedrock":
            print("Answer provider: Bedrock")
            return self._answer_with_bedrock(
                system_prompt,
                prompt,
            )
        raise ValueError(
            "ANSWER_PROVIDER must be "
            "'grok' or 'bedrock'."
        )