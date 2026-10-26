import type { CostBreakdown, CostCoverage } from "./api";

export function formatCost(value: number | null | undefined, abbreviated = true): string {
  if (value === null || value === undefined) return "Unavailable";
  if (abbreviated) {
    if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: abbreviated ? 0 : 2,
    maximumFractionDigits: abbreviated ? 0 : 2,
  }).format(value);
}

export function costBasisLabel(breakdown?: CostBreakdown): string {
  if (!breakdown) return "Crash-year nominal dollars";
  const years = breakdown.years.map(({ year }) => year);
  return years.length === 1 && years[0] !== null
    ? `${years[0]} dollars`
    : "Sum of crash-year nominal dollars";
}

export function coverageLabel(coverage?: CostCoverage): string {
  switch (coverage?.status) {
    case "complete": return "Complete estimate";
    case "partial": return "Partial estimate: known costs only";
    case "unavailable": return "Cost estimate unavailable";
    case "empty": return "No crashes selected";
    default: return "Cost coverage unavailable";
  }
}
