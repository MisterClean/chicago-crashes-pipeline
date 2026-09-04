"use client";

import { useRef, useState } from "react";
import type { HourDayCount, RoadUserSeverity } from "@/lib/api";

const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const hours = Array.from({ length: 24 }, (_, hour) => hour);
const modes = { crashes: "All crashes", injury_crashes: "Injury crashes", severe_crashes: "Fatal / incapacitating crashes" } as const;

export function TimingHeatmap({ data }: { data: HourDayCount[] }) {
  const [mode, setMode] = useState<keyof typeof modes>("crashes");
  const [focus, setFocus] = useState(0);
  const [detail, setDetail] = useState("");
  const table = useRef<HTMLTableElement>(null);
  const cells = new Map(data.map((cell) => [cell.day * 24 + cell.hour, cell[mode]]));
  const maximum = Math.max(0, ...cells.values());
  const total = [...cells.values()].reduce((sum, value) => sum + value, 0);
  return <section className="mt-8 rounded-lg bg-white dark:bg-gray-800 shadow-md p-6">
    <h2 className="text-xl font-semibold mb-2">When crashes happen</h2>
    <p className="text-sm text-gray-500 mb-4">Chicago local time · full selected area and dates. Counts show frequency, not traffic-adjusted risk. Injury crashes include fatal injuries.</p>
    <div className="flex flex-wrap gap-2 mb-4" aria-label="Crash severity">
      {Object.entries(modes).map(([key, label]) => <button key={key} type="button" aria-pressed={mode === key} onClick={() => { setMode(key as keyof typeof modes); setDetail(""); }} className={`rounded px-3 py-2 text-sm ${mode === key ? "bg-blue-700 text-white" : "bg-gray-100 dark:bg-gray-700"}`}>{label}</button>)}
    </div>
    <div className="overflow-x-auto" role="region" aria-label="Weekday and hour crash counts" tabIndex={0}>
      <table ref={table} className="w-full min-w-[820px] text-xs border-separate border-spacing-1">
        <caption className="sr-only">{modes[mode]} by day and hour. Use arrow keys to navigate cells; Home and End move within a day.</caption>
        <thead><tr><th scope="col">Day</th>{hours.map((hour) => <th key={hour} scope="col">{hour.toString().padStart(2, "0")}</th>)}<th scope="col">Total</th></tr></thead>
        <tbody>{days.map((day, dayIndex) => <tr key={day}><th scope="row" className="text-left">{day.slice(0, 3)}</th>{hours.map((hour) => {
          const index = dayIndex * 24 + hour;
          const count = cells.get(index) || 0;
          const label = `${day}, ${hour}:00–${hour + 1}:00: ${count.toLocaleString()} ${modes[mode].toLowerCase()} (${total ? (100 * count / total).toFixed(1) : 0}%).`;
          return <td key={hour}><button type="button" data-cell={index} tabIndex={index === focus ? 0 : -1} aria-label={label} title={label}
            className="w-full h-8 rounded focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-blue-600"
            style={{ backgroundColor: count ? `hsl(214 75% ${92 - 57 * count / Math.max(1, maximum)}%)` : "#e5e7eb", color: count > maximum * 0.55 ? "white" : "#172554" }}
            onMouseEnter={() => setDetail(label)} onClick={() => setDetail(label)} onFocus={() => { setFocus(index); setDetail(label); }}
            onKeyDown={(event) => {
              let next = index;
              if (event.key === "ArrowRight") next = dayIndex * 24 + Math.min(23, hour + 1);
              else if (event.key === "ArrowLeft") next = dayIndex * 24 + Math.max(0, hour - 1);
              else if (event.key === "ArrowDown") next = Math.min(6, dayIndex + 1) * 24 + hour;
              else if (event.key === "ArrowUp") next = Math.max(0, dayIndex - 1) * 24 + hour;
              else if (event.key === "Home") next = dayIndex * 24;
              else if (event.key === "End") next = dayIndex * 24 + 23;
              else return;
              event.preventDefault(); setFocus(next); table.current?.querySelector<HTMLButtonElement>(`[data-cell="${next}"]`)?.focus();
            }}>{count.toLocaleString()}</button></td>;
        })}<td className="text-right font-semibold">{hours.reduce((sum, hour) => sum + (cells.get(dayIndex * 24 + hour) || 0), 0).toLocaleString()}</td></tr>)}</tbody>
        <tfoot><tr><th scope="row" className="text-left">Total</th>{hours.map((hour) => <td key={hour} className="text-center">{days.reduce((sum, _, day) => sum + (cells.get(day * 24 + hour) || 0), 0).toLocaleString()}</td>)}<td className="font-semibold text-right">{total.toLocaleString()}</td></tr></tfoot>
      </table>
    </div>
    <div className="mt-3 flex gap-2 items-center text-xs text-gray-500"><span>0</span><span aria-hidden="true" className="h-2 w-28 rounded bg-gradient-to-r from-gray-200 to-blue-800" /><span>{maximum.toLocaleString()} crashes per cell · scale changes with selection</span></div>
    <p role="status" className="mt-2 min-h-5 text-sm">{detail || `${total.toLocaleString()} ${modes[mode].toLowerCase()}. Select a cell for details.`}</p>
  </section>;
}

export function RoadUserTable({ data }: { data: RoadUserSeverity[] }) {
  const columns = ["people", "fatal", "incapacitating", "other_injury", "no_injury", "unknown"] as const;
  return <section className="mt-8 rounded-lg bg-white dark:bg-gray-800 shadow-md p-6">
    <h2 className="text-xl font-semibold mb-2">Who is affected</h2>
    <p className="text-sm text-gray-500 mb-4">People linked to crashes in the full selection. Other injuries include non-incapacitating and reported but not evident injuries. Unknown classifications remain visible.</p>
    <div className="overflow-x-auto"><table className="w-full text-sm text-right">
      <caption className="sr-only">Road users by injury classification</caption>
      <thead><tr>{["Road user", "People", "Fatal", "Incapacitating", "Other injury", "No indication", "Unknown"].map((label) => <th key={label} scope="col" className="p-2 border-b">{label}</th>)}</tr></thead>
      <tbody>{data.map((row) => <tr key={row.road_user}><th scope="row" className="p-2 text-left">{row.road_user}</th>{columns.map((column) => <td key={column} className="p-2">{row[column].toLocaleString()}</td>)}</tr>)}</tbody>
      <tfoot><tr><th scope="row" className="p-2 text-left border-t">Total</th>{columns.map((column) => <td key={column} className="p-2 border-t font-semibold">{data.reduce((sum, row) => sum + row[column], 0).toLocaleString()}</td>)}</tr></tfoot>
    </table></div>
  </section>;
}
