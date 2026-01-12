// Use absolute URL for server-side rendering, relative for client-side
const API_BASE =
  typeof window === "undefined"
    ? process.env.BACKEND_URL || "http://localhost:8000"
    : process.env.NEXT_PUBLIC_API_URL || "/api";

// API Key for server-side requests (set in Railway environment)
const API_KEY = process.env.API_KEY || "";

// Header name for API key authentication
const API_KEY_HEADER = "X-API-Key";

// Helper to get auth headers for server-side requests
function getAuthHeaders(): HeadersInit {
  // Only include API key on server-side where it's available from env
  if (typeof window === "undefined" && API_KEY) {
    return { [API_KEY_HEADER]: API_KEY };
  }
  return {};
}

export interface DashboardStats {
  total_crashes: number;
  total_injuries: number;
  total_fatalities: number;
  pedestrians_involved: number;
  cyclists_involved: number;
  hit_and_run_count: number;
}

export interface WeeklyTrend {
  week: string;
  crashes: number;
  injuries: number;
  fatalities: number;
}

export interface CrashFeature {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number];
  };
  properties: {
    crash_record_id: string;
    crash_date: string;
    injuries_total: number;
    injuries_fatal: number;
    injuries_incapacitating: number;
    hit_and_run_i: boolean;
    crash_type: string;
    street_name?: string;
    primary_contributory_cause?: string;
  };
}

export interface CrashGeoJSON {
  type: "FeatureCollection";
  features: CrashFeature[];
}

export interface SyncStatus {
  last_sync: string | null;
  is_syncing: boolean;
  crashes_count: number;
  people_count: number;
  vehicles_count: number;
}

