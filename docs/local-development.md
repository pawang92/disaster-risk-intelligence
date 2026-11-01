# Local Development

The primary development environment is local. AWS is not required for development or testing.

## Current local foundation
- FastAPI RAG API
- Chroma vector store
- multilingual E5 local embeddings
- Ollama local LLM
- PostgreSQL + PostGIS
- Redis
- Docker Compose

## Native RAG development
From `backend/rag`:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env.local
```

Set `ANSWER_PROVIDER=ollama`, `EMBEDDING_PROVIDER=local`, and the local Ollama/Chroma values in `.env.local`.

Start Ollama with `ollama pull gemma3:4b`, then start the API with `uvicorn app.main:app --reload --port 8000`.

Health: `http://localhost:8000/health`
API docs: `http://localhost:8000/docs`

## Docker Compose
From the repository root:

```bash
docker compose up -d --build
```

Services: RAG API `:8000`, PostgreSQL/PostGIS `:5432`, Redis `:6379`, Ollama `:11434`.

Check with `docker compose ps` and `docker compose logs -f rag`.

## Embedding behavior
The application uses `local_files_only=True` for the E5 model, so inference does not download from Hugging Face.

Verify the native cache with:

```cmd
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base', local_files_only=True); print('MODEL LOAD OK')"
```

The Docker image must be supplied with the model cache before container RAG inference is used.

## No AWS requirement
The local profile does not require AWS credentials, Bedrock, S3, RDS, SQS, EventBridge, CloudFront or Cognito.

## Development workflow
1. Implement locally.
2. Run tests.
3. Run integration/end-to-end checks.
4. Build Docker images.
5. Validate Compose.
6. Prepare AWS only after local acceptance.