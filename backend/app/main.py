from __future__ import annotations

import json
import logging
import os
import base64
import io
from functools import lru_cache
from pathlib import Path
from typing import Any

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AnalysisRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    geometry: dict[str, Any] | None = None
    session_id: str | None = Field(default=None, max_length=100)


class GuidanceRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    language: str = Field(default="auto", pattern="^(auto|en|mr)$")
    district: str | None = "mumbai"
    disaster_type: str | None = "flood"


def _extract_geoai_features(value: Any, features: list[dict[str, Any]]) -> None:
    """Normalize feature-like objects from GeoAI agent results into GeoJSON Features."""
    if isinstance(value, dict):
        geometry = value.get("geometry")
        if isinstance(geometry, dict) and geometry.get("type") and "coordinates" in geometry:
            properties = value.get("properties")
            if not isinstance(properties, dict):
                properties = {key: item for key, item in value.items() if key not in {"geometry", "id"}}
            features.append({"type": "Feature", "id": str(value.get("id", len(features))), "properties": properties, "geometry": geometry})
            return
        if value.get("type") == "FeatureCollection" and isinstance(value.get("features"), list):
            features.extend(feature for feature in value["features"] if isinstance(feature, dict) and feature.get("type") == "Feature")
            return
        for child in value.values():
            _extract_geoai_features(child, features)
    elif isinstance(value, list):
        for child in value:
            _extract_geoai_features(child, features)


LAYER_CONFIG = {
    "flood_extent": {"label": "Observed flood extent", "group": "Hazard", "color": "#f2775d", "files": ["flood_extent/mumbai_s1_flood_extent.geojson", "flood_extent/mumbai_s1_flood_extent.shp"]},
    "buildings": {"label": "Building footprints", "group": "Exposure", "color": "#ffc66e", "files": ["buildings/mumbai_building_footprints.shp", "buildings/mumbai_building_footprints.geojson"]},
    "rivers": {"label": "River network", "group": "Reference", "color": "#64c8f0", "files": ["rivers/mumbai_hydrosheds_river_network.geojson"]},
}

RASTER_CONFIG = {
    "raster_flood": {"label": "Observed flood raster", "group": "Hazard", "color": "#f2775d", "path": "flood_extent/mumbai_s1_flood_extent.tif", "palette": "flood"},
    "raster_rainfall": {"label": "IMerg rainfall total", "group": "Hazard", "color": "#64c8f0", "path": "rainfall/mumbai_imerg_total_rainfall_jul_aug_2024.tif", "palette": "rain"},
    "raster_elevation": {"label": "Elevation", "group": "Terrain", "color": "#b6c49b", "path": "dem/mumbai/srtm/srtm_mumbai.tif", "palette": "terrain"},
    "raster_historical_water": {"label": "Historical water occurrence", "group": "Hazard", "color": "#63a9db", "path": "historical_water/mumbai_jrc_water_occurrence.tif", "palette": "water"},
    "gee_sentinel1": {"label": "GEE Sentinel-1 VV median", "group": "Earth Engine", "color": "#c58fe8", "path": "gee_downloads/sentinel1_vv_median.tif", "palette": "terrain"},
    "gee_imerg": {"label": "GEE IMERG precipitation", "group": "Earth Engine", "color": "#64c8f0", "path": "gee_downloads/imerg_precipitation_sum.tif", "palette": "rain"},
    "gee_nasadem": {"label": "GEE NASADEM elevation", "group": "Earth Engine", "color": "#b6c49b", "path": "gee_downloads/nasadem_elevation.tif", "palette": "terrain"},
    "gee_jrc_water": {"label": "GEE JRC water occurrence", "group": "Earth Engine", "color": "#63a9db", "path": "gee_downloads/jrc_water_occurrence.tif", "palette": "water"},
    "gee_worldpop": {"label": "GEE WorldPop population", "group": "Earth Engine", "color": "#ffc66e", "path": "gee_downloads/worldpop_population.tif", "palette": "rain"},
}

