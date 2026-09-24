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
        return Citation(
            document_id=self.document_id,
            source_key=self.source_key,
            page=self.page,
            excerpt=self.text[:500],
            score=round(self.score, 4),
        )


class DisasterRag:
    """Local-first RAG service with optional cloud providers."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._last_embedding_at = 0.0
        self._bedrock = None

    @property
    def bedrock(self):
        """Create the Bedrock client only when Bedrock is actually used."""
        if self._bedrock is None:
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.aws_region,
            )
        return self._bedrock

    @cached_property
    def local_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            ) from exc

        return SentenceTransformer(
            self.settings.local_embedding_model,
            device="cpu",
        )

    def embed(self, text: str, kind: str = "passage") -> list[float]:
        """Generate an E5 query or passage embedding."""
        if kind not in {"passage", "query"}:
            raise ValueError("Embedding kind must be 'passage' or 'query'.")

        if not text or not text.strip():
            raise ValueError("Cannot embed empty text.")

        if self.settings.embedding_provider == "local":
            vector = self.local_embedder.encode(
                f"{kind}: {text.strip()}",
                normalize_embeddings=True,
            )
            return vector.tolist()

        if self.settings.embedding_provider != "bedrock":
            raise ValueError(
                "EMBEDDING_PROVIDER must be 'local' or 'bedrock'."
            )

        elapsed = time.monotonic() - self._last_embedding_at
        if elapsed < self.settings.embedding_min_interval_seconds:
            time.sleep(
                self.settings.embedding_min_interval_seconds - elapsed
            )

        for attempt in range(1, self.settings.embedding_max_attempts + 1):
            try:
                response = self.bedrock.invoke_model(
                    modelId=self.settings.bedrock_embedding_model_id,
                    body=json.dumps(
                        {
                            "inputText": text,
                            "dimensions": self.settings.embedding_dimensions,
                            "normalize": True,
                        }
                    ),
                    accept="application/json",
                    contentType="application/json",
                )
                self._last_embedding_at = time.monotonic()
                body = json.loads(response["body"].read())
                return body["embedding"]

            except ClientError as exc:
                error_code = (
                    exc.response.get("Error", {}).get("Code")
                )
                retryable = {
                    "ThrottlingException",
                    "ServiceUnavailableException",
                }
                if (
                    error_code not in retryable
                    or attempt == self.settings.embedding_max_attempts
                ):
                    raise

                delay = min(60.0, 2.0**attempt) + random.uniform(0, 1)
                time.sleep(delay)

        raise RuntimeError("Unable to generate document embedding.")

    @cached_property
    def chroma_collection(self):
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is not installed. Run: pip install chromadb"
            ) from exc

        client = chromadb.PersistentClient(path=self.settings.chroma_path)
        collection_name = (
            f"{self.settings.chroma_collection}-"
            f"{self.settings.embedding_provider}"
        )

        return client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def _normalize_filter_value(value: str) -> str:
        return " ".join(str(value).strip().lower().split())

    def _build_where(
        self,
        filters: dict[str, str] | None,
    ) -> dict[str, Any] | None:
        if not filters:
            return None

        conditions = [
            {key: self._normalize_filter_value(value)}
            for key, value in filters.items()
            if value and str(value).strip()
        ]

        if not conditions:
            return None

        return conditions[0] if len(conditions) == 1 else {"$and": conditions}

    def _query_collection(
        self,
        query_embedding: list[float],
        n_results: int,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        return self.chroma_collection.query(**kwargs)

    @staticmethod
    def _result_count(result: dict[str, Any]) -> int:
        documents = result.get("documents") or [[]]
        return len(documents[0]) if documents else 0

    def _to_chunks(self, result: dict[str, Any]) -> list[RetrievedChunk]:
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []

        for text, metadata, distance in zip(
            documents,
            metadatas,
            distances,
        ):
            metadata = metadata or {}
            # Chroma cosine distance is normally in [0, 2].
            # Clamp the derived similarity for a stable API contract.
            score = max(0.0, min(1.0, 1.0 - float(distance)))

            chunks.append(
                RetrievedChunk(
                    text=text or "",
                    document_id=str(metadata.get("document_id", "")),
                    source_key=str(metadata.get("source_key", "")),
                    page=int(metadata.get("page", 1)),
                    language=str(metadata.get("language", "en")),
                    score=score,
                )
            )

        return chunks

    def retrieve(
        self,
        question: str,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks, with a broad-search fallback if filters are too strict."""
        query_embedding = self.embed(question, kind="query")
        where = self._build_where(filters)

        try:
            result = self._query_collection(
                query_embedding,
                self.settings.retrieval_k,
                where,
            )
        except Exception:
            # A metadata filter should never make the whole RAG service
            # unavailable. Retry without the filter.
            if where:
                result = self._query_collection(
                    query_embedding,
                    self.settings.retrieval_k,
                    None,
                )
            else:
                raise

        chunks = self._to_chunks(result)

        # If a strict filter produced no result, retry broadly. This protects
        # against historical metadata casing/format differences.
        if not chunks and where:
            result = self._query_collection(
                query_embedding,
                max(
                    self.settings.retrieval_k,
                    self.settings.retrieval_fallback_k,
                ),
                None,
            )
            chunks = self._to_chunks(result)

        # Do not return obviously irrelevant results when a threshold is set.
        if self.settings.min_retrieval_score > 0:
            filtered = [
                chunk
                for chunk in chunks
                if chunk.score >= self.settings.min_retrieval_score
            ]
            if filtered:
                chunks = filtered

        return chunks

    def retrieval_diagnostics(
        self,
        question: str,
        filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return retrieval diagnostics without calling an LLM."""
        query_embedding = self.embed(question, kind="query")
        where = self._build_where(filters)

        strict_result = self._query_collection(
            query_embedding,
            self.settings.retrieval_k,
            where,
        )
        strict_chunks = self._to_chunks(strict_result)

        broad_result = self._query_collection(
            query_embedding,
            self.settings.retrieval_k,
            None,
        )
        broad_chunks = self._to_chunks(broad_result)

        return {
            "collection": self.chroma_collection.name,
            "collection_count": self.chroma_collection.count(),
            "embedding_provider": self.settings.embedding_provider,
            "embedding_model": self.settings.local_embedding_model,
            "filters": filters or {},
            "strict_result_count": len(strict_chunks),
            "broad_result_count": len(broad_chunks),
            "strict_scores": [round(c.score, 4) for c in strict_chunks],
            "broad_scores": [round(c.score, 4) for c in broad_chunks],
            "results": [
                {
                    "source_key": c.source_key,
                    "page": c.page,
                    "score": round(c.score, 4),
                    "document_id": c.document_id,
                }
                for c in broad_chunks
            ],
        }

    def index_records(self, records: list[dict[str, Any]]) -> None:
        """Index normalized chunks into Chroma."""
        if not records:
            return

        embeddings = [
            self.embed(record["text"], kind="passage")
            for record in records
            if record.get("text", "").strip()
        ]

        valid_records = [
            record
            for record in records
            if record.get("text", "").strip()
        ]

        if not valid_records:
            return

        # Normalize metadata so future filters are deterministic.
        metadatas = []
        for record in valid_records:
            metadata = {}
            for key, value in record.items():
                if key in {"id", "text"}:
                    continue
                if key in {"district", "disaster_type", "language"}:
                    metadata[key] = self._normalize_filter_value(value)
                else:
                    metadata[key] = value
            metadatas.append(metadata)

        self.chroma_collection.upsert(
            ids=[record["id"] for record in valid_records],
            documents=[record["text"] for record in valid_records],
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def _build_context(self, chunks: list[RetrievedChunk]) -> str:
        parts: list[str] = []
        total = 0

        for chunk in chunks:
            part = (
                f"[Document: {chunk.source_key}; page {chunk.page}; "
                f"score {chunk.score:.3f}]\n{chunk.text}"
            )
            if total + len(part) > self.settings.max_context_characters:
                break
            parts.append(part)
            total += len(part)

        return "\n\n".join(parts)

    def _build_system_prompt(self, language: str) -> str:
        requested_language = (
            "Marathi (Devanagari)"
            if language == "mr"
            else "English"
        )
        return (
            "You are a disaster-risk information assistant. "
            "Answer ONLY from the provided document excerpts. "
            "Do not use outside knowledge to fill gaps. "
            "If the excerpts are insufficient, say so clearly. "
            "Never invent locations, dates, statistics, thresholds, "
            "emergency procedures, or contacts. "
            f"Respond in {requested_language}. "
            "Keep the answer factual and concise. "
            "Cite supported claims using [source_key p.N]."
        )

    @staticmethod
    def _extract_openai_style_text(data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if output_text:
            return str(output_text).strip()

        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return str(text).strip()

        return ""

    def _answer_with_grok(self, system: str, prompt: str) -> str:
        if not self.settings.grok_api_key:
            raise RuntimeError("GROK_API_KEY is not configured.")

        url = f"{self.settings.grok_base_url.rstrip('/')}/responses"
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {self.settings.grok_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.grok_model,
                "input": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=self.settings.grok_timeout_seconds,
        )
        response.raise_for_status()

        answer = self._extract_openai_style_text(response.json())
        if not answer:
            raise RuntimeError("Grok returned an empty response.")
        return answer

    def _answer_with_gemini(self, system: str, prompt: str) -> str:
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        response = httpx.post(
            url,
            params={"key": self.settings.gemini_api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1},
            },
            timeout=self.settings.gemini_timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates.")

        parts = candidates[0].get("content", {}).get("parts", [])
        answer = "".join(
            str(part.get("text", ""))
            for part in parts
            if part.get("text")
        ).strip()

        if not answer:
            raise RuntimeError("Gemini returned an empty response.")
        return answer

    def _answer_with_ollama(self, system: str, prompt: str) -> str:
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/chat"
        response = httpx.post(
            url,
            json={
                "model": self.settings.ollama_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.1},
            },
            timeout=self.settings.ollama_timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        answer = (
            data.get("message", {}).get("content", "").strip()
        )
        if not answer:
            raise RuntimeError("Ollama returned an empty response.")
        return answer

    def _answer_with_bedrock(self, system: str, prompt: str) -> str:
        response = self.bedrock.converse(
            modelId=self.settings.bedrock_chat_model_id,
            system=[{"text": system}],
            messages=[
                {"role": "user", "content": [{"text": prompt}]}
            ],
            inferenceConfig={
                "maxTokens": 900,
                "temperature": 0.1,
            },
        )
        return response["output"]["message"]["content"][0]["text"]

    def answer(
        self,
        question: str,
        language: str,
        chunks: list[RetrievedChunk],
    ) -> str:
        """Generate a grounded answer using the configured provider."""
        if not chunks:
            return (
                "The available documents do not contain enough "
                "information to answer this question."
            )

        context = self._build_context(chunks)
        system_prompt = self._build_system_prompt(language)
        prompt = (
            f"Question:\n{question}\n\n"
            f"Document excerpts:\n{context}"
        )

        providers = {
            "grok": self._answer_with_grok,
            "gemini": self._answer_with_gemini,
            "ollama": self._answer_with_ollama,
            "bedrock": self._answer_with_bedrock,
        }

        provider = self.settings.answer_provider.strip().lower()
        if provider not in providers:
            raise ValueError(
                "ANSWER_PROVIDER must be one of: "
                "grok, gemini, ollama, bedrock."
            )

        # The configured provider is the primary provider. If it fails,
        # use the other providers in a deterministic fallback order.
        fallback_order = {
            "grok": ["gemini", "ollama"],
            "gemini": ["ollama", "grok"],
            "ollama": ["gemini", "grok"],
            "bedrock": ["ollama", "grok"],
        }[provider]

        errors: list[str] = []

        for name in [provider, *fallback_order]:
            try:
                return providers[name](system_prompt, prompt)
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        raise RuntimeError(
            "All configured answer providers failed. "
            + " | ".join(errors)
        )
