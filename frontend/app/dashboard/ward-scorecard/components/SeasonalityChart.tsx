"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from "recharts";
import type { MonthlySeasonalityData } from "@/lib/api";

interface SeasonalityChartProps {
  data: MonthlySeasonalityData;
  year: number;
}

export function SeasonalityChart({ data, year }: SeasonalityChartProps) {
  // Transform data for recharts
  const chartData = data.months.map((month, index) => ({
    month,
    [year]: data.selected_year.ksi[index],
    "5-Year Avg": data.five_year_avg.ksi[index],
  }));

  return (
    <div className="h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-gray-200 dark:stroke-gray-700" />
          <XAxis
            dataKey="month"
            className="text-xs"
            tick={{ fill: "currentColor" }}
          />
          <YAxis
            className="text-xs"
            tick={{ fill: "currentColor" }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--tooltip-bg, #fff)",
              borderColor: "var(--tooltip-border, #e5e7eb)",
              borderRadius: "0.5rem",
            }}
            labelStyle={{ fontWeight: "bold" }}
          />
          <Legend />
          <Bar
            dataKey={year.toString()}
            name={`${year} KSI`}
            fill="#3b82f6"
            radius={[4, 4, 0, 0]}
          />
          <Line
            type="monotone"
            dataKey="5-Year Avg"
            name="5-Year Average"
            stroke="#dc2626"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={{ fill: "#dc2626", strokeWidth: 2, r: 4 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="text-xs text-gray-500 dark:text-gray-400 text-center mt-2">
        Bars show {year} monthly KSI. Dashed line shows 5-year average for comparison.
      </p>
    </div>
  );
}
