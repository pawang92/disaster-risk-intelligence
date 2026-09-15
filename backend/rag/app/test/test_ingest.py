from app.ingest import chunk_text, language_of


def test_marathi_is_detected() -> None:
    assert language_of("पूरस्थितीची माहिती") == "mr"


def test_chunking_preserves_all_content() -> None:
    text = "पहिले वाक्य. " * 80
    chunks = chunk_text(text, max_chars=100, overlap_chars=15)
    assert len(chunks) > 1
    assert all(len(chunk) <= 115 for chunk in chunks)
    assert "पहिले वाक्य" in chunks[0]
