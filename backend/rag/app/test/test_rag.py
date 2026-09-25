from types import SimpleNamespace
import pytest

from app.bedrock_rag import DisasterRag
from app.ingest import chunk_text, language_of, normalize_text


class FakeCollection:
    name = "disaster-guidance-local"

    def __init__(self):
        self.calls = []

    def count(self):
        return 2

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "documents": [["Flood warning for Pune district."]],
            "metadatas": [[
                {
                    "document_id": "doc-1",
                    "source_key": "guide.pdf",
                    "page": 2,
                    "language": "en",
                }
            ]],
            "distances": [[0.18]],
        }


def make_settings(**overrides):
    values = {
        "embedding_provider": "local",
        "local_embedding_model": "intfloat/multilingual-e5-base",
        "chroma_collection": "disaster-guidance",
        "chroma_path": ".chroma-test",
        "retrieval_k": 6,
        "retrieval_fallback_k": 3,
        "min_retrieval_score": 0.20,
        "max_context_characters": 12000,
        "answer_provider": "ollama",
        "grok_api_key": "",
        "grok_base_url": "https://api.x.ai/v1",
        "grok_model": "grok-4.6",
        "grok_timeout_seconds": 30.0,
        "gemini_api_key": "",
        "gemini_model": "gemini-2.5-flash",
        "gemini_timeout_seconds": 30.0,
        "ollama_base_url": "http://127.0.0.1:11434",
        "ollama_model": "gemma3:4b",
        "ollama_timeout_seconds": 30.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_normalize_text():
    assert normalize_text("  Hello   world\n\n test  ") == (
        "Hello world\n\n test"
    )


def test_language_detection():
    assert language_of("Flood warning for Pune") == "en"
    assert language_of("पुणे जिल्ह्यात पूराचा इशारा") == "mr"


def test_chunk_text_respects_limit():
    text = "Sentence one. " * 250
    chunks = chunk_text(text, max_chars=300, overlap_chars=40)

    assert chunks
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_retrieval_returns_chunks(monkeypatch):
    service = DisasterRag(make_settings())
    fake_collection = FakeCollection()

    monkeypatch.setattr(
        service,
        "chroma_collection",
        fake_collection,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "embed",
        lambda text, kind="query": [0.1, 0.2, 0.3],
    )

    chunks = service.retrieve(
        "What is the flood warning?",
        {"district": "Pune"},
    )

    assert len(chunks) == 1
    assert chunks[0].source_key == "guide.pdf"
    assert chunks[0].page == 2
    assert chunks[0].score == pytest.approx(0.82)


def test_retrieval_diagnostics(monkeypatch):
    service = DisasterRag(make_settings())
    fake_collection = FakeCollection()

    monkeypatch.setattr(
        service,
        "chroma_collection",
        fake_collection,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "embed",
        lambda text, kind="query": [0.1, 0.2, 0.3],
    )

    diagnostics = service.retrieval_diagnostics(
        "flood warning",
        {"district": "Pune"},
    )

    assert diagnostics["collection_count"] == 2
    assert diagnostics["strict_result_count"] == 1
    assert diagnostics["broad_result_count"] == 1