export async function fetchDashboardStats(params?: {
  start_date?: string;
  end_date?: string;
  community_area?: string;
}): Promise<DashboardStats> {
  const searchParams = new URLSearchParams();
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);
  if (params?.community_area)
    searchParams.set("community_area", params.community_area);

  const res = await fetch(`${API_BASE}/dashboard/stats?${searchParams}`, {
    headers: getAuthHeaders(),
    next: { revalidate: 300 }, // Cache for 5 minutes
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch dashboard stats: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchWeeklyTrends(params?: {
  weeks?: number;
  start_date?: string;
  end_date?: string;
}): Promise<WeeklyTrend[]> {
  const searchParams = new URLSearchParams();
  if (params?.weeks) searchParams.set("weeks", params.weeks.toString());
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);

  const res = await fetch(`${API_BASE}/dashboard/trends/weekly?${searchParams}`, {
    headers: getAuthHeaders(),
    next: { revalidate: 300 },
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch weekly trends: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchCrashesGeoJSON(params?: {
  start_date?: string;
  end_date?: string;
  limit?: number;
}): Promise<CrashGeoJSON> {
  const searchParams = new URLSearchParams();
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);
  if (params?.limit) searchParams.set("limit", params.limit.toString());

  const res = await fetch(`${API_BASE}/dashboard/crashes/geojson?${searchParams}`, {
    headers: getAuthHeaders(),
    next: { revalidate: 60 }, // Cache for 1 minute
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch crashes GeoJSON: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const res = await fetch(`${API_BASE}/sync/status`, {
    headers: getAuthHeaders(),
    cache: "no-store", // Always fresh
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch sync status: ${res.statusText}`);
  }

  return res.json();
}

// Location Report Types
// Cost Breakdown Types
export interface InjuryClassificationCost {
  classification: string;
  classification_label: string;
  count: number;
  unit_economic_cost: number;
  unit_qaly_cost: number;
  subtotal_economic: number;
  subtotal_societal: number;
}

export interface VehicleCostBreakdown {
  count: number;
  unit_economic_cost: number;
  unit_qaly_cost: number;
  subtotal_economic: number;
  subtotal_societal: number;
}

export interface CostBreakdown {
  injury_costs: InjuryClassificationCost[];
  vehicle_costs: VehicleCostBreakdown;
  total_economic: number;
  total_societal: number;
}

export interface LocationReportStats {
  total_crashes: number;
  total_injuries: number;
  total_fatalities: number;
  pedestrians_involved: number;
  cyclists_involved: number;
  hit_and_run_count: number;
  incapacitating_injuries: number;
  children_injured: number;
  crashes_with_injuries: number;
  crashes_with_fatalities: number;
  // Cost estimates (2024$) - FHWA methodology
  estimated_economic_damages: number;
  estimated_societal_costs: number;
  total_vehicles: number;
  unknown_injury_count: number;
  // Detailed cost breakdown
  cost_breakdown?: CostBreakdown;
}

export interface CrashCauseSummary {
  cause: string;
  crashes: number;
  injuries: number;
  fatalities: number;
  percentage: number;
}

export interface MonthlyTrendPoint {
  month: string;
  crashes: number;
  injuries: number;
  fatalities: number;
}

export interface LocationReportResponse {
  stats: LocationReportStats;
  causes: CrashCauseSummary[];
  monthly_trends: MonthlyTrendPoint[];
  crashes_geojson: CrashGeoJSON;
  query_area_geojson: {
    type: "Feature";
    geometry: {
      type: "Polygon";
      coordinates: number[][][];
    };
    properties: Record<string, unknown>;
  };
}

export interface LocationReportRequest {
  latitude?: number;
  longitude?: number;
  radius_feet?: number;
  polygon?: [number, number][];
  place_type?: string;
  place_id?: string;
  start_date?: string;
  end_date?: string;
}

export type LocationReportDataset =
  | "crashes"
  | "people"
  | "vehicles"
  | "vision_zero";

export interface LocationReportExportRequest extends LocationReportRequest {
  datasets: LocationReportDataset[];
}

function parseFilenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = disposition.match(/filename="?([^"]+)"?/i);
  return match ? match[1] : null;
}

export async function exportLocationReport(
  request: LocationReportExportRequest
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${API_BASE}/dashboard/location-report/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    throw new Error(`Failed to export location report: ${res.statusText}`);
  }

  const blob = await res.blob();
  const filename =
    parseFilenameFromDisposition(res.headers.get("Content-Disposition")) ||
    (request.datasets.length > 1
      ? "location-report-export.zip"
      : `location-report-${request.datasets[0]}.csv`);

  return { blob, filename };
}

// Places API Types
export interface PlaceType {
  id: string;
  name: string;
  source: "native" | "uploaded";
  feature_count: number;
}

export interface PlaceItem {
  id: string;
  name: string;
  display_name: string;
}

export interface PlaceGeometry {
  place_type: string;
  place_id: string;
  name: string;
  geometry: GeoJSON.Geometry;
}

export async function fetchLocationReport(
  request: LocationReportRequest
): Promise<LocationReportResponse> {
  const res = await fetch(`${API_BASE}/dashboard/location-report`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
    body: JSON.stringify(request),
    cache: "no-store",
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to fetch location report: ${errorText}`);
  }

  return res.json();
}

// Places API Functions
export async function fetchPlaceTypes(): Promise<PlaceType[]> {
  const res = await fetch(`${API_BASE}/places/types`, {
    headers: getAuthHeaders(),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch place types: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchPlaceItems(placeType: string): Promise<PlaceItem[]> {
  const res = await fetch(`${API_BASE}/places/types/${encodeURIComponent(placeType)}/items`, {
    headers: getAuthHeaders(),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch place items: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchPlaceGeometry(
  placeType: string,
  placeId: string
): Promise<PlaceGeometry> {
  const res = await fetch(
    `${API_BASE}/places/types/${encodeURIComponent(placeType)}/items/${encodeURIComponent(placeId)}/geometry`,
    {
      headers: getAuthHeaders(),
      cache: "no-store",
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch place geometry: ${res.statusText}`);
  }

  return res.json();
}

// Ward Scorecard Types
export interface WardStats {
  total_crashes: number;
  fatalities: number;
  serious_injuries: number;
  ksi: number;
  vru_injuries: number;
  children_injured: number;
  hit_and_run: number;
  economic_cost: number;
  societal_cost: number;
}

export interface WardRanking {
  ward: number;
  ward_name: string;
  alderman: string | null;
  total_crashes: number;
  fatalities: number;
  serious_injuries: number;
  ksi: number;
  vru_injuries: number;
  children_injured: number;
  economic_cost: number;
  societal_cost: number;
}

export interface WardScorecardCitywideResponse {
  year: number;
  citywide_stats: WardStats;
  ward_rankings: WardRanking[];
  wards_geojson: GeoJSON.FeatureCollection;
}

export interface WardTrendData {
  ksi: number[];
  fatalities: number[];
  serious_injuries: number[];
}

export interface WardTrendResponse {
  years: number[];
  citywide: WardTrendData;
  ward: {
    ward: number;
    ksi: number[];
    fatalities: number[];
    serious_injuries: number[];
  } | null;
}

export interface MonthlySeasonalityData {
  months: string[];
  selected_year: { year: number; ksi: number[] };
  five_year_avg: { ksi: number[] };
}

export interface WardDetailTrendResponse {
  ward: number;
  yearly_trends: {
    years: number[];
    ksi: number[];
    fatalities: number[];
    serious_injuries: number[];
    total_crashes: number[];
  };
  monthly_seasonality: MonthlySeasonalityData;
}

export interface WardDetailResponse {
  year: number;
  ward: number;
  ward_name: string;
  alderman: string | null;
  stats: WardStats;
  citywide_comparison: WardStats;
  cost_breakdown: CostBreakdown;
  crashes_geojson: CrashGeoJSON;
  ward_boundary_geojson: GeoJSON.Feature;
}

// Ward Scorecard API Functions
export async function fetchWardScorecardCitywide(
  year: number
): Promise<WardScorecardCitywideResponse> {
  const res = await fetch(
    `${API_BASE}/dashboard/ward-scorecard/citywide?year=${year}`,
    {
      headers: getAuthHeaders(),
      next: { revalidate: 300 },
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch ward scorecard citywide: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchWardScorecardCitywidetrends(
  ward?: number
): Promise<WardTrendResponse> {
  const params = new URLSearchParams();
  if (ward) params.set("ward", ward.toString());

  const res = await fetch(
    `${API_BASE}/dashboard/ward-scorecard/citywide/trends?${params}`,
    {
      headers: getAuthHeaders(),
      next: { revalidate: 300 },
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch ward scorecard trends: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchWardDetail(
  ward: number,
  year: number
): Promise<WardDetailResponse> {
  const res = await fetch(
    `${API_BASE}/dashboard/ward-scorecard/ward/${ward}?year=${year}`,
    {
      headers: getAuthHeaders(),
      next: { revalidate: 300 },
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch ward detail: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchWardDetailTrends(
  ward: number,
  year: number
): Promise<WardDetailTrendResponse> {
  const res = await fetch(
    `${API_BASE}/dashboard/ward-scorecard/ward/${ward}/trends?year=${year}`,
    {
      headers: getAuthHeaders(),
      next: { revalidate: 300 },
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch ward detail trends: ${res.statusText}`);
  }

  return res.json();
}

export function getWardExportUrl(
  year: number,
  format: "csv" | "json" = "csv",
  ward?: number
): string {
  const baseUrl =
    typeof window === "undefined"
      ? process.env.BACKEND_URL || "http://localhost:8000"
      : "";
  const params = new URLSearchParams({
    year: year.toString(),
    format,
  });
  if (ward) {
    params.set("ward", ward.toString());
  }
  return `${baseUrl}/dashboard/ward-scorecard/export?${params}`;
}
