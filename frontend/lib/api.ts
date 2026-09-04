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
  partial: boolean;
  crashes: number;
  injuries: number;
  fatalities: number;
}

export interface HourDayCount { day: number; hour: number; crashes: number; injury_crashes: number; severe_crashes: number; }
export interface RoadUserSeverity { road_user: string; people: number; fatal: number; incapacitating: number; other_injury: number; no_injury: number; unknown: number; }

export interface LocationReportResponse {
  hour_day_counts: HourDayCount[];
  road_user_severity: RoadUserSeverity[];
  map_limit: number;
  map_truncated: boolean;
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

export async function exportLocationReport(
  request: LocationReportExportRequest,
  apiKey = ""
): Promise<string> {
  const headers: HeadersInit = apiKey ? { [API_KEY_HEADER]: apiKey } : getAuthHeaders();
  const create = await fetch(`${API_BASE}/exports`, {
    method: "POST", headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(request),
  });
  if (create.status === 401 || create.status === 403) throw new Error("This server requires a valid API key for exports.");
  if (!create.ok) throw new Error(`Unable to queue export (${create.status}).`);
  let job = await create.json();
  const deadline = Date.now() + 30 * 60 * 1000;
  while (job.status === "queued" || job.status === "running") {
    if (Date.now() > deadline) throw new Error(`Export ${job.id} is still processing. Please check again later.`);
    await new Promise((resolve) => setTimeout(resolve, 3000));
    const status = await fetch(`${API_BASE}/exports/${job.id}`, { headers, cache: "no-store" });
    if (!status.ok) throw new Error(`Unable to check export ${job.id}.`);
    job = await status.json();
  }
  if (job.status !== "completed") throw new Error(job.error || `Export ${job.status}. Please try again.`);
  const download = await fetch(`${API_BASE}/exports/${job.id}/download`, { headers, cache: "no-store" });
  if (!download.ok) throw new Error("Unable to retrieve the export download link.");
  const { url } = await download.json();
  return url;
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
