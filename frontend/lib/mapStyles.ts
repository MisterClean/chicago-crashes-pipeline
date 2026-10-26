// NEXT_PUBLIC_* values are embedded at build time. The Protomaps token is a
// browser-visible map credential, never a server API key.
const PROTOMAPS_KEY = process.env.NEXT_PUBLIC_PROTOMAPS_KEY;
export const BASEMAP_STYLE_URL =
  process.env.NEXT_PUBLIC_BASEMAP_URL ||
  (PROTOMAPS_KEY
    ? `https://api.protomaps.com/styles/v4/light/en.json?key=${PROTOMAPS_KEY}`
    : "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json");

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
