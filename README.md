# Disaster Risk Intelligence — Astra

Local-first production architecture for Flood Risk Intelligence, designed to expand to cyclone, drought, landslide, wildfire, heatwave and multi-hazard intelligence.

## Architecture principle

The complete development and test system must run locally without AWS credentials or Amazon Bedrock Foundation Models.

Current foundation:

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