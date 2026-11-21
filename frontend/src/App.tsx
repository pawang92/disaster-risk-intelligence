import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  Activity, ArrowDownToLine, ArrowRight, Bot, Building2, Check, ChevronDown, ChevronRight,
  CircleHelp, Database, FileText, Layers3, Map as MapIcon, MapPin,
  MousePointer2, PanelLeftClose, RefreshCw, ShieldAlert, Sparkles,
  Waves, X,
} from 'lucide-react';
import { api, formatNumber, type AnalysisResult, type DatasetFile, type GuidanceResult, type Overview, type RasterPreview, type RiskAssessmentResponse, type SystemStatus } from './api';
import type { Basemap, DrawMode } from './components/MapCanvas';

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
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [vectors, setVectors] = useState<Record<string, GeoJSON.FeatureCollection>>({});
  const [rasters, setRasters] = useState<Record<string, RasterPreview>>({});
  const [visibility, setVisibility] = useState<Record<string, boolean>>({});
  const [askMode, setAskMode] = useState<AskMode>('spatial');
  const [drawMode, setDrawMode] = useState<DrawMode>('navigate');
  const [basemap, setBasemap] = useState<Basemap>('satellite');
  const [selection, setSelection] = useState<GeoJSON.Geometry | null>(null);
  const [query, setQuery] = useState('');
  const [queryState, setQueryState] = useState<QueryState>('idle');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [assessment, setAssessment] = useState<RiskAssessmentResponse | null>(null);
  const [assessmentLoading, setAssessmentLoading] = useState(false);
  const [assessmentError, setAssessmentError] = useState('');
  const [latitude, setLatitude] = useState('19.0760');
  const [longitude, setLongitude] = useState('72.8777');
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
      const serviceStatus = await api<SystemStatus>('/system/status').catch(() => null);
      setSystemStatus(serviceStatus);
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
  const dependencyDegraded = Boolean(systemStatus && (
    systemStatus.guidance.status !== 'healthy' || systemStatus.postgis.status === 'unavailable'
  ));
  const featureCount = useMemo(() => Object.values(vectors).reduce((total, collection) => total + collection.features.length, 0) + (analysis?.feature_collection.features.length ?? 0), [analysis, vectors]);
  const files = overview?.data_files ?? [];
  const visibleFiles = catalogExpanded ? files : files.slice(0, 6);
  const exposureBreakdown = assessment?.exposure ? [
    { label: 'Population', value: assessment.exposure.affected_population_percentage },
    { label: 'Buildings', value: typeof assessment.exposure.details.affected_building_percentage === 'number' ? assessment.exposure.details.affected_building_percentage : null },
    { label: 'Roads', value: typeof assessment.exposure.details.affected_road_percentage === 'number' ? assessment.exposure.details.affected_road_percentage : null },
    { label: 'Critical assets', value: typeof assessment.exposure.details.affected_critical_asset_percentage === 'number' ? assessment.exposure.details.affected_critical_asset_percentage : null },
  ] : [];

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

  const runRiskAssessment = async (event: FormEvent) => {
    event.preventDefault();
    setAssessmentLoading(true);
    setAssessmentError('');
    try {
      const result = await api<RiskAssessmentResponse>('/risk/assess', {
        method: 'POST',
        body: JSON.stringify({
          location: { district: 'Mumbai Suburban', state: 'Maharashtra', latitude: Number(latitude), longitude: Number(longitude) },
          hazard: 'flood',
          question: 'Assess flood risk and summarize the observed evidence and exposure at this location.',
          include_exposure: true,
          include_evidence: true,
          include_recommendations: true,
        }),
      });
      setAssessment(result);
    } catch (error) {
      setAssessmentError(error instanceof Error ? error.message : 'Assessment could not be completed.');
    } finally {
      setAssessmentLoading(false);
    }
  };

  const exportGeoJson = () => {
    const collection = assessment?.map_data ?? analysis?.feature_collection ?? {
      type: 'FeatureCollection' as const,
      features: Object.values(vectors).flatMap((layer) => layer.features),
    };
    const blob = new Blob([JSON.stringify(collection, null, 2)], { type: 'application/geo+json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = assessment ? 'flood-risk-assessment.geojson' : analysis ? 'geoai-analysis.geojson' : 'disaster-risk-layers.geojson';
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const exportAssessment = () => {
    if (!assessment) return;
    const blob = new Blob([JSON.stringify(assessment, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `flood-assessment-${assessment.request_id}.json`;
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
          <a className="nav-item selected" href="#overview"><span className="nav-glyph"><Activity size={16} /></span><span>Overview</span></a>
          <a className="nav-item" href="#risk-assessment"><span className="nav-glyph"><ShieldAlert size={16} /></span><span>Risk assessment</span></a>
          <a className="nav-item" href="#map"><span className="nav-glyph"><MapIcon size={16} /></span><span>Live risk map</span><span className="nav-count">{availableLayers.length}</span></a>
          <a className="nav-item" href="#exposure"><span className="nav-glyph"><Building2 size={16} /></span><span>Exposure analysis</span></a>
          <a className="nav-item" href="#history"><span className="nav-glyph"><Activity size={16} /></span><span>Historical analysis</span></a>
          <a className="nav-item" href="#operations"><span className="nav-glyph"><Sparkles size={16} /></span><span>AI disaster copilot</span></a>
          <a className="nav-item" href="#reports"><span className="nav-glyph"><FileText size={16} /></span><span>Reports</span></a>
          <a className="nav-item" href="#catalog"><span className="nav-glyph"><Database size={16} /></span><span>Data management</span></a>
          <a className="nav-item" href="#system"><span className="nav-glyph"><Bot size={16} /></span><span>System monitoring</span></a>
        </nav>
        <div className="sidebar-bottom">
          <div className="service-health"><span className={`health-dot ${loading ? 'loading' : loadError || dependencyDegraded ? 'offline' : ''}`} /><div><b>{loading ? 'Connecting to workspace' : loadError ? 'Risk API unavailable' : dependencyDegraded ? 'A dependency is unavailable' : 'Risk API connected'}</b><small>{loading ? 'Discovering local datasets' : loadError ? 'Start the FastAPI service on port 8000' : `RAG ${systemStatus?.guidance.status ?? 'unknown'} · ${availableLayers.filter((layer) => layer.kind !== 'raster' || rasters[layer.id]).length} map services`}</small></div></div>
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

        <section className="assessment-grid" id="risk-assessment">
          <article className="panel assessment-form-panel">
            <div className="panel-heading"><div><div className="panel-overline">RISK ASSESSMENT</div><h2>Run a flood assessment</h2></div><span className="risk-pill"><i />FLOOD ENGINE</span></div>
            <p className="assessment-copy">Run the backend risk engine against the configured rainfall, elevation, flood extent, history, and exposure sources.</p>
            <form className="assessment-form" onSubmit={runRiskAssessment}>
              <label>District<input value="Mumbai Suburban" readOnly /></label>
              <label>Hazard<select value="flood" disabled><option value="flood">Flood</option></select></label>
              <label>Latitude<input type="number" step="any" min="-90" max="90" value={latitude} onChange={(event) => setLatitude(event.target.value)} required /></label>
              <label>Longitude<input type="number" step="any" min="-180" max="180" value={longitude} onChange={(event) => setLongitude(event.target.value)} required /></label>
              <div className="assessment-form-actions"><span>{selection?.type === 'Point' ? 'Coordinates taken from the selected map point.' : 'Default coordinates are central Mumbai Suburban; select a map point to change them.'}</span><button className="button-strong" disabled={assessmentLoading}>{assessmentLoading ? <RefreshCw size={14} className="spin" /> : <ShieldAlert size={14} />}{assessmentLoading ? 'Assessing…' : 'Run assessment'}</button></div>
            </form>
            {assessmentError && <div className="assessment-error" role="alert">{assessmentError}</div>}
          </article>
          <article className={`panel assessment-result-panel ${assessment ? `risk-${assessment.risk_assessment.risk_level}` : ''}`}>
            <div className="panel-heading"><div><div className="panel-overline">LATEST RESULT</div><h2>{assessment ? 'Flood risk summary' : 'Assessment output'}</h2></div>{assessment && <span className="method-version">{assessment.risk_assessment.methodology_version ?? 'UNVERSIONED'}</span>}</div>
            {assessment ? <div className="assessment-result-content">
              <div className="risk-score-row"><div className="risk-score"><strong>{assessment.risk_assessment.risk_score == null ? '—' : `${Math.round(assessment.risk_assessment.risk_score * 100)}`}</strong><span>{assessment.risk_assessment.risk_score == null ? 'NO SCORE' : 'RISK SCORE / 100'}</span></div><div className="risk-classification"><span className="risk-level-label">CLASSIFICATION</span><b>{assessment.risk_assessment.risk_level.replaceAll('_', ' ').toUpperCase()}</b><small>{assessment.risk_assessment.affected_area_sq_km == null ? 'Affected area unavailable' : `${formatNumber(assessment.risk_assessment.affected_area_sq_km)} km² mapped`}</small></div></div>
              <div className="factor-list"><div className="quick-label">CONTRIBUTING FACTORS</div>{assessment.risk_assessment.contributing_factors.length ? assessment.risk_assessment.contributing_factors.map((factor) => <span key={factor}><i />{prettyLayerName(factor)}</span>) : <small>No contributing factors were returned.</small>}</div>
              {assessment.recommendations.length > 0 && <div className="recommendation-list"><div className="quick-label">RECOMMENDED ACTIONS</div>{assessment.recommendations.map((recommendation, index) => <div key={`${recommendation.action}-${index}`}><b>{recommendation.priority.toUpperCase()}</b><span>{recommendation.action}</span></div>)}</div>}
              <div className="assessment-explanation">{assessment.explanation}</div>
            </div> : <div className="assessment-empty"><span><ShieldAlert size={17} /></span><div><b>No assessment has been run</b><small>Risk scores and exposure values will appear here from the backend response.</small></div></div>}
          </article>
        </section>

        <section className="workspace-grid" id="map">
          <article className="panel map-panel">
            <div className="panel-heading map-heading"><div><div className="panel-overline">SPATIAL WORKSPACE</div><h2>Live hazard map</h2></div><div className="map-heading-actions"><span className={`map-status ${mapReady ? 'ready' : ''}`}><i />{mapReady ? 'MAP READY' : 'CONNECTING'}</span><button className="panel-icon" title="Refresh data" onClick={() => void loadWorkspace()}><RefreshCw size={15} /></button></div></div>
            <div className="map-toolbar"><div className="draw-tools"><button className={drawMode === 'navigate' ? 'tool-active' : ''} onClick={() => setDrawMode('navigate')} title="Pan and explore"><MousePointer2 size={15} />Explore</button><button className={drawMode === 'point' ? 'tool-active' : ''} onClick={() => setDrawMode('point')} title="Choose a location"><MapPin size={15} />Point</button><button className={drawMode === 'polygon' ? 'tool-active' : ''} onClick={() => setDrawMode('polygon')} title="Click points, double-click to finish"><Layers3 size={15} />Draw area</button>{selection && <button className="clear-selection" onClick={() => setSelection(null)}><X size={13} />Clear</button>}</div><div className="map-feature-count"><span className="metric-dot" />{formatNumber(featureCount)} features loaded</div></div>
            <div className="map-container"><Suspense fallback={<div className="map-loading">Starting MapLibre GL…</div>}><MapCanvas ready={mapReady} basemap={basemap} onBasemapChange={setBasemap} layers={availableLayers} vectors={vectors} rasters={rasters} visibility={visibility} result={assessment?.map_data ?? analysis?.feature_collection} selection={selection} drawMode={drawMode} onPoint={(point) => { setSelection(point); setLatitude(point.coordinates[1].toFixed(6)); setLongitude(point.coordinates[0].toFixed(6)); setDrawMode('navigate'); }} onPolygon={(polygon) => { setSelection(polygon); setDrawMode('navigate'); }} onMapReady={setMapReady} /></Suspense></div>
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

        <section className="lower-grid intelligence-grid" id="exposure">
          <article className="panel exposure-panel">
            <div className="panel-heading"><div><div className="panel-overline">EXPOSURE ANALYSIS</div><h2>People and assets in mapped flood extent</h2></div><span className="heading-count">{assessment ? 'ASSESSMENT DATA' : 'RUN AN ASSESSMENT'}</span></div>
            {assessment?.exposure ? <>
              <div className="exposure-metrics">
                <div className="exposure-metric"><small>POPULATION AT RISK</small><b>{formatNumber(assessment.exposure.population_at_risk)}</b><span>{assessment.exposure.affected_population_percentage == null ? 'Share unavailable' : `${formatNumber(assessment.exposure.affected_population_percentage)}% of analysis area`}</span></div>
                <div className="exposure-metric"><small>BUILDINGS AT RISK</small><b>{formatNumber(assessment.exposure.properties_at_risk)}</b><span>Mapped building footprints</span></div>
                <div className="exposure-metric"><small>ROADS AT RISK</small><b>{formatNumber(assessment.exposure.roads_at_risk)}</b><span>Road features intersected</span></div>
                <div className="exposure-metric"><small>CRITICAL ASSETS</small><b>{formatNumber(assessment.exposure.critical_assets_at_risk)}</b><span>Configured infrastructure POIs</span></div>
              </div>
              <div className="exposure-breakdown"><div className="quick-label">AFFECTED SHARE BY ASSET TYPE</div>{exposureBreakdown.map((item) => <div className="exposure-bar-row" key={item.label}><span>{item.label}</span><div><i className={item.value == null ? 'bar-unknown' : ''} style={{ width: `${item.value == null ? 0 : Math.max(0, Math.min(100, item.value))}%` }} /></div><b>{item.value == null ? '—' : `${formatNumber(item.value)}%`}</b></div>)}</div>
              <p className="exposure-footnote">Values and denominators come from the assessment response. A dash means that source is not configured or did not return a value.</p>
            </> : <div className="assessment-empty"><span><Building2 size={17} /></span><div><b>Exposure metrics are not loaded</b><small>Run an assessment to show estimated people, buildings, roads, and critical assets in the mapped flood extent.</small></div></div>}
          </article>
          <article className="panel history-panel" id="history">
            <div className="panel-heading"><div><div className="panel-overline">HISTORICAL ANALYSIS</div><h2>Historical source data</h2></div><span className="heading-count">{files.filter((file) => /historical|water/i.test(file.category + file.name)).length} FILES</span></div>
            <div className="history-list">{files.filter((file) => /historical|water/i.test(file.category + file.name)).slice(0, 5).map((file) => <div className="history-row" key={file.path}><span className="history-dot" /><span><b>{file.name}</b><small>{file.category.replaceAll('_', ' ')} · {file.format}</small></span><small>{file.size_bytes > 1048576 ? `${(file.size_bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size_bytes / 1024))} KB`}</small></div>)}{!files.some((file) => /historical|water/i.test(file.category + file.name)) && <div className="history-empty">No historical flood layers were discovered in the configured data folder.</div>}</div>
            <p className="exposure-footnote">Historical observations provide context; they are not a forecast.</p>
          </article>
        </section>

        <section className="lower-grid intelligence-grid" id="reports">
          <article className="panel report-panel"><div className="panel-heading"><div><div className="panel-overline">REPORTS</div><h2>Export assessment evidence</h2></div><FileText size={18} className="pipeline-icon" /></div><p className="assessment-copy">Download the exact API response, including methodology version, exposure details, recommendations, and mapped GeoJSON.</p><div className="report-actions"><button className="button-outline" onClick={exportGeoJson}><Layers3 size={14} />Export map GeoJSON</button><button className="button-strong" onClick={exportAssessment} disabled={!assessment}><ArrowDownToLine size={14} />Download assessment JSON</button></div><small className="report-note">PDF report generation is not implemented by the backend yet.</small></article>
          <article className="panel system-panel" id="system"><div className="panel-heading"><div><div className="panel-overline">SYSTEM MONITORING</div><h2>Service health</h2></div><RefreshCw size={16} className={loading ? 'spin' : 'pipeline-icon'} /></div><div className="service-status-list"><div><span className={`status-led ${loadError ? 'status-bad' : loading ? 'status-wait' : ''}`} /><b>Risk API</b><small>{loading ? 'checking' : loadError ? 'unavailable' : 'healthy'}</small></div><div><span className={`status-led ${systemStatus?.guidance.status === 'healthy' ? '' : 'status-bad'}`} /><b>Guidance RAG</b><small>{systemStatus?.guidance.status ?? 'unknown'}</small></div><div><span className={`status-led ${systemStatus?.postgis.status === 'healthy' ? '' : systemStatus?.postgis.status === 'not_checked' ? 'status-wait' : 'status-bad'}`} /><b>PostGIS</b><small>{systemStatus?.postgis.status ?? 'unknown'}</small></div></div><div className="system-meta">Spatial provider: <b>{systemStatus?.spatial_provider ?? 'unknown'}</b>{systemStatus?.guidance.details && <span> · {systemStatus.guidance.details.embedding_provider} embeddings / {systemStatus.guidance.details.answer_provider} answers</span>}</div></article>
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
