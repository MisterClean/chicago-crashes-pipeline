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

// Severity legend for UI
export const SEVERITY_LEGEND = [
  { label: "Fatal", color: "#dc2626" },
  { label: "Incapacitating Injury", color: "#ea580c" },
  { label: "Other Injury", color: "#eab308" },
  { label: "Property Damage Only", color: "#22c55e" },
];
