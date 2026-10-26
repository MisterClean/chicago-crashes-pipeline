"use client";

import type { CostBreakdown, CostYearBreakdown } from "@/lib/api";
import { costBasisLabel, coverageLabel, formatCost } from "@/lib/costDisplay";
import { CostCoverageNotice } from "./CostCoverageNotice";

type CostRows = Pick<CostYearBreakdown, "injury_costs" | "vehicle_costs" | "total_economic" | "total_societal">;

function ClassificationTable({ breakdown, mixedYears = false }: { breakdown: CostRows; mixedYears?: boolean }) {
  const rows = [
    ...breakdown.injury_costs.map((row) => ({ ...row, label: row.classification_label })),
    { ...breakdown.vehicle_costs, classification: "vehicles", label: "Linked vehicles" },
  ];
  const unit = (economic: number | null, qaly: number | null = 0) =>
    economic === null || qaly === null
      ? mixedYears ? "Varies by year" : "Unavailable"
      : formatCost(economic + qaly, false);
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm tabular-nums">
        <caption className="sr-only">Costs by injury classification and linked vehicle, with priced record counts</caption>
        <thead className="border-b border-gray-200 text-gray-600 dark:border-gray-600 dark:text-gray-300">
          <tr>
            <th scope="col" className="py-3 pr-3 text-left font-medium">Classification</th>
            <th scope="col" className="px-2 py-3 text-right font-medium">Priced / records</th>
            <th scope="col" className="px-2 py-3 text-right font-medium">Unit economic</th>
            <th scope="col" className="px-2 py-3 text-right font-medium">Economic subtotal</th>
            <th scope="col" className="px-2 py-3 text-right font-medium">Unit societal</th>
            <th scope="col" className="pl-2 py-3 text-right font-medium">Societal subtotal</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
          {rows.map((row) => (
            <tr key={row.classification}>
              <th scope="row" className="py-3 pr-3 text-left font-normal text-gray-800 dark:text-gray-200">{row.label}</th>
              <td className="px-2 py-3 text-right">{row.priced_count.toLocaleString()} / {row.count.toLocaleString()}</td>
              <td className="px-2 py-3 text-right text-gray-500 dark:text-gray-400">{unit(row.unit_economic_cost)}</td>
              <td className="px-2 py-3 text-right">{formatCost(row.subtotal_economic)}</td>
              <td className="px-2 py-3 text-right text-gray-500 dark:text-gray-400">{unit(row.unit_economic_cost, row.unit_qaly_cost)}</td>
              <td className="pl-2 py-3 text-right">{formatCost(row.subtotal_societal)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t-2 border-gray-300 font-semibold dark:border-gray-600">
          <tr>
            <th scope="row" className="py-3 pr-3 text-left">Known cost total</th>
            <td colSpan={2}></td>
            <td className="px-2 py-3 text-right">{formatCost(breakdown.total_economic)}</td>
            <td></td>
            <td className="pl-2 py-3 text-right">{formatCost(breakdown.total_societal)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export function CostBreakdownTable({ breakdown }: { breakdown: CostBreakdown }) {
  const { years, methodology } = breakdown;
  return (
    <div className="rounded-lg bg-white p-4 text-gray-800 shadow-md dark:bg-gray-800 dark:text-gray-200 sm:p-6">
      <h3 className="mb-2 text-lg font-semibold text-gray-900 dark:text-white">Cost Breakdown by Crash Year</h3>
      <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
        {costBasisLabel(breakdown)}. Each crash uses its own year&apos;s rates. Multi-year totals combine nominal dollars and are not adjusted to a common year.
      </p>
      <CostCoverageNotice coverage={breakdown.coverage} />
      <div className="overflow-x-auto">
        <table className="mb-5 min-w-full text-sm tabular-nums">
          <caption className="sr-only">Yearly known costs and valuation coverage</caption>
          <thead className="border-b border-gray-200 text-gray-600 dark:border-gray-600 dark:text-gray-300">
            <tr>
              <th scope="col" className="py-2 pr-3 text-left">Dollar year</th>
              <th scope="col" className="px-2 py-2 text-right">Crashes</th>
              <th scope="col" className="px-2 py-2 text-right">Economic cost</th>
              <th scope="col" className="px-2 py-2 text-right">Societal cost</th>
              <th scope="col" className="pl-3 py-2 text-left">Coverage</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {years.map((row) => (
              <tr key={row.year ?? "unknown"}>
                <th scope="row" className="py-3 pr-3 text-left font-medium">{row.year ?? "Missing crash year"}</th>
                <td className="px-2 py-3 text-right">{row.crash_count.toLocaleString()}</td>
                <td className="px-2 py-3 text-right">{formatCost(row.total_economic)}</td>
                <td className="px-2 py-3 text-right">{formatCost(row.total_societal)}</td>
                <td className="pl-3 py-3">{coverageLabel(row.coverage)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h4 className="mb-1 font-medium">All selected years by classification</h4>
      <ClassificationTable breakdown={breakdown} mixedYears={years.length > 1} />
      {years.map((row) => (
        <details key={row.year ?? "unknown"} className="mt-3 border-t border-gray-200 pt-3 dark:border-gray-700">
          <summary className="cursor-pointer font-medium">{row.year ?? "Missing crash year"}: unit rates and classification detail</summary>
          <div className="mt-3">
            {methodology.annual_inputs.find((input) => input.year === row.year) && (
              <p className="mb-3 text-xs text-gray-600 dark:text-gray-400">
                Annual CPI-U: {methodology.annual_inputs.find((input) => input.year === row.year)?.cpi}.
                {" "}Mean quarterly weekly earnings: ${methodology.annual_inputs.find((input) => input.year === row.year)?.muwe}.
                {" "}Unit rates below are in {row.year} dollars, rounded to cents.
              </p>
            )}
            <CostCoverageNotice coverage={row.coverage} />
            <ClassificationTable breakdown={row} />
          </div>
        </details>
      ))}
      <p className="mt-4 text-xs text-gray-500 dark:text-gray-400">
        Every linked person is priced by KABCO classification (K, A, B, C, or O), plus each linked vehicle&apos;s economic cost. Societal cost adds quality-of-life loss (QALY); vehicle QALY is zero. Unknown classifications are excluded and flagged. The parent crash date determines the dollar year.
      </p>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        Supported years: {methodology.supported_years.join(", ")}. Other years have unavailable estimates.
        {" "}Rates use FHWA&apos;s {methodology.base_dollar_year}-dollar person and vehicle inputs published in {methodology.publication_year}, adjusted using CPI-U for economic costs and the mean of four quarterly median weekly earnings for QALY.
        {" "}Method: {methodology.version}. <a href={methodology.source_url} target="_blank" rel="noopener noreferrer" className="underline">FHWA source</a>.
      </p>
    </div>
  );
}
