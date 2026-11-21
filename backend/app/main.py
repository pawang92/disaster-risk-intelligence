from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.risk import router as risk_router
from app.core.config import get_settings
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx

ROOT = Path(__file__).resolve().parents[2]
_configured_data_root = Path(os.getenv("DISASTER_DATA_DIR", ROOT / "data")).expanduser()
DATA_ROOT = (_configured_data_root if _configured_data_root.is_absolute() else ROOT / _configured_data_root).resolve()
WEB_ROOT = ROOT / "frontend" / "dist"
logger = logging.getLogger("disaster_risk.api")

app = FastAPI(
    title="Disaster Risk Intelligence API",
    description="Local-first geospatial data catalog, map layers, spatial queries, and document guidance API.",
    version="1.0.0",
)
settings = get_settings()
app.include_router(risk_router, prefix=settings.api_prefix)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health_check():
    return {
        "status": "ok",
        "service": "disaster-risk-intelligence",
        "environment": get_settings().environment,
    }

@app.get("/api/v1/overview")
def overview() -> dict[str, Any]:
    return _overview()


@app.get("/api/v1/catalog")
def catalog() -> dict[str, Any]:
    datasets = _file_catalog()
    return {"datasets": datasets, "total": len(datasets)}


@app.get("/api/v1/layers/{layer_id}")
def get_layer(
    layer_id: str,
    west: float | None = Query(default=None, ge=-180, le=180),
    south: float | None = Query(default=None, ge=-90, le=90),
    east: float | None = Query(default=None, ge=-180, le=180),
    north: float | None = Query(default=None, ge=-90, le=90),
    limit: int = Query(default=5000, ge=1, le=20000),
) -> dict[str, Any]:
    if layer_id not in LAYER_CONFIG:
        raise HTTPException(status_code=404, detail="Unknown map layer")
    bbox = None
    if any(value is not None for value in (west, south, east, north)):
        if None in (west, south, east, north) or west >= east or south >= north:
            raise HTTPException(status_code=422, detail="Provide a valid west,south,east,north bounding box")
        bbox = (west, south, east, north)
    try:
        return _feature_collection(layer_id, bbox, limit)
    except Exception as exc:
        logger.exception("Failed to load layer %s", layer_id)
        raise HTTPException(status_code=503, detail=f"Could not read {layer_id} source data") from exc


