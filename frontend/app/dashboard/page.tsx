import { Suspense } from "react";
import { fetchDashboardStats, fetchWeeklyTrends } from "@/lib/api";
import { MetricCards } from "./components/MetricCards";
import { TrendCharts } from "./components/TrendCharts";
import { CrashMap } from "./components/CrashMap";
import { FilterPanel } from "./components/FilterPanel";

export const dynamic = "force-dynamic";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ start_date?: string; end_date?: string }>;
}) {
  const params = await searchParams;

  // Fetch data in parallel on the server
  const [stats, trends] = await Promise.all([
    fetchDashboardStats({
      start_date: params.start_date,
      end_date: params.end_date,
    }).catch(() => null),
    fetchWeeklyTrends(52).catch(() => []),
  ]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
              Chicago Crash Dashboard
            </h1>
            <p className="mt-1 text-gray-600 dark:text-gray-400">
              Visualizing traffic crash data across Chicago
            </p>
          </div>
          <div className="mt-4 lg:mt-0">
            <FilterPanel />
          </div>
        </div>

        {/* Metric Cards */}
        <Suspense fallback={<MetricCardsSkeleton />}>
          {stats ? (
            <MetricCards stats={stats} />
          ) : (
            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 mb-8">
              <p className="text-yellow-800 dark:text-yellow-200">
                Unable to load statistics. Please check the API connection.
              </p>
            </div>
          )}
        </Suspense>

        {/* Trend Charts */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mt-8">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
            Weekly Trends
          </h2>
          <Suspense fallback={<ChartSkeleton />}>
            <TrendCharts data={trends} />
          </Suspense>
        </div>

        {/* Crash Map - Full width on its own row */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mt-8">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
            Crash Locations
          </h2>
          <Suspense fallback={<MapSkeleton />}>
            <CrashMap
              startDate={params.start_date}
              endDate={params.end_date}
            />
          </Suspense>
        </div>

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

function MetricCardsSkeleton() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
      {[...Array(6)].map((_, i) => (
        <div
          key={i}
          className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4 animate-pulse"
        >
          <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4 mb-2" />
          <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
        </div>
      ))}
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="h-72 bg-gray-100 dark:bg-gray-700 rounded animate-pulse" />
  );
}

function MapSkeleton() {
  return (
    <div className="h-[600px] bg-gray-100 dark:bg-gray-700 rounded animate-pulse flex items-center justify-center">
      <span className="text-gray-400">Loading map...</span>
    </div>
  );
}
