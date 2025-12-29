"use client";

import { useState } from "react";
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

export default function LocationReportPage() {
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("radius");
  const [report, setReport] = useState<LocationReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Date filter state
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Selection state from map
  const [selectedCenter, setSelectedCenter] = useState<[number, number] | null>(null);
  const [selectedRadius, setSelectedRadius] = useState<number>(1320); // Default 1/4 mile in feet
  const [selectedPolygon, setSelectedPolygon] = useState<[number, number][] | null>(null);

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
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mb-8">
          <div className="flex flex-wrap items-center gap-6">
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
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
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
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                    selectionMode === "polygon"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  }`}
                >
                  Draw Polygon
                </button>
              </div>
            </div>

            {/* Radius Selector (only show in radius mode) */}
            {selectionMode === "radius" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Radius
                </label>
                <select
                  value={selectedRadius}
                  onChange={(e) => setSelectedRadius(Number(e.target.value))}
                  className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                >
                  <option value={660}>1/8 mile (660 ft)</option>
                  <option value={1320}>1/4 mile (1,320 ft)</option>
                  <option value={2640}>1/2 mile (2,640 ft)</option>
                  <option value={5280}>1 mile (5,280 ft)</option>
                  <option value={10560}>2 miles (10,560 ft)</option>
                </select>
              </div>
            )}

            {/* Date Filters */}
            <div className="flex items-center gap-2">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Start Date
                </label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  End Date
                </label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                />
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-2 ml-auto">
              {hasSelection && (
                <button
                  onClick={handleClearSelection}
                  className="px-4 py-2 bg-gray-200 dark:bg-gray-600 hover:bg-gray-300 dark:hover:bg-gray-500 text-gray-700 dark:text-gray-200 rounded-md text-sm font-medium"
                >
                  Clear
                </button>
              )}
              <button
                onClick={handleGenerateReport}
                disabled={!hasSelection || loading}
                className={`px-6 py-2 rounded-md text-sm font-medium transition-colors ${
                  hasSelection && !loading
                    ? "bg-blue-600 hover:bg-blue-700 text-white"
                    : "bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed"
                }`}
              >
                {loading ? "Generating..." : "Generate Report"}
              </button>
            </div>
          </div>

          {/* Instructions */}
          <div className="mt-4 text-sm text-gray-500 dark:text-gray-400">
            {selectionMode === "radius" ? (
              <p>Click on the map to place a center point. The circle shows the selected radius.</p>
            ) : (
              <p>Click on the map to draw polygon vertices. Double-click to finish the polygon.</p>
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

        {/* Data Source Info */}
        <div className="mt-8 text-center text-sm text-gray-500 dark:text-gray-400">
          <p>
            Data sourced from the{" "}
            <a
              href="https://data.cityofchicago.org/Transportation/Traffic-Crashes-Crashes/85ca-t3if"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-gray-700 dark:hover:text-gray-200"
            >
              Chicago Open Data Portal
            </a>
            . Updated daily.
          </p>
        </div>
      </div>
    </div>
  );
}
