import type { CostCoverage } from "@/lib/api";
import { coverageLabel } from "@/lib/costDisplay";

export function CostCoverageNotice({ coverage }: { coverage: CostCoverage }) {
  const details = [
    [coverage.unknown_injury_count, "people with unknown injury classifications"],
    [coverage.missing_people_crashes, "crashes missing linked people"],
    [coverage.missing_vehicle_crashes, "crashes missing linked vehicles"],
    [coverage.inconsistent_injury_crashes, "crashes with inconsistent injury counts"],
    [coverage.inconsistent_vehicle_crashes, "crashes with inconsistent vehicle counts"],
  ] as const;
  return (
    <div className="mb-4 rounded-md border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-700/30 dark:text-gray-300" role="status">
      <p className="font-medium">{coverageLabel(coverage)}</p>
      {coverage.status !== "empty" && (
        <p className="mt-1">
          {coverage.complete_crashes.toLocaleString()} of {coverage.crash_count.toLocaleString()} crashes have complete estimates;
          {" "}{coverage.partial_crashes.toLocaleString()} partial and {coverage.unavailable_crashes.toLocaleString()} unavailable.
          {coverage.status !== "complete" && " Totals include only available components; unavailable costs are not treated as zero."}
        </p>
      )}
      {details.some(([count]) => count > 0) && (
        <p className="mt-1">{details.filter(([count]) => count > 0).map(([count, label]) => `${count.toLocaleString()} ${label}`).join("; ")}. Categories may overlap.</p>
      )}
      {coverage.status !== "empty" && (
        <p className="mt-1 text-xs">Coverage reflects observed consistency; it does not prove the source has published every record.</p>
      )}
    </div>
  );
}
