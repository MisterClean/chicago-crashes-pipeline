"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { WeeklyTrend } from "@/lib/api";

interface TrendChartsProps {
  data: WeeklyTrend[];
}

export function TrendCharts({ data }: TrendChartsProps) {
  if (!data || data.length === 0) {
    return (
      <div className="h-72 flex items-center justify-center text-gray-500">
        No trend data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={288}>
      <AreaChart
        data={data}
        margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="week"
          tick={{ fontSize: 12 }}
          tickLine={false}
          axisLine={{ stroke: "#e5e7eb" }}
        />
        <YAxis
          tick={{ fontSize: 12 }}
          tickLine={false}
          axisLine={{ stroke: "#e5e7eb" }}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "white",
            border: "1px solid #e5e7eb",
            borderRadius: "8px",
            boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
          }}
          labelStyle={{ fontWeight: "bold" }}
        />
        <Legend />
        <Area
          type="monotone"
          dataKey="crashes"
          name="Crashes"
          stroke="#6366f1"
          fill="#6366f1"
          fillOpacity={0.3}
        />
        <Area
          type="monotone"
          dataKey="injuries"
          name="Injuries"
          stroke="#f97316"
          fill="#f97316"
          fillOpacity={0.3}
        />
        <Area
          type="monotone"
          dataKey="fatalities"
          name="Fatalities"
          stroke="#dc2626"
          fill="#dc2626"
          fillOpacity={0.3}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
