"use client";

import { useState, useCallback, useEffect } from "react";
import { LocationReportMap } from "./components/LocationReportMap";
import { ReportStats } from "./components/ReportStats";
import { CausesTable } from "./components/CausesTable";
import { TrendSparklines } from "./components/TrendSparklines";
import {
  fetchLocationReport,
  fetchPlaceTypes,
  fetchPlaceItems,
  fetchPlaceGeometry,
  type LocationReportResponse,
  type LocationReportRequest,
  type PlaceType,
  type PlaceItem,
} from "@/lib/api";

type SelectionMode = "radius" | "polygon" | "place";

// Preset radius options
const RADIUS_PRESETS = [
  { label: "50 ft", value: 50 },
  { label: "75 ft", value: 75 },
  { label: "100 ft", value: 100 },
  { label: "250 ft", value: 250 },
  { label: "1/8 mi", value: 660 },
  { label: "1/2 mi", value: 2640 },
  { label: "1 mi", value: 5280 },
  { label: "2 mi", value: 10560 },
];

// Calculate default dates (last 30 days)
function getDefaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  return {
    startDate: start.toISOString().split("T")[0],
    endDate: end.toISOString().split("T")[0],
  };
}

export default function LocationReportPage() {
  const defaultDates = getDefaultDates();
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("radius");
  const [report, setReport] = useState<LocationReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Date filter state - default to last 30 days
  const [startDate, setStartDate] = useState(defaultDates.startDate);
  const [endDate, setEndDate] = useState(defaultDates.endDate);

  // Selection state from map
  const [selectedCenter, setSelectedCenter] = useState<[number, number] | null>(null);
  const [selectedRadius, setSelectedRadius] = useState<number>(1320); // Default 1/4 mile in feet
  const [customRadiusInput, setCustomRadiusInput] = useState<string>(""); // For freeform input
  const [selectedPolygon, setSelectedPolygon] = useState<[number, number][] | null>(null);

  // Place selection state
  const [placeTypes, setPlaceTypes] = useState<PlaceType[]>([]);
  const [placeItems, setPlaceItems] = useState<PlaceItem[]>([]);
  const [selectedPlaceType, setSelectedPlaceType] = useState<string | null>(null);
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null);
  const [selectedPlaceGeometry, setSelectedPlaceGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [loadingPlaceTypes, setLoadingPlaceTypes] = useState(false);
  const [loadingPlaceItems, setLoadingPlaceItems] = useState(false);

  // Load place types on mount
  useEffect(() => {
    const loadPlaceTypes = async () => {
      setLoadingPlaceTypes(true);
      try {
        const types = await fetchPlaceTypes();
        setPlaceTypes(types);
      } catch (err) {
        console.error("Failed to load place types:", err);
      } finally {
        setLoadingPlaceTypes(false);
      }
    };
    loadPlaceTypes();
  }, []);

  // Load place items when place type changes
  useEffect(() => {
    if (!selectedPlaceType) {
      setPlaceItems([]);
      setSelectedPlaceId(null);
      setSelectedPlaceGeometry(null);
      return;
    }

    const loadPlaceItems = async () => {
      setLoadingPlaceItems(true);
      setPlaceItems([]);
      setSelectedPlaceId(null);
      setSelectedPlaceGeometry(null);
      try {
        const items = await fetchPlaceItems(selectedPlaceType);
        setPlaceItems(items);
      } catch (err) {
        console.error("Failed to load place items:", err);
      } finally {
        setLoadingPlaceItems(false);
      }
    };
    loadPlaceItems();
  }, [selectedPlaceType]);

  // Load place geometry when place is selected
  useEffect(() => {
    if (!selectedPlaceType || !selectedPlaceId) {
      setSelectedPlaceGeometry(null);
      return;
    }

    const loadPlaceGeometry = async () => {
      try {
        const result = await fetchPlaceGeometry(selectedPlaceType, selectedPlaceId);
        setSelectedPlaceGeometry(result.geometry);
        setReport(null); // Clear old report when new place selected
      } catch (err) {
        console.error("Failed to load place geometry:", err);
        setSelectedPlaceGeometry(null);
      }
    };
    loadPlaceGeometry();
  }, [selectedPlaceType, selectedPlaceId]);

  // Date preset handler
  const setDatePreset = useCallback((days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    setStartDate(start.toISOString().split("T")[0]);
    setEndDate(end.toISOString().split("T")[0]);
  }, []);

  // Handle center selection - clear report when user clicks new location
  const handleCenterSelect = useCallback((center: [number, number]) => {
    setSelectedCenter(center);
    setReport(null);  // Clear old report so new circle renders
    setError(null);
  }, []);

  // Handle custom radius input
  const handleCustomRadiusChange = (value: string) => {
    setCustomRadiusInput(value);
    const numValue = parseInt(value, 10);
    if (!isNaN(numValue) && numValue > 0 && numValue <= 26400) {
      setSelectedRadius(numValue);
    }
  };

  // Handle preset radius selection
  const handleRadiusPresetChange = (value: number) => {
    setSelectedRadius(value);
    setCustomRadiusInput(""); // Clear custom input when preset is selected
  };

  const handleGenerateReport = async () => {
    setLoading(true);
    setError(null);

    try {
      const request: LocationReportRequest = {};

      if (selectionMode === "radius" && selectedCenter) {
        request.latitude = selectedCenter[1];
        request.longitude = selectedCenter[0];
        request.radius_feet = selectedRadius;
      } else if (selectionMode === "polygon" && selectedPolygon) {
        request.polygon = selectedPolygon;
      } else if (selectionMode === "place" && selectedPlaceType && selectedPlaceId) {
        request.place_type = selectedPlaceType;
        request.place_id = selectedPlaceId;
      } else {
        setError("Please select an area on the map first");
        setLoading(false);
        return;
      }

      if (startDate) request.start_date = startDate;
      if (endDate) request.end_date = endDate;

      const result = await fetchLocationReport(request);
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate report");
    } finally {
      setLoading(false);
    }
  };

  const handleClearSelection = () => {
    setSelectedCenter(null);
    setSelectedPolygon(null);
    setSelectedPlaceType(null);
    setSelectedPlaceId(null);
    setSelectedPlaceGeometry(null);
    setReport(null);
    setError(null);
  };

  const hasSelection =
    (selectionMode === "radius" && selectedCenter !== null) ||
    (selectionMode === "polygon" && selectedPolygon !== null) ||
    (selectionMode === "place" && selectedPlaceType !== null && selectedPlaceId !== null);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            Location Crash Report
          </h1>
          <p className="mt-1 text-gray-600 dark:text-gray-400">
            Select an area on the map to generate a detailed crash analysis report
          </p>
        </div>

        {/* Controls Panel */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4 sm:p-6 mb-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Selection Mode */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Selection Mode
              </label>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setSelectionMode("radius");
                    setSelectedPolygon(null);
                    setSelectedPlaceType(null);
                    setSelectedPlaceId(null);
                    setSelectedPlaceGeometry(null);
                  }}
                  className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    selectionMode === "radius"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  }`}
                >
                  Radius
                </button>
                <button
                  onClick={() => {
                    setSelectionMode("polygon");
                    setSelectedCenter(null);
                    setSelectedPlaceType(null);
                    setSelectedPlaceId(null);
                    setSelectedPlaceGeometry(null);
                  }}
                  className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    selectionMode === "polygon"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  }`}
                >
                  Polygon
                </button>
                <button
                  onClick={() => {
                    setSelectionMode("place");
                    setSelectedCenter(null);
                    setSelectedPolygon(null);
                  }}
                  className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    selectionMode === "place"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  }`}
                >
                  Place
                </button>
              </div>
            </div>

            {/* Radius Selector (only show in radius mode) */}
            {selectionMode === "radius" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Radius
                </label>
                <div className="flex items-center gap-2">
                  <select
                    value={customRadiusInput ? "custom" : selectedRadius}
                    onChange={(e) => {
                      if (e.target.value !== "custom") {
                        handleRadiusPresetChange(Number(e.target.value));
                      }
                    }}
                    className="flex-1 min-w-0 px-2 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm"
                  >
                    {customRadiusInput && (
                      <option value="custom">Custom</option>
                    )}
                    {RADIUS_PRESETS.map((preset) => (
                      <option key={preset.value} value={preset.value}>
                        {preset.label}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min="1"
                    max="26400"
                    placeholder="Custom"
                    value={customRadiusInput}
                    onChange={(e) => handleCustomRadiusChange(e.target.value)}
                    className="w-20 px-2 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm"
                  />
                </div>
                {customRadiusInput && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    {selectedRadius.toLocaleString()} ft
                  </p>
                )}
              </div>
            )}

            {/* Place Selector (only show in place mode) */}
            {selectionMode === "place" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Place
                </label>
                <div className="space-y-2">
                  <select
                    value={selectedPlaceType || ""}
                    onChange={(e) => setSelectedPlaceType(e.target.value || null)}
                    disabled={loadingPlaceTypes}
                    className="w-full px-2 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm"
                  >
                    <option value="">
                      {loadingPlaceTypes ? "Loading..." : "Select type..."}
                    </option>
                    {placeTypes.map((type) => (
                      <option key={type.id} value={type.id}>
                        {type.name} ({type.feature_count})
                      </option>
                    ))}
                  </select>
                  <select
                    value={selectedPlaceId || ""}
                    onChange={(e) => setSelectedPlaceId(e.target.value || null)}
                    disabled={!selectedPlaceType || loadingPlaceItems}
                    className="w-full px-2 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm disabled:opacity-50"
                  >
                    <option value="">
                      {loadingPlaceItems
                        ? "Loading..."
                        : selectedPlaceType
                        ? "Select place..."
                        : "Select type first"}
                    </option>
                    {placeItems.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.display_name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {/* Date Range - spans 2 columns on larger screens when radius/place is hidden */}
            <div className={selectionMode === "polygon" ? "sm:col-span-2" : ""}>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Date Range
              </label>
              {/* Quick presets */}
              <div className="flex gap-1 flex-wrap mb-2">
                {[
                  { label: "7d", days: 7 },
                  { label: "30d", days: 30 },
                  { label: "90d", days: 90 },
                  { label: "1yr", days: 365 },
                  { label: "All", days: 0 },
                ].map((preset) => (
                  <button
                    key={preset.label}
                    onClick={() => preset.days > 0 ? setDatePreset(preset.days) : (setStartDate(""), setEndDate(""))}
                    className="px-2 py-1 text-xs bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded text-gray-700 dark:text-gray-300"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
              {/* Date inputs */}
              <div className="flex items-center gap-1">
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="flex-1 min-w-0 px-2 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs"
                />
                <span className="text-gray-400 text-xs">–</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="flex-1 min-w-0 px-2 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs"
                />
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex flex-col justify-end gap-2">
              <div className="flex gap-2">
                {hasSelection && (
                  <button
                    onClick={handleClearSelection}
                    className="flex-1 px-3 py-2 bg-gray-200 dark:bg-gray-600 hover:bg-gray-300 dark:hover:bg-gray-500 text-gray-700 dark:text-gray-200 rounded-md text-sm font-medium"
                  >
                    Clear
                  </button>
                )}
                <button
                  onClick={handleGenerateReport}
                  disabled={!hasSelection || loading}
                  className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    hasSelection && !loading
                      ? "bg-blue-600 hover:bg-blue-700 text-white"
                      : "bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed"
                  }`}
                >
                  {loading ? "..." : "Generate"}
                </button>
              </div>
            </div>
          </div>

          {/* Instructions */}
          <div className="mt-3 text-xs text-gray-500 dark:text-gray-400">
            {selectionMode === "radius" ? (
              <p>Click on the map to place a center point.</p>
            ) : selectionMode === "polygon" ? (
              <p>Click to draw vertices. Double-click to finish.</p>
            ) : (
              <p>Select a place type and place from the dropdowns above.</p>
            )}
          </div>
        </div>

        {/* Error Message */}
        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-8">
            <p className="text-red-800 dark:text-red-200">{error}</p>
          </div>
        )}

        {/* Map */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mb-8">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
            Select Area
          </h2>
          <LocationReportMap
            mode={selectionMode}
            selectedCenter={selectedCenter}
            selectedRadius={selectedRadius}
            selectedPolygon={selectedPolygon}
            selectedPlaceGeometry={selectedPlaceGeometry}
            onCenterSelect={handleCenterSelect}
            onPolygonComplete={setSelectedPolygon}
            reportData={report}
            startDate={startDate}
            endDate={endDate}
          />
        </div>

        {/* Report Results */}
        {report && (
          <>
            {/* Stats Cards */}
            <ReportStats stats={report.stats} />

            {/* Two-column layout for trends and causes */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-8">
              {/* Trend Sparklines */}
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                  Monthly Trends (Last 12 Months)
                </h2>
                <TrendSparklines data={report.monthly_trends} />
              </div>

              {/* Causes Table */}
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                  Primary Crash Causes
                </h2>
                <CausesTable causes={report.causes} />
              </div>
            </div>

            {/* Cost Methodology Footnote */}
            <div className="mt-8 p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
              <div className="flex items-start gap-3">
                <span className="inline-flex items-center justify-center w-5 h-5 text-xs font-bold bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded-full flex-shrink-0 mt-0.5">i</span>
                <div className="text-xs text-gray-600 dark:text-gray-400 space-y-2">
                  <p className="font-medium text-gray-700 dark:text-gray-300">Cost Estimation Methodology</p>
                  <p>
                    Cost estimates are calculated using the Federal Highway Administration (FHWA) KABCO injury-based
                    methodology. <strong>Economic costs</strong> include medical expenses, lost productivity, legal costs,
                    and property damage. <strong>Societal costs</strong> add the value of lost quality of life (QALY -
                    Quality-Adjusted Life Years) to capture the full impact on individuals and communities.
                  </p>
                  <p>
                    Costs are calculated per-person based on injury severity classification (K=Fatal, A=Incapacitating,
                    B=Non-incapacitating, C=Possible injury, O=No injury), plus per-vehicle costs. Values are in 2024 dollars.
                  </p>
                  <p>
                    <a
                      href="https://highways.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
                    >
                      View FHWA Crash Cost Fact Sheet (PDF)
                    </a>
                  </p>
                </div>
              </div>
            </div>
          </>
        )}

      </div>
    </div>
  );
}
