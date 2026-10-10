"""PDF ingestion CLI and S3-event handler.

Text PDFs are extracted with pypdf. For scanned English/Marathi PDFs,
optional OCR can be enabled with --ocr.
"""

import argparse
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

import boto3
from pypdf import PdfReader

from .bedrock_rag import DisasterRag
from .config import get_settings


def normalize_text(text: str) -> str:
    """Normalize whitespace while preserving sentence boundaries."""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def language_of(text: str) -> str:
    return "mr" if re.search(r"[\u0900-\u097F]", text) else "en"


def chunk_text(
    text: str,
    max_chars: int = 1400,
    overlap_chars: int = 180,
) -> list[str]:
    """Create bounded chunks using paragraph/sentence boundaries."""
    if max_chars <= overlap_chars:
        raise ValueError("max_chars must be greater than overlap_chars.")

    clean = normalize_text(text)
    if not clean:
        return []

    paragraphs = re.split(r"\n{2,}", clean)
    chunks: list[str] = []
    current = ""

    def emit(value: str) -> None:
        value = value.strip()
        if value:
            chunks.append(value)

    for paragraph in paragraphs:
        sentences = re.split(
            r"(?<=[.!?।])\s+",
            paragraph.strip(),
        )

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Split very long sentences deterministically.
            if len(sentence) > max_chars:
                start = 0
                while start < len(sentence):
                    end = min(start + max_chars, len(sentence))
                    part = sentence[start:end].strip()
                    if part:
                        if current:
                            emit(current)
                            current = ""
                        emit(part)
                    start += max_chars - overlap_chars
                continue

            candidate = f"{current} {sentence}".strip()

            if current and len(candidate) > max_chars:
                emit(current)
                overlap = current[-overlap_chars:].strip()
                current = f"{overlap} {sentence}".strip()
            else:
                current = candidate

    emit(current)
    return chunks


def extract_pages(pdf_bytes: bytes, ocr: bool = False) -> list[str]:
    """Extract page text and OCR the document when pages have little/no text."""
    pages = [
        normalize_text(page.extract_text() or "")
        for page in PdfReader(io.BytesIO(pdf_bytes)).pages
    ]

    if not ocr:
        return pages

    low_text_pages = [
        index for index, text in enumerate(pages)
        if len(text) < 80
    ]

    if not low_text_pages:
        return pages

    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise RuntimeError(
            "OCR is required for low-text/scanned pages. "
            "Install pytesseract and pdf2image, plus the Tesseract/PDF "
            "system dependencies."
        ) from exc

    images = convert_from_bytes(
        pdf_bytes,
        dpi=250,
    )

    for index in low_text_pages:
        if index >= len(images):
            continue

        ocr_text = normalize_text(
            pytesseract.image_to_string(
                images[index],
                lang="eng+mar",
            )
        )

        # Keep the better extraction. OCR should not replace good PDF text.
        if len(ocr_text) > len(pages[index]):
            pages[index] = ocr_text

    return pages


def ensure_index(rag: DisasterRag) -> None:
    _ = rag.chroma_collection


def index_pdf(
    pdf_bytes: bytes,
    source_key: str,
    metadata: dict[str, str],
    ocr: bool = False,
    dry_run: bool = False,
) -> int:
    rag = DisasterRag(get_settings())
    document_id = hashlib.sha256(pdf_bytes).hexdigest()
    records: list[dict[str, Any]] = []

    district = " ".join(metadata.get("district", "").strip().lower().split())
    disaster_type = " ".join(
        metadata.get("disaster_type", "").strip().lower().split()
    )

    for page_number, page in enumerate(
        extract_pages(pdf_bytes, ocr=ocr),
        start=1,
    ):
        for ordinal, text in enumerate(chunk_text(page)):
            records.append(
                {
                    "id": f"{document_id}-{page_number}-{ordinal}",
                    "text": text,
                    "document_id": document_id,
                    "source_key": source_key,
                    "page": page_number,
                    "language": language_of(text),
                    "district": district,
                    "disaster_type": disaster_type,
                }
            )

    if dry_run:
        return len(records)

    ensure_index(rag)
    rag.index_records(records)
    return len(records)


def read_source(source: str) -> tuple[bytes, str]:
    if source.startswith("s3://"):
        bucket, key = source.removeprefix("s3://").split("/", 1)
        return (
            boto3.client("s3")
            .get_object(Bucket=bucket, Key=key)["Body"]
            .read(),
            key,
        )

    path = Path(source)
    return path.read_bytes(), path.name


def lambda_handler(
    event: dict[str, Any],
    _context: Any,
) -> dict[str, int]:
    """S3 ObjectCreated handler."""
    indexed = 0

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        content, source_key = read_source(
            f"s3://{bucket}/{key}"
        )

        tags = boto3.client("s3").get_object_tagging(
            Bucket=bucket,
            Key=key,
        )["TagSet"]

        metadata = {
            item["Key"]: item["Value"]
            for item in tags
            if item["Key"] in {"district", "disaster_type"}
        }

        indexed += index_pdf(
            content,
            source_key,
            metadata,
        )

    return {"indexed_chunks": indexed}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index an English or Marathi disaster PDF"
    )
    parser.add_argument(
        "source",
        help="Local PDF path or s3://bucket/key",
    )
    parser.add_argument("--district", default="")
    parser.add_argument("--disaster-type", default="")
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="OCR pages with little/no extracted text",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count chunks without embedding or writing to Chroma",
    )

    args = parser.parse_args()

    content, key = read_source(args.source)
    settings = get_settings()

    print(f"Embedding provider: {settings.embedding_provider}")

    count = index_pdf(
        content,
        key,
        {
            "district": args.district,
            "disaster_type": args.disaster_type,
        },
        args.ocr,
        args.dry_run,
    )

    print(
        json.dumps(
            {
                "source": key,
                "chunks": count,
                "dry_run": args.dry_run,
            }
        )
    )


if __name__ == "__main__":
    main()
