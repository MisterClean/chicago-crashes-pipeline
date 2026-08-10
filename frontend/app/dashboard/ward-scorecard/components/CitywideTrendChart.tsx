"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { WardTrendResponse } from "@/lib/api";

interface CitywideTrendChartProps {
  data: WardTrendResponse;
}

export function CitywideTrendChart({ data }: CitywideTrendChartProps) {
  // Transform data for recharts
  const chartData = data.years.map((year, index) => ({
    year,
    ksi: data.citywide.ksi[index],
    fatalities: data.citywide.fatalities[index],
    serious_injuries: data.citywide.serious_injuries[index],
  }));

  return (
    <div className="h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-gray-200 dark:stroke-gray-700" />
          <XAxis
            dataKey="year"
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
          <Line
            type="monotone"
            dataKey="ksi"
            name="KSI (Total)"
            stroke="#dc2626"
            strokeWidth={3}
            dot={{ fill: "#dc2626", strokeWidth: 2 }}
            activeDot={{ r: 8 }}
          />
          <Line
            type="monotone"
            dataKey="fatalities"
            name="Fatalities"
            stroke="#7c3aed"
            strokeWidth={2}
            dot={{ fill: "#7c3aed", strokeWidth: 2 }}
          />
          <Line
            type="monotone"
            dataKey="serious_injuries"
            name="Serious Injuries"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={{ fill: "#f59e0b", strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
