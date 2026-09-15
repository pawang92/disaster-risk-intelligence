"""PDF ingestion CLI and S3-event handler.

Text PDFs are extracted with pypdf. For scanned Marathi/English PDFs, install the
optional OCR dependencies and pass --ocr; the container includes eng+mar packs.
"""
import argparse
import hashlib
import io
import json
import re
from urllib.parse import unquote_plus
from pathlib import Path
from typing import Any

import boto3
from pypdf import PdfReader

from .bedrock_rag import DisasterRag
from .config import get_settings


def language_of(text: str) -> str:
    return "mr" if re.search(r"[\u0900-\u097F]", text) else "en"


def chunk_text(text: str, max_chars: int = 1400, overlap_chars: int = 180) -> list[str]:
    """Make language-neutral chunks, preferring sentence and paragraph boundaries."""
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    pieces = re.split(r"(?<=[.!?।])\s+|\n{2,}", clean)
    chunks, current = [], ""
    for piece in pieces:
        if len(piece) > max_chars:
            pieces_to_add = [piece[i:i + max_chars] for i in range(0, len(piece), max_chars - overlap_chars)]
        else:
            pieces_to_add = [piece]
        for part in pieces_to_add:
            candidate = f"{current} {part}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = f"{current[-overlap_chars:]} {part}".strip()
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def extract_pages(pdf_bytes: bytes, ocr: bool = False) -> list[str]:
    pages = [(page.extract_text() or "").strip() for page in PdfReader(io.BytesIO(pdf_bytes)).pages]
    if sum(map(len, pages)) >= 100 or not ocr:
        return pages
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise RuntimeError("Scanned PDF: install OCR extras or re-run with a text-extracted PDF") from exc
    return [pytesseract.image_to_string(image, lang="eng+mar") for image in convert_from_bytes(pdf_bytes, dpi=250)]


def ensure_index(rag: DisasterRag) -> None:
    _ = rag.chroma_collection


def index_pdf(pdf_bytes: bytes, source_key: str, metadata: dict[str, str], ocr: bool = False, dry_run: bool = False) -> int:
    rag = DisasterRag(get_settings())
    document_id = hashlib.sha256(pdf_bytes).hexdigest()
    records: list[dict[str, Any]] = []
    for page_number, page in enumerate(extract_pages(pdf_bytes, ocr=ocr), start=1):
        for ordinal, text in enumerate(chunk_text(page)):
            record = {"id": f"{document_id}-{page_number}-{ordinal}", "text": text, "document_id": document_id,
                      "source_key": source_key, "page": page_number, "language": language_of(text),
                      "district": metadata.get("district", ""), "disaster_type": metadata.get("disaster_type", "")}
            records.append(record)
    if dry_run:
        return len(records)
    ensure_index(rag)
    rag.index_records(records)
    return len(records)


def read_source(source: str) -> tuple[bytes, str]:
    if source.startswith("s3://"):
        bucket, key = source.removeprefix("s3://").split("/", 1)
        return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read(), key
    return Path(source).read_bytes(), Path(source).name


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    """S3 ObjectCreated handler; district/disaster_type come from S3 object tags."""
    indexed = 0
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        content, source_key = read_source(f"s3://{bucket}/{key}")
        tags = boto3.client("s3").get_object_tagging(Bucket=bucket, Key=key)["TagSet"]
        metadata = {item["Key"]: item["Value"] for item in tags if item["Key"] in {"district", "disaster_type"}}
        indexed += index_pdf(content, source_key, metadata)
    return {"indexed_chunks": indexed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Index an English or Marathi disaster PDF")
    parser.add_argument("source", help="Local PDF path or s3://bucket/key")
    parser.add_argument("--district", default="")
    parser.add_argument("--disaster-type", default="")
    parser.add_argument("--ocr", action="store_true", help="OCR scanned PDFs with English + Marathi models")
    parser.add_argument("--dry-run", action="store_true", help="Count extracted chunks without creating embeddings or writing data")
    args = parser.parse_args()
    content, key = read_source(args.source)
    settings = get_settings()
    print(f"Embedding provider: {settings.embedding_provider}")
    if settings.embedding_provider == "bedrock":
        print("Bedrock embeddings are enabled. Use EMBEDDING_PROVIDER=local to avoid Bedrock embedding quotas.")
    count = index_pdf(content, key, {"district": args.district, "disaster_type": args.disaster_type}, args.ocr, args.dry_run)
    print(json.dumps({"source": key, "chunks": count, "dry_run": args.dry_run}))


if __name__ == "__main__":
    main()
