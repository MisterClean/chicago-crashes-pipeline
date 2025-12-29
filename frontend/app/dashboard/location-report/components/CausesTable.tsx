"use client";

import type { CrashCauseSummary } from "@/lib/api";

interface CausesTableProps {
  causes: CrashCauseSummary[];
}

export function CausesTable({ causes }: CausesTableProps) {
  if (causes.length === 0) {
    return (
      <div className="text-center text-gray-500 dark:text-gray-400 py-8">
        No crash data available for this area
      </div>
    );
  }

  // Format cause name for display
  const formatCause = (cause: string): string => {
    if (!cause || cause === "UNKNOWN") return "Unknown / Not Reported";
    // Convert from ALL_CAPS to Title Case
    return cause
      .toLowerCase()
      .split(/[\s_]+/)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full">
        <thead>
          <tr className="border-b border-gray-200 dark:border-gray-700">
            <th className="text-left py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Cause
            </th>
            <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Crashes
            </th>
            <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              %
            </th>
            <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Injuries
            </th>
            <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Fatal
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
          {causes.map((cause, index) => (
            <tr
              key={cause.cause}
              className={`${
                index % 2 === 0
                  ? "bg-white dark:bg-gray-800"
                  : "bg-gray-50 dark:bg-gray-800/50"
              } hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors`}
            >
              <td className="py-2 px-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-900 dark:text-gray-100">
                    {formatCause(cause.cause)}
                  </span>
                </div>
              </td>
              <td className="py-2 px-2 text-right">
                <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {cause.crashes.toLocaleString()}
                </span>
              </td>
              <td className="py-2 px-2 text-right">
                <div className="flex items-center justify-end gap-2">
                  <div className="w-16 bg-gray-200 dark:bg-gray-600 rounded-full h-2">
                    <div
                      className="bg-blue-600 h-2 rounded-full"
                      style={{ width: `${Math.min(cause.percentage, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 dark:text-gray-400 w-10 text-right">
                    {cause.percentage}%
                  </span>
                </div>
              </td>
              <td className="py-2 px-2 text-right">
                <span
                  className={`text-sm ${
                    cause.injuries > 0
                      ? "text-orange-600 font-medium"
                      : "text-gray-400"
                  }`}
                >
                  {cause.injuries.toLocaleString()}
                </span>
              </td>
              <td className="py-2 px-2 text-right">
                <span
                  className={`text-sm ${
                    cause.fatalities > 0
                      ? "text-red-600 font-bold"
                      : "text-gray-400"
                  }`}
                >
                  {cause.fatalities > 0 ? cause.fatalities : "-"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
