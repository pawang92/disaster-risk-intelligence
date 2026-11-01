import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  Activity, ArrowDownToLine, ArrowRight, Bot, Building2, Check, ChevronDown, ChevronRight,
  CircleHelp, Database, FileText, Layers3, Map as MapIcon, MapPin,
  MousePointer2, PanelLeftClose, RefreshCw, ShieldAlert, Sparkles,
  Waves, X,
} from 'lucide-react';
import { api, formatNumber, type AnalysisResult, type DatasetFile, type GuidanceResult, type Overview, type RasterPreview } from './api';
import type { DrawMode } from './components/MapCanvas';

const MapCanvas = lazy(() => import('./components/MapCanvas').then((module) => ({ default: module.MapCanvas })));

type AskMode = 'spatial' | 'guidance';
type QueryState = 'idle' | 'loading' | 'error' | 'complete';

const operations = [
  { label: 'Nearby search', prompt: 'Find hospitals within 2 km of my selected location', icon: MapPin },
  { label: 'Nearest features', prompt: 'Find the nearest emergency shelters to my location', icon: MousePointer2 },
  { label: 'Count in area', prompt: 'Count buildings inside the selected area', icon: Building2 },
  { label: 'Intersect layers', prompt: 'Show buildings intersecting the observed flood extent', icon: Layers3 },
  { label: 'Create buffer', prompt: 'Create a 500 meter buffer around the selected location', icon: Activity },
  { label: 'Generate report', prompt: 'Create a flood risk summary report for this area', icon: FileText },
];

const metricIcons = [ShieldAlert, Building2, Database, Layers3];

function prettyLayerName(name: string) {
  return name.replaceAll('_', ' ').replace(/^raster /, '').replace(/^gee /i, 'GEE ');
}

