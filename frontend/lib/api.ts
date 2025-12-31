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
  start_date?: string;
  end_date?: string;
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
