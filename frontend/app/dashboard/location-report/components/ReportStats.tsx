"use client";

import type { LocationReportStats } from "@/lib/api";

interface ReportStatsProps {
  stats: LocationReportStats;
}

// Format currency in abbreviated form ($1.2M, $45.3K, etc.)
function formatCurrency(value: number | undefined | null): string {
  if (value === undefined || value === null) {
    return "$0";
  }
  if (value >= 1_000_000_000) {
    return `$${(value / 1_000_000_000).toFixed(1)}B`;
  } else if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1)}M`;
  } else if (value >= 1_000) {
    return `$${(value / 1_000).toFixed(1)}K`;
  } else {
    return `$${value.toFixed(0)}`;
  }
}

export function ReportStats({ stats }: ReportStatsProps) {
  const metrics = [
    {
      label: "Total Crashes",
      value: stats.total_crashes,
      color: "text-gray-900 dark:text-white",
      bgColor: "bg-gray-100 dark:bg-gray-700",
    },
    {
      label: "Fatalities",
      value: stats.total_fatalities,
      color: "text-red-600",
      bgColor: "bg-red-50 dark:bg-red-900/20",
      highlight: stats.total_fatalities > 0,
    },
    {
      label: "Incapacitating Injuries",
      value: stats.incapacitating_injuries,
      color: "text-orange-600",
      bgColor: "bg-orange-50 dark:bg-orange-900/20",
    },
    {
      label: "Total Injuries",
      value: stats.total_injuries,
      color: "text-yellow-600",
      bgColor: "bg-yellow-50 dark:bg-yellow-900/20",
    },
    {
      label: "Pedestrians Involved",
      value: stats.pedestrians_involved,
      color: "text-blue-600",
      bgColor: "bg-blue-50 dark:bg-blue-900/20",
    },
    {
      label: "Cyclists Involved",
      value: stats.cyclists_involved,
      color: "text-green-600",
      bgColor: "bg-green-50 dark:bg-green-900/20",
    },
    {
      label: "Hit & Run",
      value: stats.hit_and_run_count,
      color: "text-purple-600",
      bgColor: "bg-purple-50 dark:bg-purple-900/20",
    },
    {
      label: "Crashes with Injuries",
      value: stats.crashes_with_injuries,
      color: "text-amber-600",
      bgColor: "bg-amber-50 dark:bg-amber-900/20",
    },
    {
      label: "Vehicles Involved",
      value: stats.total_vehicles ?? 0,
      color: "text-slate-600",
      bgColor: "bg-slate-50 dark:bg-slate-900/20",
    },
  ];

  // Calculate percentages
  const injuryRate = stats.total_crashes > 0
    ? Math.round((stats.crashes_with_injuries / stats.total_crashes) * 100)
    : 0;
  const fatalityRate = stats.total_crashes > 0
    ? ((stats.crashes_with_fatalities / stats.total_crashes) * 100).toFixed(2)
    : "0";

  return (
    <div>
      {/* Cost Estimates - Featured prominently */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="bg-gradient-to-br from-emerald-500 to-emerald-600 rounded-lg shadow-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-emerald-100 mb-1 flex items-center gap-1.5">
                Est. Economic Cost
                <span className="inline-flex items-center justify-center w-4 h-4 text-[10px] font-bold bg-emerald-400/50 rounded-full cursor-help" title="See methodology footnote below">i</span>
              </p>
              <p className="text-3xl font-bold">
                {formatCurrency(stats.estimated_economic_damages)}
              </p>
              <p className="text-xs text-emerald-200 mt-2">
                Based on FHWA KABCO methodology (2024$)
              </p>
            </div>
            <div className="text-emerald-200">
              <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
        </div>

        <div className="bg-gradient-to-br from-indigo-500 to-indigo-600 rounded-lg shadow-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-indigo-100 mb-1 flex items-center gap-1.5">
                Est. Total Societal Cost
                <span className="inline-flex items-center justify-center w-4 h-4 text-[10px] font-bold bg-indigo-400/50 rounded-full cursor-help" title="See methodology footnote below">i</span>
              </p>
              <p className="text-3xl font-bold">
                {formatCurrency(stats.estimated_societal_costs)}
              </p>
              <p className="text-xs text-indigo-200 mt-2">
                Includes economic + quality-adjusted life years (QALY)
              </p>
            </div>
            <div className="text-indigo-200">
              <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
              </svg>
            </div>
          </div>
        </div>
      </div>

      {/* Main Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-9 gap-4 mb-6">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className={`${metric.bgColor} rounded-lg shadow-md p-4 ${
              metric.highlight ? "ring-2 ring-red-500" : ""
            }`}
          >
            <p className="text-xs text-gray-600 dark:text-gray-400 mb-1">
              {metric.label}
            </p>
            <p className={`text-2xl font-bold ${metric.color}`}>
              {metric.value.toLocaleString()}
            </p>
          </div>
        ))}
      </div>

      {/* Summary Statistics */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Key Insights
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Injury Rate */}
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center">
              <span className="text-2xl font-bold text-yellow-600">{injuryRate}%</span>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-white">
                Injury Rate
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                of crashes result in injuries
              </p>
            </div>
          </div>

          {/* Fatality Rate */}
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
              <span className="text-xl font-bold text-red-600">{fatalityRate}%</span>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-white">
                Fatality Rate
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                of crashes result in fatalities
              </p>
            </div>
          </div>

          {/* Vulnerable Road Users */}
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
              <span className="text-2xl font-bold text-blue-600">
                {stats.pedestrians_involved + stats.cyclists_involved}
              </span>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-white">
                Vulnerable Road Users
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                pedestrians and cyclists involved
              </p>
            </div>
          </div>
        </div>

        {/* Data Quality Note */}
        {(stats.unknown_injury_count ?? 0) > 0 && (
          <div className="mt-4 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              <span className="font-medium">Data Quality Note:</span>{" "}
              {stats.unknown_injury_count.toLocaleString()} people had unknown/blank injury classifications
              and were excluded from cost estimates.
            </p>
          </div>
        )}
      </div>

    </div>
  );
}
