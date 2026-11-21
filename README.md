# Disaster Risk Intelligence

Local-first geospatial decision support for flood analysis in Mumbai Suburban. The workspace serves the dashboard and API from one FastAPI application, reads local vector and raster files from `data/`, routes spatial questions to map layers, and can forward document questions to the existing RAG service.

## What is here

- **Interactive dashboard** (`frontend/`): React + TypeScript, MapLibre GL JS, spatial map selection, GIS operation starters, result inspection, RAG guidance, and GeoJSON export.
- **Spatial API** (`backend/app/`): health, overview, local dataset catalog, GeoJSON map layers, geometric selection analysis, and the RAG guidance proxy.
- **Earth Engine downloader** (`scripts/gee_download.py`): repeatable downloads of Sentinel-1 VV, IMERG precipitation, NASADEM elevation, JRC surface-water occurrence, and WorldPop rasters, with a provenance manifest.
- **Existing document RAG** (`backend/rag/`): document ingestion and `/v1/ask` service, kept as its own deployable component.

## Run the dashboard and spatial API

Start the FastAPI data API from the repository root in PowerShell:

```text
React Dashboard (planned)
        |
     FastAPI
        |
+-------+----------------+
|       |                |
Risk   RAG          AI Gateway
planned current       current
        |
   Local E5 + Chroma
        |
     Ollama
        |
 PostgreSQL/PostGIS + Redis
```

Grok and Gemini are optional external providers behind the LLM layer. Ollama is the local fallback.

## Current status

- Local FastAPI RAG: implemented
- Local multilingual E5 embeddings: implemented
- Chroma persistence: implemented
- PDF ingestion/chunking/metadata: implemented
- Retrieval diagnostics: implemented
- Grok/Gemini/Ollama provider paths: implemented
- Local Docker foundation: implemented
- PostgreSQL/PostGIS container: implemented
- Redis container: implemented
- Flood-risk engine: planned
- React dashboard: planned
- AI Copilot tools: planned
- Real-time event system: planned
- AWS deployment: planned

Do not treat planned components as implemented.

## Local quick start

NaN
NaN
NaN

API:
- http://localhost:8000
- http://localhost:8000/docs
- http://localhost:8000/health

For native development, see docs/local-development.md.

## Implementation phases

1. Repository audit
2. Local foundation
3. Production RAG
4. LLM Gateway
5. GIS/PostGIS platform
6. Flood Risk Engine
7. Real-time data and workers
8. Dashboard
9. AI Copilot
10. Local end-to-end acceptance
11. Production hardening
12. AWS deployment

Each phase is inspected, implemented, tested and documented before the next phase begins.