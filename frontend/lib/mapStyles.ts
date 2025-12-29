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
  zoom: 10, // Reduced from 11 to show more of the city
  pitch: 0,
  bearing: 0,
};

// Zoom constraints
export const MIN_ZOOM = 9; // Allow zooming out to see greater Chicago area
export const MAX_ZOOM = 18;

// Severity legend for UI
export const SEVERITY_LEGEND = [
  { label: "Fatal", color: "#dc2626" },
  { label: "Incapacitating Injury", color: "#ea580c" },
  { label: "Other Injury", color: "#eab308" },
  { label: "Property Damage Only", color: "#22c55e" },
];