function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [vectors, setVectors] = useState<Record<string, GeoJSON.FeatureCollection>>({});
  const [rasters, setRasters] = useState<Record<string, RasterPreview>>({});
  const [visibility, setVisibility] = useState<Record<string, boolean>>({});
  const [askMode, setAskMode] = useState<AskMode>('spatial');
  const [drawMode, setDrawMode] = useState<DrawMode>('navigate');
  const [selection, setSelection] = useState<GeoJSON.Geometry | null>(null);
  const [query, setQuery] = useState('');
  const [queryState, setQueryState] = useState<QueryState>('idle');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [guidance, setGuidance] = useState<GuidanceResult | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [noticeVisible, setNoticeVisible] = useState(true);
  const [catalogExpanded, setCatalogExpanded] = useState(false);
  const [mapReady, setMapReady] = useState(false);

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const data = await api<Overview>('/overview');
      setOverview(data);
      setVisibility((previous) => {
        const next = { ...previous };
        data.layers.forEach((layer) => {
          if (next[layer.id] === undefined) next[layer.id] = layer.available && (layer.kind !== 'raster' || layer.id === 'raster_flood');
        });
        return next;
      });
      const available = data.layers.filter((layer) => layer.available);
      const results = await Promise.allSettled(available.map(async (layer) => {
        if (layer.kind === 'raster') {
          const raster = await api<RasterPreview>(`/rasters/${layer.id}`);
          return { id: layer.id, kind: 'raster' as const, value: raster };
        }
        const collection = await api<GeoJSON.FeatureCollection>(`/layers/${layer.id}?limit=5000`);
        return { id: layer.id, kind: 'vector' as const, value: collection };
      }));
      const nextVectors: Record<string, GeoJSON.FeatureCollection> = {};
      const nextRasters: Record<string, RasterPreview> = {};
      results.forEach((result) => {
        if (result.status !== 'fulfilled') return;
        if (result.value.kind === 'raster') nextRasters[result.value.id] = result.value.value;
        else nextVectors[result.value.id] = result.value.value;
      });
      setVectors(nextVectors);
      setRasters(nextRasters);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Could not load the local workspace.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadWorkspace(); }, [loadWorkspace]);

  const availableLayers = useMemo(() => overview?.layers.filter((layer) => layer.available) ?? [], [overview]);
  const featureCount = useMemo(() => Object.values(vectors).reduce((total, collection) => total + collection.features.length, 0) + (analysis?.feature_collection.features.length ?? 0), [analysis, vectors]);
  const files = overview?.data_files ?? [];
  const visibleFiles = catalogExpanded ? files : files.slice(0, 6);

  const changeMode = (mode: AskMode) => {
    setAskMode(mode);
    setAnalysis(null);
    setGuidance(null);
    setQueryState('idle');
    setErrorMessage('');
    if (mode === 'spatial') setQuery('');
  };

  const runQuery = async (event?: FormEvent) => {
    event?.preventDefault();
    const question = query.trim();
    if (question.length < 3 || queryState === 'loading') return;
    setQueryState('loading');
    setErrorMessage('');
    setAnalysis(null);
    setGuidance(null);
    try {
      if (askMode === 'spatial') {
        const result = await api<AnalysisResult>('/analyze', {
          method: 'POST',
          body: JSON.stringify({ query: question, geometry: selection, session_id: sessionId }),
        });
        if (result.provenance.session_id && typeof result.provenance.session_id === 'string') setSessionId(result.provenance.session_id);
        setAnalysis(result);
        if (result.provenance.success === false) {
          setErrorMessage(result.answer);
          setQueryState('error');
          return;
        }
      } else {
        const result = await api<GuidanceResult>('/guidance', {
          method: 'POST',
          body: JSON.stringify({ question, language: 'auto', district: 'mumbai', disaster_type: 'flood' }),
        });
        setGuidance(result);
      }
      setQueryState('complete');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'The request could not be completed.');
      setQueryState('error');
    }
  };

  const setLayerVisible = (id: string, checked: boolean) => setVisibility((current) => ({ ...current, [id]: checked }));

  const exportGeoJson = () => {
    const collection = analysis?.feature_collection ?? {
      type: 'FeatureCollection' as const,
      features: Object.values(vectors).flatMap((layer) => layer.features),
    };
    const blob = new Blob([JSON.stringify(collection, null, 2)], { type: 'application/geo+json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = analysis ? 'geoai-analysis.geojson' : 'disaster-risk-layers.geojson';
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const metrics = overview?.metrics ?? [];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-symbol"><Waves size={19} strokeWidth={2.2} /></div>
          <div className="brand-word">ATLAS<span> / RISK INTELLIGENCE</span></div>
          <button className="sidebar-close" aria-label="Collapse sidebar"><PanelLeftClose size={16} /></button>
        </div>
        <div className="sidebar-section-label">WORKSPACE</div>
        <button className="workspace-picker"><span className="workspace-avatar">M</span><span className="workspace-copy"><b>Mumbai Suburban</b><small>Flood resilience workspace</small></span><ChevronDown size={15} /></button>
        <div className="sidebar-section-label nav-label">PLATFORM</div>
        <nav className="nav-list">
          <a className="nav-item selected" href="#overview"><span className="nav-glyph"><Activity size={16} /></span><span>Risk overview</span></a>
          <a className="nav-item" href="#map"><span className="nav-glyph"><MapIcon size={16} /></span><span>Spatial workspace</span><span className="nav-count">{availableLayers.length}</span></a>
          <a className="nav-item" href="#operations"><span className="nav-glyph"><Sparkles size={16} /></span><span>GIS operations</span></a>
          <a className="nav-item" href="#catalog"><span className="nav-glyph"><Database size={16} /></span><span>Data catalog</span></a>
          <a className="nav-item" href="#agents"><span className="nav-glyph"><Bot size={16} /></span><span>Agent workflow</span></a>
        </nav>
        <div className="sidebar-bottom">
          <div className="service-health"><span className={`health-dot ${loading ? 'loading' : loadError ? 'offline' : ''}`} /><div><b>{loading ? 'Connecting to workspace' : loadError ? 'API unavailable' : 'Local stack connected'}</b><small>{loading ? 'Discovering local datasets' : loadError ? 'Start the FastAPI service' : `${availableLayers.filter((layer) => layer.kind !== 'raster' || rasters[layer.id]).length} map services ready`}</small></div></div>
          <div className="profile-row"><div className="profile-avatar">DR</div><div><b>Risk analyst</b><small>Local development</small></div><button className="more-button" aria-label="Account options">···</button></div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar"><div className="breadcrumb">Disaster Risk Intelligence <ChevronRight size={13} /><b>Workspace</b></div><div className="topbar-right"><span className="local-badge"><span className="live-dot" />LOCAL-FIRST</span><span className="date-stamp">FLOOD INTELLIGENCE · V1</span><button className="top-icon" onClick={() => void loadWorkspace()} aria-label="Refresh workspace"><RefreshCw size={16} /></button><div className="top-profile">DR</div></div></header>

        {loadError && <div className="page-error"><CircleHelp size={17} /><span><b>Could not load workspace data.</b> {loadError}</span><button onClick={() => void loadWorkspace()}>Retry</button></div>}

        <section className="page-intro" id="overview"><div><div className="eyebrow"><span /> GEOAI · FLOOD RISK INTELLIGENCE</div><h1>Risk overview<span>.</span></h1><p>One workspace for geospatial evidence, operational analysis, and decision support.</p></div><div className="intro-actions"><span className="district-tag"><MapPin size={14} />{overview?.district ?? 'Mumbai Suburban'}</span><button className="button-outline" onClick={() => void loadWorkspace()} disabled={loading}><RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh data</button><button className="button-strong" onClick={exportGeoJson}><ArrowDownToLine size={15} /> Export GeoJSON</button></div></section>

        {noticeVisible && <div className="data-notice"><div className="notice-icon">i</div><div><b>Evidence-first view</b><span>Dashboard indicators summarize observed datasets. A calibrated forecast score is shown only when a configured model returns one.</span></div><button onClick={() => setNoticeVisible(false)} aria-label="Dismiss notice"><X size={16} /></button></div>}

        <section className="metric-grid" aria-label="Workspace metrics">
          {metrics.map((metric, index) => {
            const Icon = metricIcons[index % metricIcons.length];
            return <article className={`metric-card metric-${index}`} key={metric.label}><div className="metric-head"><span>{metric.label.toUpperCase()}</span><div><Icon size={16} /></div></div><div className="metric-value">{metric.label === 'Mapped flood area' && metric.value != null ? Number(metric.value).toLocaleString('en-IN', { maximumFractionDigits: 2 }) : formatNumber(metric.value)}<small>{metric.unit}</small></div><div className="metric-foot"><span className="metric-dot" />{metric.status}</div></article>;
          })}
          {!metrics.length && Array.from({ length: 4 }, (_, index) => <article className="metric-card skeleton" key={index}><div /><div /><div /></article>)}
        </section>

        <section className="workspace-grid" id="map">
          <article className="panel map-panel">
            <div className="panel-heading map-heading"><div><div className="panel-overline">SPATIAL WORKSPACE</div><h2>Live hazard map</h2></div><div className="map-heading-actions"><span className={`map-status ${mapReady ? 'ready' : ''}`}><i />{mapReady ? 'MAP READY' : 'CONNECTING'}</span><button className="panel-icon" title="Refresh data" onClick={() => void loadWorkspace()}><RefreshCw size={15} /></button></div></div>
            <div className="map-toolbar"><div className="draw-tools"><button className={drawMode === 'navigate' ? 'tool-active' : ''} onClick={() => setDrawMode('navigate')} title="Pan and explore"><MousePointer2 size={15} />Explore</button><button className={drawMode === 'point' ? 'tool-active' : ''} onClick={() => setDrawMode('point')} title="Choose a location"><MapPin size={15} />Point</button><button className={drawMode === 'polygon' ? 'tool-active' : ''} onClick={() => setDrawMode('polygon')} title="Click points, double-click to finish"><Layers3 size={15} />Draw area</button>{selection && <button className="clear-selection" onClick={() => setSelection(null)}><X size={13} />Clear</button>}</div><div className="map-feature-count"><span className="metric-dot" />{formatNumber(featureCount)} features loaded</div></div>
            <div className="map-container"><Suspense fallback={<div className="map-loading">Starting MapLibre GL…</div>}><MapCanvas ready={mapReady} layers={availableLayers} vectors={vectors} rasters={rasters} visibility={visibility} result={analysis?.feature_collection} selection={selection} drawMode={drawMode} onPoint={(point) => { setSelection(point); setDrawMode('navigate'); }} onPolygon={(polygon) => { setSelection(polygon); setDrawMode('navigate'); }} onMapReady={setMapReady} /></Suspense></div>
            <div className="map-footer"><span><span className="map-footer-dot" />{selection?.type === 'Point' ? 'Point selected' : selection ? 'Polygon selected' : 'Select a point or draw a polygon to provide map context'}</span><span>EPSG:4326 <b>·</b> MapLibre GL</span></div>
            <div className="map-layer-control"><div className="layer-control-title"><span><Layers3 size={14} /> MAP LAYERS</span><span>{availableLayers.length}</span></div><div className="layer-control-list">{availableLayers.map((layer) => <label key={layer.id} className="layer-control-row"><input type="checkbox" checked={visibility[layer.id] ?? true} onChange={(event) => setLayerVisible(layer.id, event.target.checked)} /><i style={{ background: layer.color }} /><span>{layer.label}</span><small>{layer.feature_count == null ? 'RASTER' : formatNumber(layer.feature_count)}</small></label>)}</div></div>
          </article>

          <aside className="panel query-panel" id="operations">
            <div className="panel-heading query-heading"><div><div className="panel-overline">AGENTIC ANALYSIS</div><h2>Ask the workspace</h2></div><div className="assistant-icon"><Sparkles size={16} /></div></div>
            <div className="mode-switch"><button className={askMode === 'spatial' ? 'mode-selected' : ''} onClick={() => changeMode('spatial')}><MapIcon size={14} />Spatial operations</button><button className={askMode === 'guidance' ? 'mode-selected' : ''} onClick={() => changeMode('guidance')}><FileText size={14} />Guidance RAG</button></div>
            <p className="query-description">{askMode === 'spatial' ? 'Describe a GIS operation. Queries use the configured spatial provider; results show returned features, workflow steps, and limitations.' : 'Ask about preparedness and response. Answers are grounded in indexed disaster guidance documents.'}</p>
            <form className="query-form" onSubmit={runQuery}><textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder={askMode === 'spatial' ? 'Find the nearest shelters to my selected location…' : 'What should residents do before a flood?'} rows={4} /><div className="query-form-bottom"><span>{askMode === 'spatial' ? selection ? `Context: ${selection.type}` : 'Select a point or draw an area on the map' : 'Source citations are shown with the answer'}</span><button className="send-query" disabled={queryState === 'loading' || query.trim().length < 3} aria-label="Run query">{queryState === 'loading' ? <RefreshCw size={15} className="spin" /> : <ArrowRight size={16} />}</button></div></form>
            {askMode === 'spatial' && <><div className="quick-label">GIS OPERATION STARTERS</div><div className="operation-grid">{operations.map((operation) => { const Icon = operation.icon; return <button key={operation.label} className="operation-chip" onClick={() => { setQuery(operation.prompt); }}><Icon size={13} /><span>{operation.label}</span></button>; })}</div></>}
            {askMode === 'guidance' && <div className="quick-guidance"><button onClick={() => setQuery('Summarize the Mumbai Suburban district flood management plan')}>Summarize the district flood plan <ArrowRight size={13} /></button><button onClick={() => setQuery('What actions should residents take before a flood?')}>Resident preparedness actions <ArrowRight size={13} /></button></div>}
            <div className={`result-panel result-${queryState}`}>
              {queryState === 'idle' && <div className="empty-result"><span><Sparkles size={16} /></span><div><b>Your analysis will appear here</b><small>Results include the selected agent, returned features, and provenance.</small></div></div>}
              {queryState === 'loading' && <div className="empty-result"><span className="loading-spark"><RefreshCw size={16} /></span><div><b>{askMode === 'spatial' ? 'Running spatial workflow' : 'Retrieving guidance'}</b><small>Waiting for connected services…</small></div></div>}
              {queryState === 'error' && <div className="result-error"><b>Request could not complete</b><p>{errorMessage}</p></div>}
              {queryState === 'complete' && analysis && <div className="analysis-result"><div className="result-summary"><span className="result-success"><Check size={13} />WORKFLOW COMPLETE</span><span className="result-count">{formatNumber(analysis.counts[analysis.layers[0]] ?? analysis.feature_collection.features.length)} returned</span></div><p>{analysis.answer}</p><div className="agent-tags">{analysis.layers.map((layer) => <span key={layer}><Bot size={12} />{prettyLayerName(layer)}</span>)}</div>{Array.isArray(analysis.provenance.steps) && analysis.provenance.steps.length > 0 && <div className="workflow-steps" id="agents">{(analysis.provenance.steps as string[]).map((step, index) => <span key={`${step}-${index}`}><Check size={11} />{prettyLayerName(step)}</span>)}</div>}{analysis.limitations?.map((limitation) => <div className="result-limitation" key={limitation}><CircleHelp size={12} />{limitation}</div>)}</div>}
              {queryState === 'complete' && guidance && <div className="analysis-result"><div className="result-summary"><span className="result-success"><Check size={13} />GROUNDED RESPONSE</span><span className="service-tag">{guidance.service}</span></div><p>{guidance.answer}</p>{guidance.citations.length > 0 && <div className="citations"><div className="quick-label">SOURCES</div>{guidance.citations.map((citation, index) => <div className="citation" key={`${citation.source_key}-${index}`}><b>{citation.source_key}</b><span>{citation.page ? `Page ${citation.page}` : citation.location ?? ''}</span>{citation.excerpt && <p>{citation.excerpt}</p>}</div>)}</div>}</div>}
            </div>
          </aside>
        </section>

        <section className="lower-grid" id="catalog">
          <article className="panel catalog-panel"><div className="panel-heading"><div><div className="panel-overline">LOCAL DATA INVENTORY</div><h2>Data catalog <span className="heading-count">{formatNumber(files.length)} files</span></h2></div><button className="text-action" onClick={() => setCatalogExpanded((value) => !value)}>{catalogExpanded ? 'Show less' : 'View all'}<ArrowRight size={14} /></button></div><div className="catalog-table-wrap"><table className="catalog-table"><thead><tr><th>DATASET</th><th>FORMAT</th><th>COLLECTION</th><th>SIZE</th><th>STATUS</th></tr></thead><tbody>{visibleFiles.map((file: DatasetFile) => <tr key={file.path}><td><span className="file-icon"><FileText size={14} /></span><span className="filename" title={file.path}>{file.name}</span></td><td><span className="format-pill">{file.format}</span></td><td>{file.category.replaceAll('_', ' ')}</td><td>{file.size_bytes > 1048576 ? `${(file.size_bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size_bytes / 1024))} KB`}</td><td><span className="file-ready"><i />Available</span></td></tr>)}{!visibleFiles.length && <tr><td colSpan={5} className="empty-table">{loading ? 'Discovering local datasets…' : 'No supported files found.'}</td></tr>}</tbody></table></div></article>
          <article className="panel pipeline-panel"><div className="panel-heading"><div><div className="panel-overline">DATA PIPELINE</div><h2>Source readiness</h2></div><span className="pipeline-icon"><Activity size={17} /></span></div><div className="pipeline-total"><strong>{formatNumber(files.length)}</strong><div><b>files discovered</b><span>from the configured local data root</span></div></div><div className="pipeline-groups">{overview?.dataset_groups.filter((group) => group.files > 0).map((group) => <div className="pipeline-group" key={group.name}><span>{group.name}</span><b>{group.files}</b></div>)}</div><div className="pipeline-footer"><span><span className="metric-dot" />Catalog synchronized</span><span>Local storage</span></div></article>
        </section>
        <footer className="page-footer"><span>ATLAS <b>·</b> DISASTER RISK INTELLIGENCE</span><span>Local-first decision support · Mumbai Suburban</span><a href="/docs" target="_blank" rel="noreferrer">API REFERENCE <ArrowRight size={11} /></a></footer>
      </main>
    </div>
  );
}

export default App;
