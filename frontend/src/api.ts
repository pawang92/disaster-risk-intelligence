export const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export interface Metric {
  label: string;
  value: number | null;
  unit: string;
  status: string;
}

export interface LayerInfo {
  id: string;
  label: string;
  group: string;
  color: string;
  available: boolean;
  feature_count: number | null;
  kind?: 'raster';
}

export interface DatasetFile {
  name: string;
  path: string;
  format: string;
  size_bytes: number;
  category: string;
}

export interface Overview {
  district: string;
  metrics: Metric[];
  layers: LayerInfo[];
  dataset_groups: Array<{ name: string; files: number }>;
  data_files: DatasetFile[];
  data_root: string;
}

export interface RasterPreview {
  id: string;
  label: string;
  image: string;
  bounds: [number, number, number, number];
  source_crs: string | null;
  display_crs: string;
  preview_size: [number, number];
}

export interface AnalysisResult {
  query: string;
  answer: string;
  layers: string[];
  counts: Record<string, number>;
  feature_collection: GeoJSON.FeatureCollection;
  provenance: Record<string, unknown>;
  limitations: string[];
}

export interface GuidanceResult {
  answer: string;
  language: string;
  citations: Array<{
    source_key: string;
    page?: number;
    location?: string;
    excerpt?: string;
    score?: number;
  }>;
  service: string;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function formatNumber(value: number | null | undefined) {
  if (value == null) return '—';
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 }).format(value);
}

