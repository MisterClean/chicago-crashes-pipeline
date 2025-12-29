"use client";

import type { LocationReportStats } from "@/lib/api";

interface ReportStatsProps {
  stats: LocationReportStats;
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
      {/* Main Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4 mb-6">
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
      </div>
    </div>
  );
}
