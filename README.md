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
current current       current
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
- Flood-risk engine: implemented (flood-v0.1)
- React dashboard: planned
- AI Copilot tools: planned
- Real-time event system: planned
- AWS deployment: planned

Do not treat planned components as implemented.

## Local quick start

From the repository root, start PostGIS, Redis, Ollama, and the RAG API:

```bash
docker compose up -d --build
```

RAG API:
- http://localhost:8000
- http://localhost:8000/docs
- http://localhost:8000/health

From `backend`, install dependencies and start the flood risk API:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

Risk API:
- http://localhost:8001
- http://localhost:8001/docs
- http://localhost:8001/health

For native RAG development, see docs/local-development.md.

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


## Flood exposure analysis

The `POST /api/v1/risk/assess` response includes exposure metrics calculated against the configured mapped flood extent:

- `exposure.critical_assets_at_risk`: critical OpenStreetMap POIs intersecting the flood geometry.
- `risk_assessment.inputs.critical_infrastructure_exposure`: overall and per-category counts and percentages for configured POI classes.
- `exposure.roads_at_risk` and `risk_assessment.inputs.road_exposure`: road-segment exposure when a roads table is configured and enabled.
- Building and railway exposure remain available through the same response.

The denominator for POI and road percentages is the configured feature count inside the flood geometry's bounding box. A feature is counted as affected only if it intersects the flood geometry itself. These are mapped feature-exposure metrics; they do not prove that a facility is operational or that a road is impassable.

### Critical infrastructure

The default PostGIS source is `mumbai_suburban_poi`, with `fclass` and `geom` columns, alongside `mumbai_s1_flood_extent`. The adapter filters to hospitals, clinics, doctors, pharmacies, schools, universities, fire stations, police stations, shelters, nursing homes and selected community facilities. It uses the existing `critical_assets_at_risk` API field and provides category details under `exposure.details`.

### Road exposure

Road analysis is implemented but disabled by default because the current local database inventory does not include a roads table. After importing road segments with `fclass` and `geom` columns in the same SRID as the flood layer, configure:

```env
ROAD_EXPOSURE_ENABLED=true
ROAD_EXPOSURE_TABLE=mumbai_suburban_roads
```

The table name can be changed with `ROAD_EXPOSURE_TABLE`. Keep road exposure disabled until the configured table exists and has valid geometry. Road metrics count intersecting road features, not kilometers of road affected.
