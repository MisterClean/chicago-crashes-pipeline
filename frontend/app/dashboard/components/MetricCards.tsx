"use client";

import type { DashboardStats } from "@/lib/api";

interface MetricCardsProps {
  stats: DashboardStats;
}

export function MetricCards({ stats }: MetricCardsProps) {
  const metrics = [
    {
      label: "Total Crashes",
      value: stats.total_crashes,
      color: "text-gray-900 dark:text-white",
    },
    {
      label: "Total Injuries",
      value: stats.total_injuries,
      color: "text-orange-600",
    },
    {
      label: "Fatalities",
      value: stats.total_fatalities,
      color: "text-red-600",
    },
    {
      label: "Pedestrians",
      value: stats.pedestrians_involved,
      color: "text-blue-600",
    },
    {
      label: "Cyclists",
      value: stats.cyclists_involved,
      color: "text-green-600",
    },
    {
      label: "Hit & Run",
      value: stats.hit_and_run_count,
      color: "text-purple-600",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
      {metrics.map((metric) => (
        <div
          key={metric.label}
          className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4"
        >
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {metric.label}
          </p>
          <p className={`text-2xl font-bold ${metric.color}`}>
            {metric.value.toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}
