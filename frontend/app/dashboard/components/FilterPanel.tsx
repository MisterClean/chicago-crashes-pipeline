"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, useCallback } from "react";

export function FilterPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [startDate, setStartDate] = useState(
    searchParams.get("start_date") || ""
  );
  const [endDate, setEndDate] = useState(searchParams.get("end_date") || "");

  const applyFilters = useCallback(() => {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);

    router.push(`/dashboard?${params.toString()}`);
  }, [router, startDate, endDate]);

  const clearFilters = useCallback(() => {
    setStartDate("");
    setEndDate("");
    router.push("/dashboard");
  }, [router]);

  // Quick date presets
  const setPreset = useCallback(
    (days: number) => {
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - days);

      setStartDate(start.toISOString().split("T")[0]);
      setEndDate(end.toISOString().split("T")[0]);
    },
    []
  );

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Quick presets */}
      <div className="flex gap-2">
        <button
          onClick={() => setPreset(7)}
          className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md text-gray-700 dark:text-gray-300"
        >
          7 Days
        </button>
        <button
          onClick={() => setPreset(30)}
          className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md text-gray-700 dark:text-gray-300"
        >
          30 Days
        </button>
        <button
          onClick={() => setPreset(365)}
          className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md text-gray-700 dark:text-gray-300"
        >
          1 Year
        </button>
      </div>

      {/* Date inputs */}
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor="start_date">
          Start Date
        </label>
        <input
          type="date"
          id="start_date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
        />
        <span className="text-gray-500">to</span>
        <label className="sr-only" htmlFor="end_date">
          End Date
        </label>
        <input
          type="date"
          id="end_date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
        />
      </div>

      {/* Action buttons */}
      <div className="flex gap-2">
        <button
          onClick={applyFilters}
          className="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-md font-medium"
        >
          Apply
        </button>
        {(startDate || endDate) && (
          <button
            onClick={clearFilters}
            className="px-4 py-1.5 text-sm bg-gray-200 dark:bg-gray-600 hover:bg-gray-300 dark:hover:bg-gray-500 text-gray-700 dark:text-gray-200 rounded-md"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
