"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import Map, {
  Source,
  Layer,
  Marker,
  NavigationControl,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { bbox } from "@turf/turf";
import hexGrid from "@turf/hex-grid";
import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import {
  LOOP_VIEW_STATE,
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
  mode: "radius" | "polygon" | "place";
  selectedCenter: [number, number] | null;
  selectedRadius: number; // in feet
  selectedPolygon: [number, number][] | null;
  selectedPlaceGeometry: GeoJSON.Geometry | null;
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

const HEX_COLOR_STOPS = [
  "#e0f2fe",
  "#7dd3fc",
  "#38bdf8",
  "#0ea5e9",
  "#0284c7",
  "#0c4a6e",
] as const;

function buildHexColorExpression(maxCount: number) {
  const safeMax = Math.max(maxCount, 1);
  return [
    "interpolate",
    ["linear"],
    ["get", "crash_count"],
    0,
    HEX_COLOR_STOPS[0],
    safeMax * 0.15,
    HEX_COLOR_STOPS[1],
    safeMax * 0.35,
    HEX_COLOR_STOPS[2],
    safeMax * 0.55,
    HEX_COLOR_STOPS[3],
    safeMax * 0.8,
    HEX_COLOR_STOPS[4],
    safeMax,
    HEX_COLOR_STOPS[5],
  ];
}

function buildHexBins(
  areaFeature: GeoJSON.Feature | null,
  crashPoints: GeoJSON.Feature[],
  cellSizeKm: number
) {
  if (!areaFeature || crashPoints.length === 0) {
    return { collection: { type: "FeatureCollection", features: [] }, maxCount: 0 };
  }

  const bounds = bbox(areaFeature);
  const grid = hexGrid(bounds, cellSizeKm, { units: "kilometers" });
  const features: GeoJSON.Feature[] = [];
  let maxCount = 0;

  for (const hex of grid.features) {
    let crashCount = 0;
    for (const point of crashPoints) {
      if (booleanPointInPolygon(point, hex)) {
        crashCount += 1;
      }
    }

    if (crashCount === 0) {
      continue;
    }

    maxCount = Math.max(maxCount, crashCount);
    features.push({
      type: "Feature",
      geometry: hex.geometry,
      properties: { crash_count: crashCount },
    });
  }

  return {
    collection: { type: "FeatureCollection", features },
    maxCount,
  };
}

// Basemap style URL - requires NEXT_PUBLIC_PROTOMAPS_KEY env var
const PROTOMAPS_KEY = process.env.NEXT_PUBLIC_PROTOMAPS_KEY;
const BASEMAP_STYLE_URL =
  process.env.NEXT_PUBLIC_BASEMAP_URL ||
  (PROTOMAPS_KEY
    ? `https://api.protomaps.com/styles/v4/light/en.json?key=${PROTOMAPS_KEY}`
    : "");

export function LocationReportMap({
  mode,
  selectedCenter,
  selectedRadius,
  selectedPolygon,
  selectedPlaceGeometry,
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

  // Fit map bounds to selected place geometry
  useEffect(() => {
    if (!selectedPlaceGeometry || !mapRef.current) return;

    try {
      // Create a GeoJSON Feature from the geometry
      const feature = {
        type: "Feature" as const,
        geometry: selectedPlaceGeometry,
        properties: {},
      };

      // Calculate bounding box: [minLng, minLat, maxLng, maxLat]
      const bounds = bbox(feature);

      // Validate bounds are finite numbers
      if (bounds.some((coord) => !Number.isFinite(coord))) {
        console.warn("Invalid bounding box calculated from geometry");
        return;
      }

      // fitBounds expects [[minLng, minLat], [maxLng, maxLat]]
      mapRef.current.fitBounds(
        [
          [bounds[0], bounds[1]], // Southwest corner
          [bounds[2], bounds[3]], // Northeast corner
        ],
        {
          padding: 50, // Add padding around the bounds (pixels)
          duration: 1000, // Animate over 1 second
        }
      );
    } catch (error) {
      console.error("Error fitting bounds to geometry:", error);
    }
  }, [selectedPlaceGeometry]);

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
        // Complete the polygon - save a copy before clearing
        const completedPolygon = [...drawingPolygon];
        onPolygonComplete(completedPolygon);
        setDrawingPolygon([]); // Clear drawing state
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

  // Create place geometry as a GeoJSON feature
  const placeGeoJSON = useCallback(() => {
    if (!selectedPlaceGeometry) return null;

    return {
      type: "Feature" as const,
      geometry: selectedPlaceGeometry,
      properties: {},
    };
  }, [selectedPlaceGeometry]);

  // Get the selection area to display (from report data or current selection)
  const selectionAreaGeoJSON = reportData?.query_area_geojson ||
    (mode === "radius" ? circleGeoJSON() :
     mode === "polygon" ? completedPolygonGeoJSON() :
     placeGeoJSON());

  const crashPoints = useMemo(
    () => reportData?.crashes_geojson?.features ?? [],
    [reportData]
  );

  // Hex bin sizes scaled to Chicago city blocks (~100-200m per block)
  // Coarse: ~6 blocks, Mid: ~2 blocks, Fine: ~half block (intersection level)
  const coarseHexBins = useMemo(
    () => buildHexBins(selectionAreaGeoJSON ?? null, crashPoints, 0.5),
    [selectionAreaGeoJSON, crashPoints]
  );
  const midHexBins = useMemo(
    () => buildHexBins(selectionAreaGeoJSON ?? null, crashPoints, 0.15),
    [selectionAreaGeoJSON, crashPoints]
  );
  const fineHexBins = useMemo(
    () => buildHexBins(selectionAreaGeoJSON ?? null, crashPoints, 0.05),
    [selectionAreaGeoJSON, crashPoints]
  );

  const coarseHexColor = useMemo(
    () => buildHexColorExpression(coarseHexBins.maxCount),
    [coarseHexBins.maxCount]
  );
  const midHexColor = useMemo(
    () => buildHexColorExpression(midHexBins.maxCount),
    [midHexBins.maxCount]
  );
  const fineHexColor = useMemo(
    () => buildHexColorExpression(fineHexBins.maxCount),
    [fineHexBins.maxCount]
  );

  return (
    <div className="relative">
      <Map
        ref={mapRef}
        initialViewState={LOOP_VIEW_STATE}
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

        {/* Hexagonal crash density bins */}
        {coarseHexBins.collection.features.length > 0 && (
          <Source id="hex-coarse" type="geojson" data={coarseHexBins.collection}>
            <Layer
              id="hex-coarse-fill"
              type="fill"
              paint={{
                "fill-color": coarseHexColor as any,
                "fill-opacity": [
                  "interpolate",
                  ["linear"],
                  ["zoom"],
                  11,
                  0.8,
                  13.5,
                  0.8,
                  14.5,
                  0,
                ],
              }}
            />
            <Layer
              id="hex-coarse-outline"
              type="line"
              paint={{
                "line-color": "#0c4a6e",
                "line-opacity": 0.35,
                "line-width": 1,
              }}
            />
          </Source>
        )}

        {midHexBins.collection.features.length > 0 && (
          <Source id="hex-mid" type="geojson" data={midHexBins.collection}>
            <Layer
              id="hex-mid-fill"
              type="fill"
              paint={{
                "fill-color": midHexColor as any,
                "fill-opacity": [
                  "interpolate",
                  ["linear"],
                  ["zoom"],
                  14,
                  0,
                  14.5,
                  0.85,
                  16,
                  0.85,
                  17,
                  0,
                ],
              }}
            />
            <Layer
              id="hex-mid-outline"
              type="line"
              paint={{
                "line-color": "#0c4a6e",
                "line-opacity": 0.25,
                "line-width": 0.8,
              }}
            />
          </Source>
        )}

        {fineHexBins.collection.features.length > 0 && (
          <Source id="hex-fine" type="geojson" data={fineHexBins.collection}>
            <Layer
              id="hex-fine-fill"
              type="fill"
              paint={{
                "fill-color": fineHexColor as any,
                "fill-opacity": [
                  "interpolate",
                  ["linear"],
                  ["zoom"],
                  16.5,
                  0,
                  17,
                  0.9,
                  18,
                  0.9,
                  19,
                  0.5,
                ],
              }}
            />
            <Layer
              id="hex-fine-outline"
              type="line"
              paint={{
                "line-color": "#0c4a6e",
                "line-opacity": 0.2,
                "line-width": 0.6,
              }}
            />
          </Source>
        )}

        {/* Selection Area (circle or polygon) - use empty FeatureCollection when no selection */}
        <Source
          id="selection-area"
          type="geojson"
          data={selectionAreaGeoJSON || { type: "FeatureCollection", features: [] }}
        >
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
                "circle-opacity": [
                  "interpolate",
                  ["linear"],
                  ["zoom"],
                  14,
                  0,
                  15,
                  0.7,
                  16.5,
                  0.9,
                ],
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
          <div className="mb-2 pb-2 border-b border-gray-200 dark:border-gray-700 space-y-1">
            <div className="bg-gray-50 dark:bg-gray-700/30 rounded-md px-2 py-0.5">
              <div className="text-base font-bold text-gray-900 dark:text-white leading-tight">
                {formatCurrency(reportData.stats.estimated_economic_damages)}
              </div>
              <div className="text-[10px] text-gray-600 dark:text-gray-400 flex items-center gap-1">
                Est. Economic Cost
                <span className="inline-flex items-center justify-center w-3 h-3 text-[8px] font-bold bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-full" title="See methodology footnote below">i</span>
              </div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-700/30 rounded-md px-2 py-0.5">
              <div className="text-base font-bold text-gray-900 dark:text-white leading-tight">
                {formatCurrency(reportData.stats.estimated_societal_costs)}
              </div>
              <div className="text-[10px] text-gray-600 dark:text-gray-400 flex items-center gap-1">
                Est. Total Societal Cost
                <span className="inline-flex items-center justify-center w-3 h-3 text-[8px] font-bold bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-full" title="See methodology footnote below">i</span>
              </div>
            </div>
          </div>

          {/* Conditional metrics - only show if > 0 */}
          <div className="space-y-1">
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
          <div className="mt-2 pt-1.5 border-t border-gray-200 dark:border-gray-700">
            <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
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

          <div className="mt-3 pt-2 border-t border-gray-200 dark:border-gray-700">
            <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">
              Crash Density (Hex)
            </p>
            <div className="flex items-center gap-2">
              <div className="h-2 flex-1 rounded-full bg-gradient-to-r from-sky-100 via-sky-400 to-sky-950" />
              <div className="text-[10px] text-gray-500 dark:text-gray-400">Low → High</div>
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
