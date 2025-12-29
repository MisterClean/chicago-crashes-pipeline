"use client";

import { useState, useCallback } from "react";
import { LocationReportMap } from "./components/LocationReportMap";
import { ReportStats } from "./components/ReportStats";
import { CausesTable } from "./components/CausesTable";
import { TrendSparklines } from "./components/TrendSparklines";
import {
  fetchLocationReport,
  type LocationReportResponse,
  type LocationReportRequest,
} from "@/lib/api";

type SelectionMode = "radius" | "polygon";

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

  // Date preset handler
  const setDatePreset = useCallback((days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    setStartDate(start.toISOString().split("T")[0]);
    setEndDate(end.toISOString().split("T")[0]);
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
    setReport(null);
    setError(null);
  };

  const hasSelection =
    (selectionMode === "radius" && selectedCenter !== null) ||
    (selectionMode === "polygon" && selectedPolygon !== null);

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
                  }}
                  className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    selectionMode === "polygon"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  }`}
                >
                  Polygon
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
                    value={customRadiusInput ? "" : selectedRadius}
                    onChange={(e) => handleRadiusPresetChange(Number(e.target.value))}
                    className="flex-1 min-w-0 px-2 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm"
                  >
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

            {/* Date Range - spans 2 columns on larger screens when radius is hidden */}
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
            ) : (
              <p>Click to draw vertices. Double-click to finish.</p>
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
            onCenterSelect={setSelectedCenter}
            onPolygonComplete={setSelectedPolygon}
            reportData={report}
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
          </>
        )}

      </div>
    </div>
  );
}
