"use client";

import { useState, useEffect, useCallback } from "react";
import {
  fetchWardScorecardCitywide,
  fetchWardScorecardCitywidetrends,
  fetchWardDetail,
  fetchWardDetailTrends,
  type WardScorecardCitywideResponse,
  type WardTrendResponse,
  type WardDetailResponse,
  type WardDetailTrendResponse,
} from "@/lib/api";
import { WardChoroplethMap } from "./components/WardChoroplethMap";
import { WardRankingTable } from "./components/WardRankingTable";
import { CitywideTrendChart } from "./components/CitywideTrendChart";
import { WardBANCards } from "./components/WardBANCards";
import { WardDetailMap } from "./components/WardDetailMap";
import { SeasonalityChart } from "./components/SeasonalityChart";
import { ShareExportButtons } from "./components/ShareExportButtons";
import { CostBreakdownTable } from "../location-report/components/CostBreakdownTable";

type TabType = "citywide" | "ward";

const AVAILABLE_YEARS = [2024, 2023, 2022, 2021, 2020, 2019, 2018];

export default function WardScorecardPage() {
  const [activeTab, setActiveTab] = useState<TabType>("citywide");
  const [selectedYear, setSelectedYear] = useState(2024);
  const [selectedWard, setSelectedWard] = useState<number | null>(null);

  // Citywide data
  const [citywideData, setCitywideData] = useState<WardScorecardCitywideResponse | null>(null);
  const [citywidetrends, setCitywideTrends] = useState<WardTrendResponse | null>(null);
  const [citywideLoading, setCitywideLoading] = useState(false);
  const [citywideError, setCitywideError] = useState<string | null>(null);

  // Ward detail data
  const [wardData, setWardData] = useState<WardDetailResponse | null>(null);
  const [wardTrends, setWardTrends] = useState<WardDetailTrendResponse | null>(null);
  const [wardLoading, setWardLoading] = useState(false);
  const [wardError, setWardError] = useState<string | null>(null);

  // Load citywide data
  const loadCitywideData = useCallback(async () => {
    setCitywideLoading(true);
    setCitywideError(null);
    try {
      const [data, trends] = await Promise.all([
        fetchWardScorecardCitywide(selectedYear),
        fetchWardScorecardCitywidetrends(),
      ]);
      setCitywideData(data);
      setCitywideTrends(trends);
    } catch (err) {
      setCitywideError(err instanceof Error ? err.message : "Failed to load citywide data");
    } finally {
      setCitywideLoading(false);
    }
  }, [selectedYear]);

  // Load ward detail data
  const loadWardData = useCallback(async () => {
    if (!selectedWard) return;
    setWardLoading(true);
    setWardError(null);
    try {
      const [data, trends] = await Promise.all([
        fetchWardDetail(selectedWard, selectedYear),
        fetchWardDetailTrends(selectedWard, selectedYear),
      ]);
      setWardData(data);
      setWardTrends(trends);
    } catch (err) {
      setWardError(err instanceof Error ? err.message : "Failed to load ward data");
    } finally {
      setWardLoading(false);
    }
  }, [selectedWard, selectedYear]);

  // Load data on mount and when year changes
  useEffect(() => {
    loadCitywideData();
  }, [loadCitywideData]);

  // Load ward data when ward is selected
  useEffect(() => {
    if (selectedWard && activeTab === "ward") {
      loadWardData();
    }
  }, [selectedWard, activeTab, loadWardData]);

  // Handle ward selection from map or table
  const handleWardSelect = (ward: number) => {
    setSelectedWard(ward);
    setActiveTab("ward");
  };

  // Format currency
  const formatCurrency = (value: number): string => {
    if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
    return `$${value.toFixed(0)}`;
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            Ward Safety Scorecard
          </h1>
          <p className="mt-1 text-gray-600 dark:text-gray-400">
            Compare traffic safety metrics across Chicago&apos;s 50 wards
          </p>
        </div>

        {/* Controls */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4 mb-6">
          <div className="flex flex-wrap items-center gap-4">
            {/* Year Selector */}
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Year:
              </label>
              <select
                value={selectedYear}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm"
              >
                {AVAILABLE_YEARS.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            </div>

            {/* Share/Export Buttons */}
            <ShareExportButtons
              year={selectedYear}
              ward={activeTab === "ward" ? selectedWard ?? undefined : undefined}
            />

            {/* Tab Navigation */}
            <div className="flex gap-2 ml-auto">
              <button
                onClick={() => setActiveTab("citywide")}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  activeTab === "citywide"
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                }`}
              >
                Citywide Overview
              </button>
              <button
                onClick={() => setActiveTab("ward")}
                disabled={!selectedWard}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  activeTab === "ward"
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                } ${!selectedWard ? "opacity-50 cursor-not-allowed" : ""}`}
              >
                {selectedWard ? `Ward ${selectedWard} Detail` : "Select a Ward"}
              </button>
            </div>
          </div>
        </div>

        {/* Error Display */}
        {(citywideError || wardError) && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
            <p className="text-red-800 dark:text-red-200">
              {citywideError || wardError}
            </p>
          </div>
        )}

        {/* Loading State */}
        {(citywideLoading || wardLoading) && (
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
            <div className="flex items-center gap-3">
              <svg
                className="animate-spin h-5 w-5 text-blue-600 dark:text-blue-400"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              <p className="text-blue-800 dark:text-blue-200 font-medium">
                Loading data...
              </p>
            </div>
          </div>
        )}

        {/* Citywide Tab */}
        {activeTab === "citywide" && citywideData && (
          <>
            {/* Citywide BAN Cards */}
            <WardBANCards stats={citywideData.citywide_stats} formatCurrency={formatCurrency} />

            {/* Map and Table Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
              {/* Choropleth Map */}
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                  KSI by Ward
                </h2>
                <WardChoroplethMap
                  geojson={citywideData.wards_geojson}
                  onWardClick={handleWardSelect}
                  selectedWard={selectedWard}
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                  Click on a ward to see detailed statistics
                </p>
              </div>

              {/* Ranking Table */}
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                  Ward Rankings
                </h2>
                <WardRankingTable
                  rankings={citywideData.ward_rankings}
                  onWardClick={handleWardSelect}
                  selectedWard={selectedWard}
                  formatCurrency={formatCurrency}
                />
              </div>
            </div>

            {/* Citywide Trend Chart */}
            {citywidetrends && (
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mt-6">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                  Citywide KSI Trend (2018-Present)
                </h2>
                <CitywideTrendChart data={citywidetrends} />
              </div>
            )}
          </>
        )}

        {/* Ward Detail Tab */}
        {activeTab === "ward" && selectedWard && wardData && (
          <>
            {/* Ward Header */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mb-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                    Ward {wardData.ward}
                  </h2>
                  {wardData.alderman && (
                    <p className="text-gray-600 dark:text-gray-400">
                      Alderman: {wardData.alderman}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => setActiveTab("citywide")}
                  className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
                >
                  Back to Citywide
                </button>
              </div>
            </div>

            {/* Ward BAN Cards with Comparison */}
            <WardBANCards
              stats={wardData.stats}
              comparison={wardData.citywide_comparison}
              wardCount={50}
              formatCurrency={formatCurrency}
            />

            {/* Map and Trends Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
              {/* Ward Detail Map */}
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                  Crash Locations in Ward {wardData.ward}
                </h2>
                <WardDetailMap
                  crashesGeojson={wardData.crashes_geojson}
                  boundaryGeojson={wardData.ward_boundary_geojson}
                />
              </div>

              {/* Seasonality Chart */}
              {wardTrends && (
                <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                    Monthly KSI Pattern
                  </h2>
                  <SeasonalityChart data={wardTrends.monthly_seasonality} year={selectedYear} />
                </div>
              )}
            </div>

            {/* Cost Breakdown */}
            {wardData.cost_breakdown && (
              <div className="mt-6">
                <CostBreakdownTable breakdown={wardData.cost_breakdown} />
              </div>
            )}
          </>
        )}

        {/* No Ward Selected State */}
        {activeTab === "ward" && !selectedWard && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-12 text-center">
            <p className="text-gray-600 dark:text-gray-400 text-lg">
              Select a ward from the map or table to view detailed statistics
            </p>
            <button
              onClick={() => setActiveTab("citywide")}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              Go to Citywide Overview
            </button>
          </div>
        )}

        {/* Credits */}
        <div className="mt-8 text-center text-sm text-gray-600 dark:text-gray-400">
          <p>
            Data from Chicago Data Portal. KSI = Killed or Seriously Injured.
          </p>
        </div>
      </div>
    </div>
  );
}
