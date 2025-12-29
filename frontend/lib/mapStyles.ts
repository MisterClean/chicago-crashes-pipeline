// Chicago geographic constants
export const CHICAGO_CENTER = {
  longitude: -87.6298,
  latitude: 41.8781,
};

export const CHICAGO_BOUNDS: [[number, number], [number, number]] = [
  [-87.94, 41.64], // Southwest
  [-87.52, 42.02], // Northeast
];

// Default view state for the map
export const DEFAULT_VIEW_STATE = {
  ...CHICAGO_CENTER,
  zoom: 11,
  pitch: 0,
  bearing: 0,
};

// MapLibre style for PMTiles basemap served by Martin
export const BASEMAP_STYLE = "/tiles/basemap";

// Crash layer styling
export const crashCircleLayer = {
  id: "crashes-circle",
  type: "circle" as const,
  paint: {
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 2, 14, 6, 18, 12],
    "circle-color": [
      "case",
      [">", ["get", "injuries_fatal"], 0],
      "#dc2626", // Fatal - red
      [">", ["get", "injuries_incapacitating"], 0],
      "#ea580c", // Incapacitating - orange
      [">", ["get", "injuries_total"], 0],
      "#eab308", // Injury - yellow
      "#22c55e", // Property damage only - green
    ],
    "circle-opacity": 0.7,
    "circle-stroke-width": 1,
    "circle-stroke-color": "#ffffff",
    "circle-stroke-opacity": 0.5,
  },
};

// Heatmap layer for zoomed out view
export const crashHeatmapLayer = {
  id: "crashes-heatmap",
  type: "heatmap" as const,
  maxzoom: 12,
  paint: {
    "heatmap-weight": [
      "interpolate",
      ["linear"],
      ["get", "injuries_total"],
      0,
      0.1,
      1,
      0.5,
      5,
      1,
    ],
    "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 8, 0.5, 12, 1],
    "heatmap-color": [
      "interpolate",
      ["linear"],
      ["heatmap-density"],
      0,
      "rgba(0, 0, 255, 0)",
      0.2,
      "#22c55e",
      0.4,
      "#eab308",
      0.6,
      "#ea580c",
      1,
      "#dc2626",
    ],
    "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 8, 10, 12, 20],
    "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 11, 1, 12, 0],
  },
};

// Severity legend for UI
export const SEVERITY_LEGEND = [
  { label: "Fatal", color: "#dc2626" },
  { label: "Incapacitating Injury", color: "#ea580c" },
  { label: "Other Injury", color: "#eab308" },
  { label: "Property Damage Only", color: "#22c55e" },
];