RASTER_GROUPS = {
    "Rainfall": "rainfall", "Elevation": "dem", "Historical flood": "historical_flood",
    "Surface water": "historical_water", "Population": "population", "Flood detection": "flood_extent",
    "River indicators": "rivers",
}


def _local_file(relative: str) -> Path | None:
    path = (DATA_ROOT / relative).resolve()
    if DATA_ROOT not in path.parents:
        return None
    return path if path.is_file() else None


def _vector_source(layer_id: str) -> Path | None:
    config = LAYER_CONFIG.get(layer_id)
    if not config:
        return None
    for relative in config["files"]:
        path = _local_file(relative)
        if path:
            return path
    return None


@lru_cache(maxsize=6)
def _read_vector(layer_id: str, bbox: tuple[float, float, float, float] | None = None, limit: int = 5000):
    path = _vector_source(layer_id)
    if path is None:
        return None
    import geopandas as gpd

    kwargs: dict[str, Any] = {"rows": limit}
    if bbox:
        kwargs["bbox"] = bbox
    frame = gpd.read_file(path, **kwargs)
    if frame.crs is not None and frame.crs.to_epsg() != 4326:
        frame = frame.to_crs("EPSG:4326")
    return frame


def _vector_count(layer_id: str) -> int | None:
    path = _vector_source(layer_id)
    if path is None:
        return None
    try:
        import fiona
        with fiona.open(path) as source:
            return len(source)
    except Exception:
        return None


def _feature_collection(layer_id: str, bbox: tuple[float, float, float, float] | None = None, limit: int = 5000) -> dict[str, Any]:
    frame = _read_vector(layer_id, bbox, limit)
    if frame is None:
        return {"type": "FeatureCollection", "features": [], "metadata": {"available": False}}
    subset = frame
    data = json.loads(subset.to_json(drop_id=True))
    for feature in data["features"]:
        feature.setdefault("properties", {})
    data["metadata"] = {"available": True, "total": _vector_count(layer_id), "returned": len(data["features"]), "crs": "EPSG:4326", "limit": limit}
    return data


