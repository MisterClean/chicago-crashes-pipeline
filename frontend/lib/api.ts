// Use absolute URL for server-side rendering, relative for client-side
const API_BASE =
  typeof window === "undefined"
    ? process.env.BACKEND_URL || "http://localhost:8000"
    : process.env.NEXT_PUBLIC_API_URL || "/api";

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
    next: { revalidate: 60 }, // Cache for 1 minute
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch crashes GeoJSON: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const res = await fetch(`${API_BASE}/sync/status`, {
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
    headers: { "Content-Type": "application/json" },
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
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch place types: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchPlaceItems(placeType: string): Promise<PlaceItem[]> {
  const res = await fetch(`${API_BASE}/places/types/${encodeURIComponent(placeType)}/items`, {
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
      cache: "no-store",
    }
  );

  if (!res.ok) {
    throw new Error(`Failed to fetch place geometry: ${res.statusText}`);
  }

  return res.json();
}
