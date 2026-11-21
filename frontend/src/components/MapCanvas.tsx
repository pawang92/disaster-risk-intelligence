import { useEffect, useRef } from 'react';
import { Map as MapLibreMapConstructor, NavigationControl, ScaleControl, type GeoJSONSource, type ImageSource, type Map as MapLibreMap } from 'maplibre-gl';
import type { LayerInfo, RasterPreview } from '../api';

export type DrawMode = 'navigate' | 'point' | 'polygon';
export type Basemap = 'satellite' | 'terrain';

interface Props {
  ready: boolean;
  basemap: Basemap;
  onBasemapChange: (basemap: Basemap) => void;
  layers: LayerInfo[];
  vectors: Record<string, GeoJSON.FeatureCollection>;
  rasters: Record<string, RasterPreview>;
  visibility: Record<string, boolean>;
  result?: GeoJSON.FeatureCollection;
  selection: GeoJSON.Geometry | null;
  drawMode: DrawMode;
  onPoint: (point: GeoJSON.Point) => void;
  onPolygon: (polygon: GeoJSON.Polygon) => void;
  onMapReady?: (ready: boolean) => void;
}

const COLORS: Record<string, string> = {
  flood_extent: '#ef715d', buildings: '#f5b952', rivers: '#46b8dc', analysis: '#b593ff',
};

function selectionCollection(geometry: GeoJSON.Geometry | null): GeoJSON.FeatureCollection {
  return { type: 'FeatureCollection', features: geometry ? [{ type: 'Feature', properties: {}, geometry }] : [] };
}

function basemapStyle(kind: Basemap) {
  const configuredTiles = kind === 'satellite'
    ? import.meta.env.VITE_SATELLITE_TILE_URL
    : import.meta.env.VITE_TERRAIN_TILE_URL;
  const tiles = configuredTiles || (kind === 'satellite'
    ? 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
    : 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}');
  const attribution = kind === 'satellite'
    ? 'Tiles © Esri, Maxar, Earthstar Geographics, and the GIS User Community'
    : 'Tiles © Esri, HERE, Garmin, FAO, NOAA, USGS, OpenStreetMap contributors, and the GIS User Community';
  return { version: 8 as const, sources: { basemap: { type: 'raster' as const, tiles: [tiles], tileSize: 256, attribution } }, layers: [{ id: 'basemap', type: 'raster' as const, source: 'basemap' }] };
}

