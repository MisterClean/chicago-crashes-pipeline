"use client";

import type { WardStats } from "@/lib/api";

interface WardBANCardsProps {
  stats: WardStats;
  comparison?: WardStats;
  wardCount?: number;
  formatCurrency: (value: number) => string;
}

export function WardBANCards({
  stats,
  comparison,
  wardCount = 50,
  formatCurrency,
}: WardBANCardsProps) {
  // Calculate ward's share of citywide when comparison is provided
  const getPercentOfCitywide = (wardValue: number, citywideValue: number): string => {
    if (!citywideValue) return "0%";
    return `${((wardValue / citywideValue) * 100).toFixed(1)}%`;
  };

  const getPerWardAvg = (citywideValue: number): number => {
    return Math.round(citywideValue / wardCount);
  };

  const metrics = [
    {
      label: "KSI",
      field: "ksi" as keyof WardStats,
      value: stats.ksi,
      color: "text-red-600 dark:text-red-400",
      bgColor: "bg-red-50 dark:bg-red-900/20",
      description: "Killed or Seriously Injured",
    },
    {
      label: "Fatalities",
      field: "fatalities" as keyof WardStats,
      value: stats.fatalities,
      color: "text-red-700 dark:text-red-500",
      bgColor: "bg-red-100 dark:bg-red-900/30",
      description: "Fatal crashes",
    },
    {
      label: "Serious Injuries",
      field: "serious_injuries" as keyof WardStats,
      value: stats.serious_injuries,
      color: "text-amber-600 dark:text-amber-400",
      bgColor: "bg-amber-50 dark:bg-amber-900/20",
      description: "Incapacitating injuries",
    },
    {
      label: "VRU Injuries",
      field: "vru_injuries" as keyof WardStats,
      value: stats.vru_injuries,
      color: "text-blue-600 dark:text-blue-400",
      bgColor: "bg-blue-50 dark:bg-blue-900/20",
      description: "Pedestrians & cyclists",
    },
    {
      label: "Children Injured",
      field: "children_injured" as keyof WardStats,
      value: stats.children_injured,
      color: "text-purple-600 dark:text-purple-400",
      bgColor: "bg-purple-50 dark:bg-purple-900/20",
      description: "Under 18 years old",
    },
    {
      label: "Hit & Run",
      field: "hit_and_run" as keyof WardStats,
      value: stats.hit_and_run,
      color: "text-slate-600 dark:text-slate-400",
      bgColor: "bg-slate-50 dark:bg-slate-800",
      description: "Crashes with fleeing driver",
    },
  ];

  return (
    <div>
      {/* Cost Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div className="bg-gradient-to-br from-emerald-500 to-emerald-600 rounded-lg shadow-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-emerald-100 mb-1">
                Economic Cost
              </p>
              <p className="text-3xl font-bold">
                {formatCurrency(stats.economic_cost)}
              </p>
              {comparison && (
                <p className="text-xs text-emerald-200 mt-2">
                  {getPercentOfCitywide(stats.economic_cost, comparison.economic_cost)} of citywide
                </p>
              )}
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
              <p className="text-sm font-medium text-indigo-100 mb-1">
                Societal Cost
              </p>
              <p className="text-3xl font-bold">
                {formatCurrency(stats.societal_cost)}
              </p>
              {comparison && (
                <p className="text-xs text-indigo-200 mt-2">
                  {getPercentOfCitywide(stats.societal_cost, comparison.societal_cost)} of citywide
                </p>
              )}
            </div>
            <div className="text-indigo-200">
              <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
          </div>
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className={`${metric.bgColor} rounded-lg shadow-sm p-4`}
          >
            <p className="text-xs text-gray-600 dark:text-gray-400 mb-1">
              {metric.label}
            </p>
            <p className={`text-2xl font-bold ${metric.color} tabular-nums`}>
              {metric.value.toLocaleString()}
            </p>
            {comparison && (
              <p className="text-[10px] text-gray-500 dark:text-gray-500 mt-1">
                Avg: {getPerWardAvg(comparison[metric.field] as number).toLocaleString()}
              </p>
            )}
            <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">
              {metric.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
