"use client";

import { useRef, useEffect, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { CrashGeoJSON } from "@/lib/api";

interface WardDetailMapProps {
  crashesGeojson: CrashGeoJSON;
  boundaryGeojson: GeoJSON.Feature;
}

export function WardDetailMap({
  crashesGeojson,
  boundaryGeojson,
}: WardDetailMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  useEffect(() => {
    if (!mapContainer.current || map.current) return;

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "&copy; OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
          },
        ],
      },
      center: [-87.65, 41.85],
      zoom: 11,
    });

    map.current.on("load", () => {
      setMapLoaded(true);
    });

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  // Add layers when data changes
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    // Remove existing layers/sources
    if (map.current.getLayer("crashes")) map.current.removeLayer("crashes");
    if (map.current.getLayer("crashes-fatal")) map.current.removeLayer("crashes-fatal");
    if (map.current.getLayer("boundary-fill")) map.current.removeLayer("boundary-fill");
    if (map.current.getLayer("boundary-line")) map.current.removeLayer("boundary-line");
    if (map.current.getSource("crashes")) map.current.removeSource("crashes");
    if (map.current.getSource("boundary")) map.current.removeSource("boundary");

    // Add boundary source and layers
    if (boundaryGeojson.geometry) {
      map.current.addSource("boundary", {
        type: "geojson",
        data: boundaryGeojson,
      });

      map.current.addLayer({
        id: "boundary-fill",
        type: "fill",
        source: "boundary",
        paint: {
          "fill-color": "#3b82f6",
          "fill-opacity": 0.1,
        },
      });

      map.current.addLayer({
        id: "boundary-line",
        type: "line",
        source: "boundary",
        paint: {
          "line-color": "#2563eb",
          "line-width": 3,
        },
      });

      // Fit to boundary
      const bounds = new maplibregl.LngLatBounds();
      const coords = boundaryGeojson.geometry.type === "Polygon"
        ? boundaryGeojson.geometry.coordinates[0]
        : boundaryGeojson.geometry.type === "MultiPolygon"
        ? boundaryGeojson.geometry.coordinates.flat(2)
        : [];

      (coords as [number, number][]).forEach((coord) => {
        bounds.extend(coord);
      });

      map.current.fitBounds(bounds, { padding: 40 });
    }

    // Add crashes source and layers
    map.current.addSource("crashes", {
      type: "geojson",
      data: crashesGeojson,
    });

    // Non-fatal crashes (small dots)
    map.current.addLayer({
      id: "crashes",
      type: "circle",
      source: "crashes",
      filter: ["==", ["get", "injuries_fatal"], 0],
      paint: {
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          9, 2,
          14, 4,
        ],
        "circle-color": [
          "case",
          [">", ["get", "injuries_incapacitating"], 0],
          "#f59e0b", // Amber for serious
          "#6b7280", // Gray for other
        ],
        "circle-opacity": 0.6,
      },
    });

    // Fatal crashes (larger red dots)
    map.current.addLayer({
      id: "crashes-fatal",
      type: "circle",
      source: "crashes",
      filter: [">", ["get", "injuries_fatal"], 0],
      paint: {
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          9, 5,
          14, 10,
        ],
        "circle-color": "#dc2626",
        "circle-opacity": 0.9,
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
      },
    });

    // Popup on click
    const popup = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: true,
    });

    const handleClick = (e: maplibregl.MapLayerMouseEvent) => {
      if (!e.features || !e.features[0]) return;
      const props = e.features[0].properties;
      const coords = (e.features[0].geometry as GeoJSON.Point).coordinates;

      popup
        .setLngLat(coords as [number, number])
        .setHTML(
          `<div class="p-2 text-sm">
            <strong>Crash ${props?.crash_record_id}</strong><br/>
            Date: ${props?.crash_date?.split("T")[0] || "Unknown"}<br/>
            Severity: ${props?.most_severe_injury || "Unknown"}<br/>
            Fatal: ${props?.injuries_fatal || 0}<br/>
            Serious: ${props?.injuries_incapacitating || 0}
          </div>`
        )
        .addTo(map.current!);
    };

    map.current.on("click", "crashes", handleClick);
    map.current.on("click", "crashes-fatal", handleClick);

    // Hover cursor
    map.current.on("mouseenter", "crashes", () => {
      if (map.current) map.current.getCanvas().style.cursor = "pointer";
    });
    map.current.on("mouseleave", "crashes", () => {
      if (map.current) map.current.getCanvas().style.cursor = "";
    });
    map.current.on("mouseenter", "crashes-fatal", () => {
      if (map.current) map.current.getCanvas().style.cursor = "pointer";
    });
    map.current.on("mouseleave", "crashes-fatal", () => {
      if (map.current) map.current.getCanvas().style.cursor = "";
    });
  }, [crashesGeojson, boundaryGeojson, mapLoaded]);

  return (
    <div className="relative">
      <div ref={mapContainer} className="h-[400px] rounded-lg" />
      {/* Legend */}
      <div className="absolute bottom-4 right-4 bg-white dark:bg-gray-800 rounded-lg shadow-md p-3">
        <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
          Crash Severity
        </p>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-red-600 border-2 border-white" />
            <span className="text-xs text-gray-600 dark:text-gray-400">Fatal</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-amber-500" />
            <span className="text-xs text-gray-600 dark:text-gray-400">Serious Injury</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-gray-500" />
            <span className="text-xs text-gray-600 dark:text-gray-400">Other</span>
          </div>
        </div>
      </div>
    </div>
  );
}
