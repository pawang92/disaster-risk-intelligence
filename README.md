# Disaster Risk Intelligence

Local-first geospatial decision support for flood analysis in Mumbai Suburban. The workspace serves the dashboard and API from one FastAPI application, reads local vector and raster files from `data/`, routes spatial questions to map layers, and can forward document questions to the existing RAG service.

## What is here

- **Interactive dashboard** (`frontend/`): React + TypeScript, MapLibre GL JS, spatial map selection, GIS operation starters, result inspection, RAG guidance, and GeoJSON export.
- **Spatial API** (`backend/app/`): health, overview, local dataset catalog, GeoJSON map layers, geometric selection analysis, and the RAG guidance proxy.
- **Earth Engine downloader** (`scripts/gee_download.py`): repeatable downloads of Sentinel-1 VV, IMERG precipitation, NASADEM elevation, JRC surface-water occurrence, and WorldPop rasters, with a provenance manifest.
- **Existing document RAG** (`backend/rag/`): document ingestion and `/v1/ask` service, kept as its own deployable component.

## Run the dashboard and spatial API

Start the FastAPI data API from the repository root in PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In a second terminal, start the React dashboard:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite forwards `/api` calls to FastAPI on port 8000. The FastAPI docs are at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

Set `VITE_MAP_STYLE_URL` in `frontend/.env.local` to a MapLibre style URL. The default is MapLibre's public demo style; use a self-hosted or licensed basemap style for regular production use. Run `npm run build` to create `frontend/dist/`; FastAPI serves that build from `/` when present.

The data directory defaults to this repository's `data/` folder. Set `DISASTER_DATA_DIR` to use a mounted or external data directory. `CORS_ORIGINS` accepts a comma-separated origin list if the frontend is hosted separately.

The settings in `.env.example` are documentation; the FastAPI app reads process environment variables directly. Set optional values in PowerShell before starting Uvicorn, for example `$env:DISASTER_DATA_DIR = "E:\\risk-data"`.

### Container

Build from the repository root and mount the data directory read-only:

```powershell
docker build -f backend/Dockerfile -t disaster-risk-intelligence .
docker run --rm -p 8000:8000 -v "${PWD}/data:/app/data:ro" disaster-risk-intelligence
```

The image runs as a non-root user and has a health check. The `.dockerignore` excludes the local data so the image stays portable; provide rasters and vectors through a volume or object-storage adapter.

## Connect document guidance

Start the existing RAG service in a separate terminal from its own directory. Set its API URL if it is not at the default `http://127.0.0.1:8080`:

```powershell
Set-Location backend\rag
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

In the dashboard/API terminal, set `$env:RAG_API_URL = "http://127.0.0.1:8080"` before starting its Uvicorn process if the RAG service uses a different address.

The local RAG service needs its own dependencies, configuration, and indexed documents. Follow [backend/rag/SETUP.md](backend/rag/SETUP.md). In the dashboard, choose **Guidance RAG** to ask policy and preparedness questions; choose **Spatial operations** for feature-based analysis.

The spatial query panel can call the GeoAI Copilot workflow through the adapter in `backend/app/main.py`. Start the copilot backend in its own environment with its database and agents configured, then set the dashboard/API process to:

```powershell
$env:SPATIAL_PROVIDER = "geoai"
$env:GEOAI_API_URL = "http://127.0.0.1:8002"
```

For the current GeoAI Copilot FastAPI route, start it from its `backend` directory on port 8002:

```powershell
Set-Location D:\python_projects\geoai-copilot\backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8002
```

The adapter sends `/api/v1/query/natural` a natural language query, session ID, and drawn GeoJSON selection, then normalizes returned geometries and workflow steps for the map. With `SPATIAL_PROVIDER=local`, this app uses transparent keyword layer routing and optional intersection against local data. The sibling GeoAI Copilot source remains unchanged.

To route guidance requests to the separate Enterprise Document Intelligence API instead, start that service on port 8001 and set these values in the dashboard/API terminal before starting this app:

```powershell
$env:GUIDANCE_PROVIDER = "enterprise"
$env:GUIDANCE_API_URL = "http://127.0.0.1:8001"
```

The adapter calls its `/chat` endpoint with document retrieval enabled and normalizes the answer and source snippets for the dashboard. The separate repository remains untouched; its current API response fields do not provide the same page citations as the local RAG service.

## Google Earth Engine data retrieval

1. Create/register a Google Cloud project for Earth Engine and authenticate once:

   ```powershell
   python -m pip install -r scripts\requirements-gee.txt
   earthengine authenticate
   $env:EARTHENGINE_PROJECT = "your-earth-engine-project-id"
   ```

2. Download the default Mumbai vicinity, or provide a single Polygon GeoJSON boundary in EPSG:4326:

   ```powershell
   python scripts\gee_download.py --project $env:EARTHENGINE_PROJECT
   python scripts\gee_download.py --project $env:EARTHENGINE_PROJECT --aoi data\district_boundary.geojson --start 2024-07-01 --end 2024-09-01
   ```

The default destination is `data/gee_downloads/`; each run writes a `manifest.json` with collection IDs, units, resolution, period, AOI, and file sizes. The Sentinel-1 and IMERG date range uses a start-inclusive/end-exclusive interval. This downloader uses Earth Engine `getDownloadURL`, intended for smaller requests; large areas should use Earth Engine batch exports to Cloud Storage. The default AOI is an approximate Mumbai Suburban vicinity rectangle; pass an authoritative district boundary for analysis. [Earth Engine authentication guide](https://developers.google.com/earth-engine/guides/auth) · [Image download limits and formats](https://developers.google.com/earth-engine/apidocs/ee-image-getdownloadurl).

## API surface

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/health` | Service health |
| `GET /api/v1/overview` | Summary metrics, available layers, and dataset groups |
| `GET /api/v1/catalog` | Local data file inventory |
| `GET /api/v1/layers/{flood_extent\|buildings\|rivers}` | GeoJSON layer; optional `west`, `south`, `east`, `north`, and `limit` |
| `GET /api/v1/rasters/{raster_id}` | Bounded (max 700×700) PNG preview plus geographic bounds and source CRS for available raster layers |
| `POST /api/v1/analyze` | Keyword-routed layer query with optional GeoJSON selection geometry |
| `POST /api/v1/guidance` | Forward a document question to the existing RAG API |

## Scope and data interpretation

The source data in `data/` is currently local and partly untracked by Git because of its size. The dashboard discovers supported files at startup/request time; keep raw rasters and large vectors in local storage or object storage, not in application source control. GeoJSON map layers are currently building footprints, observed flood extent, and the river network.

The disaster-risk checkout contains no tracked calibrated risk engine or GeoAI LangGraph source. The dashboard can forward to the separate GeoAI Copilot API using the adapter above, but its LangGraph and GIS execution remain in that service. The local fallback selects relevant layers with transparent keyword rules, optionally filters features by geometric intersection, and returns source-feature counts. Neither path in this checkout infers flood depth, population exposed, forecasts, or a calibrated risk score. No sibling repository was modified.

For a production deployment, add identity and role controls, background jobs for large raster analysis and Earth Engine exports, PostGIS/object storage for larger layers, request limits, audit records, and monitored risk-model versioning. Keep model outputs traceable to source file, processing date, CRS, resolution, and model version.