export function MapCanvas({ ready, basemap, onBasemapChange, layers, vectors, rasters, visibility, result, selection, drawMode, onPoint, onPolygon, onMapReady }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const handlers = useRef({ onPoint, onPolygon, onMapReady, drawMode });
  const vertices = useRef<Array<[number, number]>>([]);
  const initialBasemap = useRef(basemap);

  useEffect(() => { handlers.current = { onPoint, onPolygon, onMapReady, drawMode }; }, [onPoint, onPolygon, onMapReady, drawMode]);

  useEffect(() => {
    if (!host.current || mapRef.current) return;
    const map = new MapLibreMapConstructor({
      container: host.current,
      style: basemapStyle(basemap),
      center: [72.88, 19.12],
      zoom: 10.3,
      minZoom: 4,
      maxZoom: 19,
      attributionControl: {},
      cooperativeGestures: true,
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right');
    map.addControl(new ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left');

    const ensureSelection = () => {
      if (!map.getSource('map-selection')) {
        map.addSource('map-selection', { type: 'geojson', data: selectionCollection(null) });
        map.addLayer({ id: 'selection-fill', type: 'fill', source: 'map-selection', filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': '#4ed3b2', 'fill-opacity': 0.17 } });
        map.addLayer({ id: 'selection-line', type: 'line', source: 'map-selection', paint: { 'line-color': '#4ed3b2', 'line-width': 2, 'line-dasharray': [2, 1.5] } });
        map.addLayer({ id: 'selection-point', type: 'circle', source: 'map-selection', filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 7, 'circle-color': '#4ed3b2', 'circle-stroke-color': '#eafff9', 'circle-stroke-width': 2 } });
      }
      handlers.current.onMapReady?.(true);
    };
    map.on('style.load', ensureSelection);
    map.on('error', (event) => { if (event.error) console.warn('MapLibre style/tile message:', event.error.message); });
    map.on('click', (event) => {
      if (handlers.current.drawMode === 'point') {
        handlers.current.onPoint({ type: 'Point', coordinates: [event.lngLat.lng, event.lngLat.lat] });
      } else if (handlers.current.drawMode === 'polygon') {
        vertices.current.push([event.lngLat.lng, event.lngLat.lat]);
        const source = map.getSource('map-selection') as GeoJSONSource | undefined;
        if (source && vertices.current.length >= 3) {
          const ring = [...vertices.current, vertices.current[0]];
          source.setData(selectionCollection({ type: 'Polygon', coordinates: [ring] }));
        }
      }
    });
    map.on('dblclick', (event) => {
      if (handlers.current.drawMode !== 'polygon' || vertices.current.length < 3) return;
      event.preventDefault();
      const ring = [...vertices.current, vertices.current[0]];
      handlers.current.onPolygon({ type: 'Polygon', coordinates: [ring] });
      vertices.current = [];
    });
    return () => {
      map.remove();
      mapRef.current = null;
      handlers.current.onMapReady?.(false);
    };
    // Map construction is intentionally one-shot; event handlers read current callbacks from a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (initialBasemap.current === basemap) return;
    initialBasemap.current = basemap;
    const map = mapRef.current;
    if (!map) return;
    handlers.current.onMapReady?.(false);
    vertices.current = [];
    map.setStyle(basemapStyle(basemap));
  }, [basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (drawMode === 'polygon') map.doubleClickZoom.disable();
    else { map.doubleClickZoom.enable(); vertices.current = []; }
    map.getCanvas().style.cursor = drawMode === 'navigate' ? '' : drawMode === 'point' ? 'crosshair' : 'cell';
  }, [drawMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.isStyleLoaded()) return;
    const addVector = (id: string, data: GeoJSON.FeatureCollection, color: string) => {
      const sourceId = `source-${id}`;
      const source = map.getSource(sourceId) as GeoJSONSource | undefined;
      if (source) source.setData(data);
      else {
        map.addSource(sourceId, { type: 'geojson', data, promoteId: 'id' });
        map.addLayer({ id: `${id}-fill`, type: 'fill', source: sourceId, filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': color, 'fill-opacity': id === 'buildings' ? 0.36 : 0.3 } });
        map.addLayer({ id: `${id}-line`, type: 'line', source: sourceId, filter: ['in', '$type', 'LineString', 'Polygon'], paint: { 'line-color': color, 'line-width': id === 'rivers' ? 1.5 : 1, 'line-opacity': 0.88 } });
        map.addLayer({ id: `${id}-point`, type: 'circle', source: sourceId, filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 3.5, 'circle-color': color, 'circle-stroke-color': '#f5f6f5', 'circle-stroke-width': 0.8 } });
      }
    };
    Object.entries(vectors).forEach(([id, data]) => addVector(id, data, COLORS[id] || '#a899d6'));
    if (result) addVector('analysis', result, COLORS.analysis);
    if (selection && map.getSource('map-selection')) (map.getSource('map-selection') as GeoJSONSource).setData(selectionCollection(selection));

    Object.entries(rasters).forEach(([id, raster]) => {
      const sourceId = `source-${id}`;
      const source = map.getSource(sourceId) as ImageSource | undefined;
      const [west, south, east, north] = raster.bounds;
      const coordinates: [[number, number], [number, number], [number, number], [number, number]] = [[west, north], [east, north], [east, south], [west, south]];
      if (source) source.updateImage({ url: raster.image, coordinates });
      else {
        map.addSource(sourceId, { type: 'image', url: raster.image, coordinates });
        map.addLayer({ id: id, type: 'raster', source: sourceId, paint: { 'raster-opacity': 0.72, 'raster-fade-duration': 0 } });
      }
      if (map.getLayer('selection-fill')) map.moveLayer(id, 'selection-fill');
    });

    layers.forEach((layer) => {
      const ids = layer.kind === 'raster' ? [layer.id] : [`${layer.id}-fill`, `${layer.id}-line`, `${layer.id}-point`];
      ids.forEach((id) => {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visibility[layer.id] ? 'visible' : 'none');
      });
    });
    if (map.getLayer('analysis-fill')) ['analysis-fill', 'analysis-line', 'analysis-point'].forEach((id) => map.setLayoutProperty(id, 'visibility', 'visible'));
  }, [ready, vectors, rasters, layers, visibility, result, selection]);

  return <div className="map-canvas-shell"><div className="map-canvas" ref={host} aria-label="Interactive MapLibre map" /><div className="basemap-switch" role="group" aria-label="Choose basemap"><button className={basemap === 'satellite' ? 'active' : ''} onClick={() => onBasemapChange('satellite')}>Satellite</button><button className={basemap === 'terrain' ? 'active' : ''} onClick={() => onBasemapChange('terrain')}>Terrain</button></div></div>;
}