def _file_catalog() -> list[dict[str, Any]]:
    entries = []
    if not DATA_ROOT.exists():
        return entries
    for path in sorted(DATA_ROOT.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        suffix = path.suffix.lower()
        if suffix not in {".tif", ".tiff", ".geojson", ".shp", ".pdf", ".csv", ".gpkg"}:
            continue
        rel = path.relative_to(DATA_ROOT).as_posix()
        entries.append({"name": path.stem.replace("_", " "), "path": rel, "format": suffix[1:].upper(), "size_bytes": path.stat().st_size, "category": rel.split("/")[0]})
    return entries


def _overview() -> dict[str, Any]:
    datasets = _file_catalog()
    layer_meta = []
    for layer_id, config in LAYER_CONFIG.items():
        source = _vector_source(layer_id)
        count = _vector_count(layer_id)
        if source:
            if count is None:
                logger.warning("Unable to read feature count for layer %s", layer_id)
        layer_meta.append({"id": layer_id, "label": config["label"], "group": config["group"], "color": config["color"], "available": source is not None, "feature_count": count})

    for layer_id, config in RASTER_CONFIG.items():
        source = _local_file(config["path"])
        layer_meta.append({"id": layer_id, "label": config["label"], "group": config["group"], "color": config["color"], "available": source is not None, "feature_count": None, "kind": "raster"})

    flood_area_km2 = None
    flood_layer = next((item for item in layer_meta if item["id"] == "flood_extent"), None)
    try:
        frame = _read_vector("flood_extent", limit=5000)
        if frame is not None:
            flood_area_km2 = round(float(frame.to_crs("EPSG:6933").geometry.area.sum()) / 1_000_000, 2)
    except Exception:
        logger.exception("Unable to calculate mapped flood extent area")
    building_count = next((item["feature_count"] for item in layer_meta if item["id"] == "buildings"), None)
    spatial_dataset_count = sum(item["format"] != "PDF" for item in datasets)
    return {
        "district": "Mumbai Suburban",
        "as_of": None,
        "metrics": [
            {"label": "Mapped flood area", "value": flood_area_km2, "unit": "km²", "status": "observed"},
            {"label": "Building footprints", "value": building_count, "unit": "buildings", "status": "mapped"},
            {"label": "Spatial datasets", "value": spatial_dataset_count, "unit": "files", "status": "local catalog"},
            {"label": "Available map layers", "value": sum(bool(item["available"]) for item in layer_meta), "unit": "layers", "status": "ready"},
        ],
        "layers": layer_meta,
        "dataset_groups": [{"name": name, "files": sum(1 for item in datasets if item["category"] == folder)} for name, folder in RASTER_GROUPS.items()],
        "data_files": datasets,
        "data_root": str(DATA_ROOT),
    }


@app.get("/api/v1/rasters/{raster_id}")
def get_raster(raster_id: str) -> dict[str, Any]:
    config = RASTER_CONFIG.get(raster_id)
    if not config:
        raise HTTPException(status_code=404, detail="Unknown raster layer")
    path = _local_file(config["path"])
    if path is None:
        raise HTTPException(status_code=404, detail="Raster layer is not present in the configured data directory")
    try:
        import numpy as np
        import rasterio
        from PIL import Image
        from rasterio.enums import Resampling
        from rasterio.transform import Affine
        from rasterio.warp import calculate_default_transform, reproject

        with rasterio.open(path) as source:
            source_size = [source.width, source.height]
            crs = source.crs
            if crs is None:
                raise HTTPException(status_code=422, detail="Raster source has no CRS; assign its CRS before displaying it")
            bounds = source.bounds
            if crs.to_epsg() != 4326:
                base_transform, projected_width, projected_height = calculate_default_transform(
                    crs, "EPSG:4326", source.width, source.height, *source.bounds
                )
            else:
                base_transform, projected_width, projected_height = source.transform, source.width, source.height
            scale = min(1.0, 700 / projected_width, 700 / projected_height)
            width = max(1, round(projected_width * scale))
            height = max(1, round(projected_height * scale))
            display_transform = base_transform * Affine.scale(projected_width / width, projected_height / height)
            values = np.full((height, width), np.nan, dtype="float32")
            reproject(
                source=rasterio.band(source, 1), destination=values,
                src_transform=source.transform, src_crs=crs, src_nodata=source.nodata,
                dst_transform=display_transform, dst_crs="EPSG:4326", dst_nodata=np.nan,
                resampling=Resampling.nearest,
            )
            west = display_transform.c
            north = display_transform.f
            east = west + display_transform.a * width
            south = north + display_transform.e * height
            bounds = (west, south, east, north)
            nodata = source.nodata
        valid = np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        rgba = np.zeros((height, width, 4), dtype="uint8")
        palette = config["palette"]
        if palette == "flood":
            mask = valid & (values > 0)
            rgba[mask] = [242, 119, 93, 170]
        else:
            mask = valid & (values > 0 if palette == "water" else np.ones(values.shape, dtype=bool))
            selected = values[mask]
            if selected.size:
                low, high = np.percentile(selected, [3, 97])
                normalized = np.clip((selected - low) / max(float(high - low), 1e-6), 0, 1)
                if palette == "rain":
                    colors = np.stack([35 + 140 * normalized, 104 + 125 * normalized, 180 + 58 * normalized], axis=1)
                elif palette == "water":
                    colors = np.stack([30 + 48 * normalized, 104 + 108 * normalized, 160 + 86 * normalized], axis=1)
                else:
                    colors = np.stack([74 + 147 * normalized, 84 + 133 * normalized, 83 + 111 * normalized], axis=1)
                rgba[mask, :3] = colors.astype("uint8")
                rgba[mask, 3] = 160
        image = Image.fromarray(rgba, mode="RGBA")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        west, south, east, north = bounds
        return {"id": raster_id, "label": config["label"], "image": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii"),
                "bounds": [west, south, east, north], "source_crs": crs.to_string() if crs else None,
                "display_crs": "EPSG:4326", "source_size": source_size, "preview_size": [width, height], "path": config["path"]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to render raster %s", raster_id)
        raise HTTPException(status_code=503, detail="Could not render raster preview") from exc


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "disaster-risk-intelligence", "version": app.version}


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
