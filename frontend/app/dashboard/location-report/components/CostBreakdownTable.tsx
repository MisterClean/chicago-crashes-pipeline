"use client";

import type { CostBreakdown } from "@/lib/api";

interface CostBreakdownTableProps {
  breakdown: CostBreakdown;
}

// Format currency with full precision for unit costs
function formatCurrencyFull(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

// Format currency abbreviated for subtotals and totals
function formatCurrencyAbbrev(value: number): string {
  if (value >= 1_000_000_000) {
    return `$${(value / 1_000_000_000).toFixed(1)}B`;
  } else if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1)}M`;
  } else if (value >= 1_000) {
    return `$${(value / 1_000).toFixed(1)}K`;
  }
  return formatCurrencyFull(value);
}

export function CostBreakdownTable({ breakdown }: CostBreakdownTableProps) {
  const { injury_costs, vehicle_costs, total_economic, total_societal } =
    breakdown;

  // Calculate person subtotals
  const personEconomicTotal = injury_costs.reduce(
    (sum, ic) => sum + ic.subtotal_economic,
    0
  );
  const personSocietalTotal = injury_costs.reduce(
    (sum, ic) => sum + ic.subtotal_societal,
    0
  );
  const personCount = injury_costs.reduce((sum, ic) => sum + ic.count, 0);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4 sm:p-6">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        Cost Breakdown by Injury Classification
      </h3>
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-700">
              <th className="text-left py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Classification
              </th>
              <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Count
              </th>
              <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden sm:table-cell">
                Unit Econ.
              </th>
              <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Subtotal Econ.
              </th>
              <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden sm:table-cell">
                Unit Societal
              </th>
              <th className="text-right py-3 px-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Subtotal Societal
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {/* Injury classification rows */}
            {injury_costs.map((ic, index) => (
              <tr
                key={ic.classification}
                className={`${
                  index % 2 === 0
                    ? "bg-white dark:bg-gray-800"
                    : "bg-gray-50 dark:bg-gray-800/50"
                } hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors`}
              >
                <td className="py-2 px-2">
                  <span className="text-sm text-gray-900 dark:text-gray-100">
                    {ic.classification_label}
                  </span>
                </td>
                <td className="py-2 px-2 text-right">
                  <span
                    className={`text-sm font-medium ${
                      ic.count > 0
                        ? "text-gray-900 dark:text-gray-100"
                        : "text-gray-400"
                    }`}
                  >
                    {ic.count.toLocaleString()}
                  </span>
                </td>
                <td className="py-2 px-2 text-right text-sm text-gray-500 dark:text-gray-400 hidden sm:table-cell">
                  {formatCurrencyFull(ic.unit_economic_cost)}
                </td>
                <td className="py-2 px-2 text-right">
                  <span
                    className={`text-sm font-medium ${
                      ic.subtotal_economic > 0
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-gray-400"
                    }`}
                  >
                    {formatCurrencyAbbrev(ic.subtotal_economic)}
                  </span>
                </td>
                <td className="py-2 px-2 text-right text-sm text-gray-500 dark:text-gray-400 hidden sm:table-cell">
                  {formatCurrencyFull(ic.unit_economic_cost + ic.unit_qaly_cost)}
                </td>
                <td className="py-2 px-2 text-right">
                  <span
                    className={`text-sm font-medium ${
                      ic.subtotal_societal > 0
                        ? "text-indigo-600 dark:text-indigo-400"
                        : "text-gray-400"
                    }`}
                  >
                    {formatCurrencyAbbrev(ic.subtotal_societal)}
                  </span>
                </td>
              </tr>
            ))}

            {/* Person subtotal row */}
            <tr className="bg-gray-100 dark:bg-gray-700/50 font-medium border-t border-gray-300 dark:border-gray-600">
              <td className="py-2 px-2 text-sm text-gray-700 dark:text-gray-300">
                Person Subtotal
              </td>
              <td className="py-2 px-2 text-right text-sm text-gray-700 dark:text-gray-300">
                {personCount.toLocaleString()}
              </td>
              <td className="py-2 px-2 hidden sm:table-cell"></td>
              <td className="py-2 px-2 text-right text-sm text-emerald-700 dark:text-emerald-300">
                {formatCurrencyAbbrev(personEconomicTotal)}
              </td>
              <td className="py-2 px-2 hidden sm:table-cell"></td>
              <td className="py-2 px-2 text-right text-sm text-indigo-700 dark:text-indigo-300">
                {formatCurrencyAbbrev(personSocietalTotal)}
              </td>
            </tr>

            {/* Vehicle row - only PDO (Property Damage Only) vehicles */}
            <tr className="bg-white dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700/50">
              <td className="py-2 px-2">
                <span className="text-sm text-gray-900 dark:text-gray-100">
                  PDO Vehicles
                </span>
                <span className="text-xs text-gray-500 dark:text-gray-400 block">
                  (property damage only)
                </span>
              </td>
              <td className="py-2 px-2 text-right">
                <span
                  className={`text-sm font-medium ${
                    vehicle_costs.count > 0
                      ? "text-gray-900 dark:text-gray-100"
                      : "text-gray-400"
                  }`}
                >
                  {vehicle_costs.count.toLocaleString()}
                </span>
              </td>
              <td className="py-2 px-2 text-right text-sm text-gray-500 dark:text-gray-400 hidden sm:table-cell">
                {formatCurrencyFull(vehicle_costs.unit_economic_cost)}
              </td>
              <td className="py-2 px-2 text-right">
                <span
                  className={`text-sm font-medium ${
                    vehicle_costs.subtotal_economic > 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-gray-400"
                  }`}
                >
                  {formatCurrencyAbbrev(vehicle_costs.subtotal_economic)}
                </span>
              </td>
              <td className="py-2 px-2 text-right text-sm text-gray-500 dark:text-gray-400 hidden sm:table-cell">
                {formatCurrencyFull(vehicle_costs.unit_economic_cost + vehicle_costs.unit_qaly_cost)}
              </td>
              <td className="py-2 px-2 text-right">
                <span
                  className={`text-sm font-medium ${
                    vehicle_costs.subtotal_societal > 0
                      ? "text-indigo-600 dark:text-indigo-400"
                      : "text-gray-400"
                  }`}
                >
                  {formatCurrencyAbbrev(vehicle_costs.subtotal_societal)}
                </span>
              </td>
            </tr>

            {/* Grand total row */}
            <tr className="bg-gray-200 dark:bg-gray-600 font-bold border-t-2 border-gray-300 dark:border-gray-500">
              <td className="py-3 px-2 text-sm text-gray-900 dark:text-white">
                Grand Total
              </td>
              <td className="py-3 px-2"></td>
              <td className="py-3 px-2 hidden sm:table-cell"></td>
              <td className="py-3 px-2 text-right text-sm text-emerald-700 dark:text-emerald-200">
                {formatCurrencyAbbrev(total_economic)}
              </td>
              <td className="py-3 px-2 hidden sm:table-cell"></td>
              <td className="py-3 px-2 text-right text-sm text-indigo-700 dark:text-indigo-200">
                {formatCurrencyAbbrev(total_societal)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
        <strong>Methodology:</strong> Person costs are calculated for injuries/fatalities (K-A-B-C).
        &quot;No Indication&quot; (O) persons = $0 since no injury was reported for that person. Instead,
        for (O) we substitute the count of vehicles involved in crashes with zero injuries, coded as
        &quot;Property Damage Only (PDO)&quot; using FHWA O-classification rates ($6,269 + $3,927 = $10,196/vehicle).
        Source: FHWA KABCO (2024$).
      </p>
    </div>
  );
}
