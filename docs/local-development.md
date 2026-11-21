# Local development

The local development stack does not require AWS. For the complete dashboard workflow and Compose ports, see the root [README](../README.md).

## Risk API

From the repository root in PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements-dev.txt
$env:BUILDING_EXPOSURE_BACKEND = "disabled"
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Set `BUILDING_EXPOSURE_BACKEND=postgis` only after PostGIS is reachable and the required exposure tables are loaded. Tests are in `backend/app/test/`.

## RAG API

Follow [backend/rag/SETUP.md](../backend/rag/SETUP.md). It uses its own environment and starts on host port 8080. The risk API defaults to `RAG_API_URL=http://127.0.0.1:8080`.

## Dashboard

In a third terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

The dashboard opens at [http://127.0.0.1:5173](http://127.0.0.1:5173) and Vite proxies API calls to port 8000.

## Compose services

`docker compose up --build` starts the dashboard/API on host port 8000, RAG on 8080, PostGIS on 5432, and Ollama on 11434. The fresh PostGIS volume has no exposure tables; load data before turning on PostGIS building/railway/critical asset exposure. The RAG container downloads its local embedding model into a persistent Hugging Face volume on first use unless `LOCAL_EMBEDDING_FILES_ONLY=true` and the model has already been cached.

\n