@app.post("/api/v1/analyze")
def analyze(payload: AnalysisRequest) -> dict[str, Any]:
    text = payload.query.strip()
    lower = text.casefold()
    provider = os.getenv("SPATIAL_PROVIDER", "local").lower()
    if provider == "geoai":
        service_url = os.getenv("GEOAI_API_URL", "http://127.0.0.1:8002").rstrip("/")
        try:
            response = httpx.post(f"{service_url}/api/v1/query/natural",
                                  json={"text": text, "selected_geometry": payload.geometry, "session_id": payload.session_id},
                                  timeout=httpx.Timeout(120.0, connect=3.0))
            response.raise_for_status()
            result = response.json()
            features: list[dict[str, Any]] = []
            _extract_geoai_features(result.get("results", {}), features)
            total = int(result.get("total_count", len(features)) or 0)
            message = result.get("message") or "Spatial query completed."
            return {"query": text, "answer": message,
                    "layers": [result.get("agent_used") or "GeoAI"],
                    "counts": {result.get("agent_used") or "GeoAI results": total},
                    "feature_collection": {"type": "FeatureCollection", "features": features},
                    "provenance": {"provider": "geoai-copilot", "success": result.get("success", True),
                                   "session_id": result.get("session_id"), "steps": result.get("steps", [])},
                    "limitations": []}
        except httpx.ConnectError as exc:
            raise HTTPException(status_code=503, detail="GeoAI Copilot is offline. Start it and check GEOAI_API_URL.") from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=503, detail="GeoAI Copilot returned an error. Check its API logs and configuration.") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="GeoAI Copilot did not respond in time.") from exc
    if provider != "local":
        raise HTTPException(status_code=503, detail="SPATIAL_PROVIDER must be local or geoai")
    requested = []
    if any(word in lower for word in ("building", "structure", "exposure", "people", "population")):
        requested.append("buildings")
    if any(word in lower for word in ("river", "stream", "drain")):
        requested.append("rivers")
    if any(word in lower for word in ("flood", "inundat", "hazard", "risk", "water")):
        requested.append("flood_extent")
    if not requested:
        requested = ["flood_extent", "buildings"]

    geometries = []
    features = []
    counts = {}
    try:
        selection = None
        if payload.geometry:
            from shapely.geometry import shape
            selection = shape(payload.geometry)
            if selection.is_empty or not selection.is_valid:
                raise HTTPException(status_code=422, detail="Selection geometry must be valid GeoJSON geometry")
        bbox = tuple(selection.bounds) if selection is not None else None
        for layer_id in requested:
            collection = _feature_collection(layer_id, bbox=bbox, limit=20000)
            matching = []
            for feature in collection["features"]:
                geometry = feature.get("geometry")
                if not geometry:
                    continue
                if selection is not None:
                    from shapely.geometry import shape
                    try:
                        if not selection.intersects(shape(geometry)):
                            continue
                    except Exception:
                        continue
                feature["properties"] = {**(feature.get("properties") or {}), "layer": layer_id}
                matching.append(feature)
                features.append(feature)
            counts[layer_id] = len(matching)
        if selection is not None and not features:
            answer = "No returned features from the selected layers intersect the selected geometry."
        else:
            selection_label = "the selected area" if selection is not None else "the available Mumbai Suburban datasets"
            answer = f"Loaded {sum(counts.values()):,} returned features across {len(requested)} relevant layer(s) in {selection_label}. Results are bounded samples; population exposure and forecast risk are not inferred from feature counts."
        return {
            "query": text,
            "answer": answer,
            "layers": requested,
            "counts": counts,
            "feature_collection": {"type": "FeatureCollection", "features": features},
            "provenance": {"data_root": str(DATA_ROOT), "method": "keyword layer routing and optional geometric intersection", "as_of": None},
            "limitations": ["Feature output is bounded to the first 20,000 records per layer (or the selected bounding box); zero matches do not prove complete absence."]
                          + (["This checkout contains no tracked risk engine source. Counts describe mapped source features and are not a calibrated risk score."]
                             if "flood_extent" in requested and "buildings" in requested else [])
                          + (["This query lists river and flood layers; it does not calculate nearest distance or hydrologic connectivity."]
                             if any(word in lower for word in ("near", "nearest", "close")) and "rivers" in requested else []),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analysis request failed")
        raise HTTPException(status_code=503, detail="Spatial analysis could not be completed") from exc


@app.post("/api/v1/guidance")
def guidance(payload: GuidanceRequest) -> dict[str, Any]:
    """Route policy questions to either local RAG backend using a normalized response."""
    provider = os.getenv("GUIDANCE_PROVIDER", "local").lower()
    if provider == "enterprise":
        service_url = os.getenv("GUIDANCE_API_URL", "http://127.0.0.1:8001").rstrip("/")
        endpoint = "/chat"
        request = {"message": payload.question, "use_documents": True}
    elif provider == "local":
        service_url = os.getenv("RAG_API_URL", "http://127.0.0.1:8080").rstrip("/")
        endpoint = "/v1/ask"
        request = {"question": payload.question, "language": payload.language,
                   "district": payload.district, "disaster_type": payload.disaster_type}
    else:
        raise HTTPException(status_code=503, detail="GUIDANCE_PROVIDER must be local or enterprise")
    try:
        response = httpx.post(f"{service_url}{endpoint}", json=request, timeout=httpx.Timeout(90.0, connect=3.0))
        response.raise_for_status()
        result = response.json()
        if provider == "enterprise":
            citations = [{"source_key": source.get("title") or source.get("source_key") or "Document source",
                          "location": f"chunk {source['chunk_id']}" if source.get("chunk_id") is not None else None,
                          "excerpt": source.get("content", "")[:500], "score": source.get("relevance")}
                         for source in (result.get("sources") or [])]
            return {"answer": result.get("response", ""), "language": payload.language,
                    "citations": citations, "service": "enterprise-document-intelligence"}
        return {"answer": result.get("answer", ""), "language": result.get("language", payload.language),
                "citations": result.get("citations", []), "service": "local-disaster-rag"}
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="Guidance service is offline. Start the RAG API on its configured URL.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=503, detail="Guidance service returned an error. Check its API logs and configuration.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Guidance service did not respond in time.") from exc


if WEB_ROOT.exists():
    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    index = WEB_ROOT / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Dashboard build is missing. Start Vite in development or run npm run build.")
    return FileResponse(index)
