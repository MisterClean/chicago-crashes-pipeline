// Chicago geographic constants
export const CHICAGO_CENTER = {
  longitude: -87.6298,
  latitude: 41.8781,
};

// Expanded bounds to allow users to see surrounding context
export const CHICAGO_BOUNDS: [[number, number], [number, number]] = [
  [-88.1, 41.5], // Southwest - expanded
  [-87.3, 42.15], // Northeast - expanded
];

// Default view state for the map - zoomed out to show all of Chicago
export const DEFAULT_VIEW_STATE = {
  ...CHICAGO_CENTER,
  zoom: 9.5, // Zoomed out to show entire city
  pitch: 0,
  bearing: 0,
};

// Loop community area center coordinates
export const LOOP_CENTER = {
  longitude: -87.6298,
  latitude: 41.8823,
};

// Default view state for location report - focused on Loop
export const LOOP_VIEW_STATE = {
  ...LOOP_CENTER,
  zoom: 14, // Zoomed in to show Loop neighborhood
  pitch: 0,
  bearing: 0,
};

// Zoom constraints
export const MIN_ZOOM = 7; // Allow zooming out to see full Chicago metro area
export const MAX_ZOOM = 18;

// Severity legend for UI
export const SEVERITY_LEGEND = [
  { label: "Fatal", color: "#dc2626" },
  { label: "Incapacitating Injury", color: "#ea580c" },
  { label: "Other Injury", color: "#eab308" },
  { label: "Property Damage Only", color: "#22c55e" },
];

// Map metric options for user selection
export type MapMetric = "severity" | "hit_and_run" | "crash_type";

export interface MetricConfig {
  id: MapMetric;
  label: string;
  legend: { label: string; color: string }[];
  // MapLibre expression for circle-color
  colorExpression: unknown[];
  // Function to get filter expression for visible categories
  getFilterExpression: (visibleLabels: Set<string>) => unknown[];
}

export const MAP_METRICS: MetricConfig[] = [
  {
    id: "severity",
    label: "Severity",
    legend: SEVERITY_LEGEND,
    colorExpression: [
      "case",
      [">", ["get", "injuries_fatal"], 0],
      "#dc2626",
      [">", ["get", "injuries_incapacitating"], 0],
      "#ea580c",
      [">", ["get", "injuries_total"], 0],
      "#eab308",
      "#22c55e",
    ],
    getFilterExpression: (visible: Set<string>) => {
      const conditions: unknown[] = ["any"];
      if (visible.has("Fatal")) {
        conditions.push([">", ["get", "injuries_fatal"], 0]);
      }
      if (visible.has("Incapacitating Injury")) {
        conditions.push([
          "all",
          ["==", ["get", "injuries_fatal"], 0],
          [">", ["get", "injuries_incapacitating"], 0],
        ]);
      }
      if (visible.has("Other Injury")) {
        conditions.push([
          "all",
          ["==", ["get", "injuries_fatal"], 0],
          ["==", ["get", "injuries_incapacitating"], 0],
          [">", ["get", "injuries_total"], 0],
        ]);
      }
      if (visible.has("Property Damage Only")) {
        conditions.push([
          "all",
          ["==", ["get", "injuries_fatal"], 0],
          ["==", ["get", "injuries_incapacitating"], 0],
          ["==", ["get", "injuries_total"], 0],
        ]);
      }
      // Return false filter when nothing selected (no features will match)
      return conditions.length > 1 ? conditions : ["==", 1, 0];
    },
  },
  {
    id: "hit_and_run",
    label: "Hit and Run",
    legend: [
      { label: "Hit and Run", color: "#9333ea" },
      { label: "Not Hit and Run", color: "#6b7280" },
    ],
    colorExpression: [
      "case",
      ["==", ["get", "hit_and_run_i"], true],
      "#9333ea",
      "#6b7280",
    ],
    getFilterExpression: (visible: Set<string>) => {
      const conditions: unknown[] = ["any"];
      if (visible.has("Hit and Run")) {
        conditions.push(["==", ["get", "hit_and_run_i"], true]);
      }
      if (visible.has("Not Hit and Run")) {
        conditions.push(["!=", ["get", "hit_and_run_i"], true]);
      }
      return conditions.length > 1 ? conditions : ["==", 1, 0];
    },
  },
  {
    id: "crash_type",
    label: "Crash Type",
    legend: [
      { label: "Pedestrian", color: "#dc2626" },
      { label: "Pedalcyclist", color: "#ea580c" },
      { label: "Other", color: "#3b82f6" },
    ],
    colorExpression: [
      "case",
      ["==", ["get", "crash_type"], "PEDESTRIAN"],
      "#dc2626",
      ["==", ["get", "crash_type"], "PEDALCYCLIST"],
      "#ea580c",
      "#3b82f6",
    ],
    getFilterExpression: (visible: Set<string>) => {
      const conditions: unknown[] = ["any"];
      if (visible.has("Pedestrian")) {
        conditions.push(["==", ["get", "crash_type"], "PEDESTRIAN"]);
      }
      if (visible.has("Pedalcyclist")) {
        conditions.push(["==", ["get", "crash_type"], "PEDALCYCLIST"]);
      }
      if (visible.has("Other")) {
        conditions.push([
          "all",
          ["!=", ["get", "crash_type"], "PEDESTRIAN"],
          ["!=", ["get", "crash_type"], "PEDALCYCLIST"],
        ]);
      }
      return conditions.length > 1 ? conditions : ["==", 1, 0];
    },
  },
];
