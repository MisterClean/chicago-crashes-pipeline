"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import Map, {
  Source,
  Layer,
  Marker,
  NavigationControl,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  DEFAULT_VIEW_STATE,
  SEVERITY_LEGEND,
  MIN_ZOOM,
  MAX_ZOOM,
} from "@/lib/mapStyles";
import type { LocationReportResponse } from "@/lib/api";

// Helper to generate circle polygon from center and radius
function generateCirclePolygon(
  center: [number, number],
  radiusKm: number,
  steps: number = 64
): GeoJSON.Feature<GeoJSON.Polygon> {
  const coordinates: [number, number][] = [];
  for (let i = 0; i < steps; i++) {
    const angle = (i / steps) * 2 * Math.PI;
    // Approximate conversion: 1 degree latitude = 111km, 1 degree longitude varies by latitude
    const latOffset = (radiusKm / 111) * Math.sin(angle);
    const lngOffset = (radiusKm / (111 * Math.cos((center[1] * Math.PI) / 180))) * Math.cos(angle);
    coordinates.push([center[0] + lngOffset, center[1] + latOffset]);
  }
  coordinates.push(coordinates[0]); // Close the ring

  return {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [coordinates],
    },
    properties: {},
  };
}

interface LocationReportMapProps {
  mode: "radius" | "polygon";
  selectedCenter: [number, number] | null;
  selectedRadius: number; // in feet
  selectedPolygon: [number, number][] | null;
  onCenterSelect: (center: [number, number]) => void;
  onPolygonComplete: (polygon: [number, number][]) => void;
  reportData: LocationReportResponse | null;
  startDate: string;
  endDate: string;
}

// Format date range for display
function formatDateRange(startDate: string, endDate: string): string {
  if (!startDate && !endDate) return "All time";
  if (!startDate) return `Through ${formatDate(endDate)}`;
  if (!endDate) return `From ${formatDate(startDate)}`;
  return `${formatDate(startDate)} – ${formatDate(endDate)}`;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr + "T00:00:00");
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// Format currency in abbreviated form ($1.2M, $45.3K, etc.)
function formatCurrency(value: number | undefined | null): string {
  if (value === undefined || value === null) return "$0";
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}

const BASEMAP_STYLE_URL =
  process.env.NEXT_PUBLIC_BASEMAP_URL ||
  "https://api.protomaps.com/styles/v4/light/en.json?key=1003762e067defa9";

