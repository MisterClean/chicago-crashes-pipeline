"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";
import type { MonthlyTrendPoint } from "@/lib/api";

interface TrendSparklinesProps {
  data: MonthlyTrendPoint[];
}

export function TrendSparklines({ data }: TrendSparklinesProps) {
  if (data.length === 0) {
    return (
      <div className="text-center text-gray-500 dark:text-gray-400 py-8">
        No trend data available for this period
      </div>
    );
  }

  // Format month for display
  const formatMonth = (month: string): string => {
    const date = new Date(month + "-01");
    return date.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  };

  // Custom tooltip
  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean;
    payload?: Array<{ value: number; name: string; color: string }>;
    label?: string;
  }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3">
          <p className="text-sm font-medium text-gray-900 dark:text-white mb-2">
            {label ? formatMonth(label) : ""}
          </p>
          {payload.map((entry) => (
            <p
              key={entry.name}
              className="text-xs"
              style={{ color: entry.color }}
            >
              {entry.name}: {entry.value.toLocaleString()}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  // Calculate totals for summary
  const totals = data.reduce(
    (acc, point) => ({
      crashes: acc.crashes + point.crashes,
      injuries: acc.injuries + point.injuries,
      fatalities: acc.fatalities + point.fatalities,
    }),
    { crashes: 0, injuries: 0, fatalities: 0 }
  );

  const avgCrashes = data.length > 0 ? Math.round(totals.crashes / data.length) : 0;
  const avgInjuries = data.length > 0 ? Math.round(totals.injuries / data.length) : 0;

  return (
    <div className="space-y-6">
      {/* Summary row */}
      <div className="grid grid-cols-3 gap-4 text-center">
        <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
          <p className="text-xs text-gray-500 dark:text-gray-400">Avg/Month</p>
          <p className="text-lg font-bold text-gray-900 dark:text-white">
            {avgCrashes}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400">crashes</p>
        </div>
        <div className="bg-sky-50 dark:bg-sky-900/20 rounded-lg p-3">
          <p className="text-xs text-gray-500 dark:text-gray-400">Avg/Month</p>
          <p className="text-lg font-bold" style={{ color: "#56B4E9" }}>{avgInjuries}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">injuries</p>
        </div>
        <div className="bg-violet-50 dark:bg-violet-900/20 rounded-lg p-3">
          <p className="text-xs text-gray-500 dark:text-gray-400">Total</p>
          <p className="text-lg font-bold" style={{ color: "#440154" }}>{totals.fatalities}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">fatalities</p>
        </div>
      </div>

      {/* Crashes Trend */}
      <div>
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Crashes
        </p>
        <div className="h-24">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="crashGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="month"
                tickFormatter={formatMonth}
                tick={{ fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis hide domain={[0, "auto"]} />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="crashes"
                stroke="#3b82f6"
                strokeWidth={2}
                fill="url(#crashGradient)"
                name="Crashes"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Injuries Trend */}
      <div>
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Injuries
        </p>
        <div className="h-24">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="injuryGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#56B4E9" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#56B4E9" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="month"
                tickFormatter={formatMonth}
                tick={{ fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis hide domain={[0, "auto"]} />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="injuries"
                stroke="#56B4E9"
                strokeWidth={2}
                fill="url(#injuryGradient)"
                name="Injuries"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Fatalities Trend (only if there are any) */}
      {totals.fatalities > 0 && (
        <div>
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Fatalities
          </p>
          <div className="h-24">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data}>
                <defs>
                  <linearGradient id="fatalityGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#440154" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#440154" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="month"
                  tickFormatter={formatMonth}
                  tick={{ fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis hide domain={[0, "auto"]} />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="fatalities"
                  stroke="#440154"
                  strokeWidth={2}
                  fill="url(#fatalityGradient)"
                  name="Fatalities"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
