// Legacy dashboard links use calendar dates. Only accept values the date inputs
// and backend can both represent; do not normalize a typo into another day.
function calendarDate(value: string | null, fallback: string): string {
  if (value === "") return "";
  if (value === null || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) {
    return fallback;
  }
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value
    ? value : fallback;
}

export function initialReportDates(
  searchParams: Pick<URLSearchParams, "get">,
  defaults: { startDate: string; endDate: string },
) {
  const startDate = calendarDate(searchParams.get("start_date"), defaults.startDate);
  const endDate = calendarDate(searchParams.get("end_date"), defaults.endDate);
  return {
    startDate,
    endDate,
    preset: startDate === defaults.startDate && endDate === defaults.endDate ? "1yr" : null,
  };
}