export function LocationReportMap({
  mode,
  selectedCenter,
  selectedRadius,
  selectedPolygon,
  onCenterSelect,
  onPolygonComplete,
  reportData,
  startDate,
  endDate,
}: LocationReportMapProps) {
  const mapRef = useRef<MapRef>(null);

  // Polygon drawing state
  const [drawingPolygon, setDrawingPolygon] = useState<[number, number][]>([]);
  const [isDrawing, setIsDrawing] = useState(false);

  // Reset drawing when mode changes
  useEffect(() => {
    setDrawingPolygon([]);
    setIsDrawing(false);
  }, [mode]);

  // Generate circle GeoJSON from center and radius
  const circleGeoJSON = useCallback(() => {
    if (!selectedCenter) return null;

    // Convert feet to kilometers (1 foot = 0.0003048 km)
    const radiusKm = selectedRadius * 0.0003048;

    return generateCirclePolygon(selectedCenter, radiusKm);
  }, [selectedCenter, selectedRadius]);

  // Handle map click
  const handleMapClick = useCallback(
    (event: MapLayerMouseEvent) => {
      const { lng, lat } = event.lngLat;

      if (mode === "radius") {
        onCenterSelect([lng, lat]);
      } else {
        // Polygon mode
        const newPoint: [number, number] = [lng, lat];
        setDrawingPolygon((prev) => [...prev, newPoint]);
        setIsDrawing(true);
      }
    },
    [mode, onCenterSelect]
  );

  // Handle double-click to complete polygon
  const handleMapDblClick = useCallback(
    (event: MapLayerMouseEvent) => {
      if (mode === "polygon" && drawingPolygon.length >= 3) {
        event.preventDefault();
        // Complete the polygon
        onPolygonComplete(drawingPolygon);
        setIsDrawing(false);
      }
    },
    [mode, drawingPolygon, onPolygonComplete]
  );

  // Generate polygon GeoJSON for drawing preview
  const drawingPolygonGeoJSON = useCallback(() => {
    if (drawingPolygon.length < 2) return null;

    if (drawingPolygon.length === 2) {
      // Just a line
      return {
        type: "Feature" as const,
        geometry: {
          type: "LineString" as const,
          coordinates: drawingPolygon,
        },
        properties: {},
      };
    }

    // Polygon preview (close it)
    return {
      type: "Feature" as const,
      geometry: {
        type: "Polygon" as const,
        coordinates: [[...drawingPolygon, drawingPolygon[0]]],
      },
      properties: {},
    };
  }, [drawingPolygon]);

  // Generate completed polygon GeoJSON
  const completedPolygonGeoJSON = useCallback(() => {
    if (!selectedPolygon || selectedPolygon.length < 3) return null;

    return {
      type: "Feature" as const,
      geometry: {
        type: "Polygon" as const,
        coordinates: [[...selectedPolygon, selectedPolygon[0]]],
      },
      properties: {},
    };
  }, [selectedPolygon]);

  // Get the selection area to display (from report data or current selection)
  const selectionAreaGeoJSON = reportData?.query_area_geojson ||
    (mode === "radius" ? circleGeoJSON() : completedPolygonGeoJSON());

  return (
    <div className="relative">
      <Map
        ref={mapRef}
        initialViewState={DEFAULT_VIEW_STATE}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        style={{ width: "100%", height: "600px", borderRadius: "8px" }}
        mapStyle={BASEMAP_STYLE_URL}
        onClick={handleMapClick}
        onDblClick={handleMapDblClick}
        doubleClickZoom={mode !== "polygon"}
        cursor={mode === "polygon" && isDrawing ? "crosshair" : "pointer"}
      >
        <NavigationControl position="top-right" />

        {/* Selection Area (circle or polygon) */}
        {selectionAreaGeoJSON && (
          <Source id="selection-area" type="geojson" data={selectionAreaGeoJSON}>
            <Layer
              id="selection-area-fill"
              type="fill"
              paint={{
                "fill-color": "#3b82f6",
                "fill-opacity": 0.15,
              }}
            />
            <Layer
              id="selection-area-outline"
              type="line"
              paint={{
                "line-color": "#3b82f6",
                "line-width": 2,
                "line-dasharray": [2, 2],
              }}
            />
          </Source>
        )}

        {/* Drawing preview for polygon */}
        {mode === "polygon" && isDrawing && drawingPolygon.length >= 2 && (
          <Source
            id="drawing-preview"
            type="geojson"
            data={drawingPolygonGeoJSON()!}
          >
            <Layer
              id="drawing-preview-fill"
              type="fill"
              paint={{
                "fill-color": "#3b82f6",
                "fill-opacity": 0.1,
              }}
            />
            <Layer
              id="drawing-preview-line"
              type="line"
              paint={{
                "line-color": "#3b82f6",
                "line-width": 2,
              }}
            />
          </Source>
        )}

        {/* Drawing vertices */}
        {mode === "polygon" && isDrawing && drawingPolygon.map((point, index) => (
          <Marker
            key={index}
            longitude={point[0]}
            latitude={point[1]}
            anchor="center"
          >
            <div className="w-3 h-3 bg-blue-600 rounded-full border-2 border-white shadow-md" />
          </Marker>
        ))}

        {/* Center marker for radius mode */}
        {mode === "radius" && selectedCenter && (
          <Marker
            longitude={selectedCenter[0]}
            latitude={selectedCenter[1]}
            anchor="center"
          >
            <div className="w-4 h-4 bg-blue-600 rounded-full border-2 border-white shadow-lg" />
          </Marker>
        )}

        {/* Crash points from report */}
        {reportData?.crashes_geojson && (
          <Source id="crashes" type="geojson" data={reportData.crashes_geojson}>
            <Layer
              id="crashes-circle"
              type="circle"
              paint={{
                "circle-radius": 5,
                "circle-color": [
                  "case",
                  [">", ["get", "injuries_fatal"], 0],
                  "#dc2626",
                  [">", ["get", "injuries_incapacitating"], 0],
                  "#ea580c",
                  [">", ["get", "injuries_total"], 0],
                  "#eab308",
                  "#22c55e",
                ],
                "circle-opacity": 0.8,
                "circle-stroke-width": 1,
                "circle-stroke-color": "#ffffff",
              }}
            />
          </Source>
        )}
      </Map>

      {/* Stats Side Panel */}
      {reportData && (
        <div className="absolute top-4 left-4 bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-lg shadow-lg p-4 max-w-[220px]">
          {/* Date Range */}
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-3 pb-2 border-b border-gray-200 dark:border-gray-700">
            {formatDateRange(startDate, endDate)}
          </div>

          {/* Total Crashes - Always show */}
          <div className="mb-3">
            <div className="text-3xl font-bold text-gray-900 dark:text-white">
              {reportData.stats.total_crashes.toLocaleString()}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400">Total Crashes</div>
          </div>

          {/* Cost Estimates */}
          <div className="mb-3 pb-3 border-b border-gray-200 dark:border-gray-700 space-y-2">
            <div className="bg-gray-50 dark:bg-gray-700/30 rounded-md px-2 py-1.5">
              <div className="text-lg font-bold text-gray-900 dark:text-white">
                {formatCurrency(reportData.stats.estimated_economic_damages)}
              </div>
              <div className="text-[10px] text-gray-600 dark:text-gray-400 flex items-center gap-1">
                Est. Economic Cost
                <span className="inline-flex items-center justify-center w-3 h-3 text-[8px] font-bold bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-full" title="See methodology footnote below">i</span>
              </div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-700/30 rounded-md px-2 py-1.5">
              <div className="text-lg font-bold text-gray-900 dark:text-white">
                {formatCurrency(reportData.stats.estimated_societal_costs)}
              </div>
              <div className="text-[10px] text-gray-600 dark:text-gray-400 flex items-center gap-1">
                Est. Total Societal Cost
                <span className="inline-flex items-center justify-center w-3 h-3 text-[8px] font-bold bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-full" title="See methodology footnote below">i</span>
              </div>
            </div>
          </div>

          {/* Conditional metrics - only show if > 0 */}
          <div className="space-y-2">
            {reportData.stats.total_fatalities > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 dark:text-gray-400">Fatalities</span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">{reportData.stats.total_fatalities.toLocaleString()}</span>
              </div>
            )}
            {reportData.stats.incapacitating_injuries > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 dark:text-gray-400">Incapacitating</span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">{reportData.stats.incapacitating_injuries.toLocaleString()}</span>
              </div>
            )}
            {reportData.stats.total_injuries > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 dark:text-gray-400">Total Injuries</span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">{reportData.stats.total_injuries.toLocaleString()}</span>
              </div>
            )}
            {reportData.stats.pedestrians_involved > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 dark:text-gray-400">Pedestrians</span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">{reportData.stats.pedestrians_involved.toLocaleString()}</span>
              </div>
            )}
            {reportData.stats.cyclists_involved > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 dark:text-gray-400">Cyclists</span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">{reportData.stats.cyclists_involved.toLocaleString()}</span>
              </div>
            )}
            {reportData.stats.hit_and_run_count > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 dark:text-gray-400">Hit & Run</span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">{reportData.stats.hit_and_run_count.toLocaleString()}</span>
              </div>
            )}
            {reportData.stats.crashes_with_injuries > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 dark:text-gray-400">With Injuries</span>
                <span className="text-lg font-bold text-gray-900 dark:text-white">{reportData.stats.crashes_with_injuries.toLocaleString()}</span>
              </div>
            )}
          </div>

          {/* Severity Legend */}
          <div className="mt-3 pt-2 border-t border-gray-200 dark:border-gray-700">
            <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
              Severity
            </p>
            <div className="space-y-1">
              {SEVERITY_LEGEND.map((item) => (
                <div key={item.label} className="flex items-center gap-2">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="text-xs text-gray-600 dark:text-gray-400">
                    {item.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Drawing instructions overlay */}
      {mode === "polygon" && isDrawing && (
        <div className="absolute top-4 left-1/2 transform -translate-x-1/2 bg-blue-600 text-white px-4 py-2 rounded-lg shadow-md">
          <span className="text-sm font-medium">
            {drawingPolygon.length < 3
              ? `Click to add vertices (${3 - drawingPolygon.length} more needed)`
              : "Double-click to complete polygon"}
          </span>
        </div>
      )}
    </div>
  );
}
