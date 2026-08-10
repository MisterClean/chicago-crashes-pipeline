"use client";

import { useState, useMemo } from "react";
import type { WardRanking } from "@/lib/api";

interface WardRankingTableProps {
  rankings: WardRanking[];
  onWardClick: (ward: number) => void;
  selectedWard: number | null;
  formatCurrency: (value: number) => string;
}

type SortKey = "ward" | "ksi" | "fatalities" | "serious_injuries" | "vru_injuries" | "societal_cost";
type SortDirection = "asc" | "desc";

export function WardRankingTable({
  rankings,
  onWardClick,
  selectedWard,
  formatCurrency,
}: WardRankingTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("ksi");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const sortedRankings = useMemo(() => {
    return [...rankings].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (sortDirection === "asc") return aVal > bVal ? 1 : -1;
      return aVal < bVal ? 1 : -1;
    });
  }, [rankings, sortKey, sortDirection]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDirection("desc");
    }
  };

  const SortIcon = ({ columnKey }: { columnKey: SortKey }) => {
    if (sortKey !== columnKey) return null;
    return (
      <span className="ml-1">
        {sortDirection === "asc" ? "↑" : "↓"}
      </span>
    );
  };

  const headerClass =
    "px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700";

  return (
    <div className="overflow-auto max-h-[400px]">
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
          <tr>
            <th
              className={headerClass}
              onClick={() => handleSort("ward")}
            >
              Ward <SortIcon columnKey="ward" />
            </th>
            <th
              className={headerClass}
              onClick={() => handleSort("ksi")}
            >
              KSI <SortIcon columnKey="ksi" />
            </th>
            <th
              className={headerClass}
              onClick={() => handleSort("fatalities")}
            >
              Fatal <SortIcon columnKey="fatalities" />
            </th>
            <th
              className={headerClass}
              onClick={() => handleSort("serious_injuries")}
            >
              Serious <SortIcon columnKey="serious_injuries" />
            </th>
            <th
              className={headerClass}
              onClick={() => handleSort("vru_injuries")}
            >
              VRU <SortIcon columnKey="vru_injuries" />
            </th>
            <th
              className={headerClass}
              onClick={() => handleSort("societal_cost")}
            >
              Cost <SortIcon columnKey="societal_cost" />
            </th>
          </tr>
        </thead>
        <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
          {sortedRankings.map((ward, index) => (
            <tr
              key={ward.ward}
              onClick={() => onWardClick(ward.ward)}
              className={`cursor-pointer transition-colors ${
                selectedWard === ward.ward
                  ? "bg-blue-50 dark:bg-blue-900/30"
                  : "hover:bg-gray-50 dark:hover:bg-gray-700/50"
              }`}
            >
              <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100">
                <span className="inline-flex items-center gap-2">
                  <span className="w-6 h-6 flex items-center justify-center bg-gray-100 dark:bg-gray-700 rounded-full text-xs">
                    {index + 1}
                  </span>
                  Ward {ward.ward}
                </span>
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-red-600 dark:text-red-400 font-semibold">
                {ward.ksi}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                {ward.fatalities}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                {ward.serious_injuries}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                {ward.vru_injuries}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-600 dark:text-gray-400">
                {formatCurrency(ward.societal_cost)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
