# Local document RAG setup

The RAG service is a separate FastAPI application in `backend/rag/`. Keep its environment and index separate from the risk API. The local profile uses multilingual E5 embeddings, Chroma persistence, and Ollama for answer generation. AWS credentials are optional unless you select Bedrock.

## 1. Install the local services

Install Python 3.11+, then in PowerShell:

```powershell
Set-Location D:\python_projects\disaster-risk-intelligence\backend\rag
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env.local
```

The default setting allows the E5 model to download into the Hugging Face cache on first use. You can warm it before starting the API to avoid a slow first request:

```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"
```

Install [Ollama](https://ollama.com/download) and fetch the configured chat model:

```powershell
ollama pull gemma3:4b
```

The default `.env.example` uses `EMBEDDING_PROVIDER=local`, `ANSWER_PROVIDER=ollama`, and a Chroma directory at `./.chroma`. Set `LOCAL_EMBEDDING_FILES_ONLY=true` only after the model is present in the runtime's Hugging Face cache. Edit `.env.local` to change providers. Keep API keys out of Git and logs. If using Bedrock, configure AWS credentials through the normal AWS credential chain; do not paste access keys into this file.

## 2. Ingest guidance PDFs

Still inside `backend/rag/` with the virtual environment activated:

```powershell
python -m app.ingest "C:\path\to\flood-guidance.pdf" --district mumbai --disaster-type flood --dry-run
```

Review the extraction/chunk count. For scanned PDFs, run with `--ocr` after installing the local OCR tools. Then remove `--dry-run` to index the document:

```powershell
python -m app.ingest "C:\path\to\flood-guidance.pdf" --district mumbai --disaster-type flood
```

The CLI writes to the configured Chroma path. Keep the index directory persistent and backed up. Re-ingest into a new collection and verify it before switching if you change embedding models; vectors from different embedding models must not be mixed.

## 3. Start the RAG API

From `backend/rag/`:

```powershell
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Open [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs). Use `POST /v1/ask` for an English or Marathi question. `GET /health` reports the configured provider and Chroma collection. Retrieval diagnostics are disabled unless `DEBUG=true`; do not enable that setting on a public service.

The risk API forwards guidance questions to `http://127.0.0.1:8080` by default. Set `RAG_API_URL` in the risk API process to change it. In Docker Compose the API uses the internal address `http://rag:8000`, while your host reaches RAG at port 8080.

## Provider choices

Supported answer providers are `ollama`, `grok`, `gemini`, and `bedrock`. Embeddings support `local` and `bedrock`. `ANSWER_PROVIDER=auto` is not supported. Set a specific provider and configure its credentials or local service. Provider fallback order is configured in `DisasterRag.answer`; review outbound data policies before enabling external providers because retrieved document excerpts are sent with the question.

## Production boundary

This setup is for local development. Chroma is a single-node persistent store, ingestion is a CLI, and the API does not yet enforce user/document authorization or rate limits. Follow [the production RAG plan](../../docs/production-rag.md) before exposing the service to users.

\n