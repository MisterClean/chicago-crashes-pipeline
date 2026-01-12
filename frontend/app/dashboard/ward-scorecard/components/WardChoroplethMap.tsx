"use client";

import { useRef, useEffect, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

interface WardChoroplethMapProps {
  geojson: GeoJSON.FeatureCollection;
  onWardClick: (ward: number) => void;
  selectedWard: number | null;
}

// Color scale for KSI (red gradient)
function getColorForKSI(ksi: number, maxKSI: number): string {
  if (maxKSI === 0) return "#f0f0f0";
  const ratio = ksi / maxKSI;
  // Light pink to dark red
  if (ratio < 0.2) return "#fee5d9";
  if (ratio < 0.4) return "#fcae91";
  if (ratio < 0.6) return "#fb6a4a";
  if (ratio < 0.8) return "#de2d26";
  return "#a50f15";
}

export function WardChoroplethMap({
  geojson,
  onWardClick,
  selectedWard,
}: WardChoroplethMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  // Calculate max KSI for color scaling
  const maxKSI = Math.max(
    ...geojson.features.map((f) => (f.properties?.ksi as number) || 0)
  );

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
      zoom: 9.5,
    });

    map.current.on("load", () => {
      setMapLoaded(true);
    });

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  // Add/update ward layer when geojson changes
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    // Add colors to features
    const coloredFeatures = geojson.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        fillColor: getColorForKSI(feature.properties?.ksi || 0, maxKSI),
        isSelected: feature.properties?.ward === selectedWard,
      },
    }));

    const coloredGeojson = {
      type: "FeatureCollection" as const,
      features: coloredFeatures,
    };

    // Remove existing layers/sources
    if (map.current.getLayer("ward-fill")) map.current.removeLayer("ward-fill");
    if (map.current.getLayer("ward-outline")) map.current.removeLayer("ward-outline");
    if (map.current.getLayer("ward-selected")) map.current.removeLayer("ward-selected");
    if (map.current.getLayer("ward-labels")) map.current.removeLayer("ward-labels");
    if (map.current.getSource("wards")) map.current.removeSource("wards");

    // Add source
    map.current.addSource("wards", {
      type: "geojson",
      data: coloredGeojson,
    });

    // Fill layer
    map.current.addLayer({
      id: "ward-fill",
      type: "fill",
      source: "wards",
      paint: {
        "fill-color": ["get", "fillColor"],
        "fill-opacity": 0.7,
      },
    });

    // Outline layer
    map.current.addLayer({
      id: "ward-outline",
      type: "line",
      source: "wards",
      paint: {
        "line-color": "#333",
        "line-width": 1,
      },
    });

    // Selected ward highlight
    map.current.addLayer({
      id: "ward-selected",
      type: "line",
      source: "wards",
      filter: ["==", ["get", "isSelected"], true],
      paint: {
        "line-color": "#2563eb",
        "line-width": 3,
      },
    });

    // Ward labels
    map.current.addLayer({
      id: "ward-labels",
      type: "symbol",
      source: "wards",
      layout: {
        "text-field": ["to-string", ["get", "ward"]],
        "text-size": 12,
        "text-font": ["Open Sans Regular"],
      },
      paint: {
        "text-color": "#000",
        "text-halo-color": "#fff",
        "text-halo-width": 1,
      },
    });

    // Click handler
    map.current.on("click", "ward-fill", (e) => {
      if (e.features && e.features[0]) {
        const ward = e.features[0].properties?.ward;
        if (ward) onWardClick(ward);
      }
    });

    // Hover cursor
    map.current.on("mouseenter", "ward-fill", () => {
      if (map.current) map.current.getCanvas().style.cursor = "pointer";
    });
    map.current.on("mouseleave", "ward-fill", () => {
      if (map.current) map.current.getCanvas().style.cursor = "";
    });

    // Popup on hover
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
    });

    map.current.on("mousemove", "ward-fill", (e) => {
      if (!e.features || !e.features[0]) return;
      const props = e.features[0].properties;
      popup
        .setLngLat(e.lngLat)
        .setHTML(
          `<div class="p-2">
            <strong>Ward ${props?.ward}</strong><br/>
            KSI: ${props?.ksi || 0}
          </div>`
        )
        .addTo(map.current!);
    });

    map.current.on("mouseleave", "ward-fill", () => {
      popup.remove();
    });
  }, [geojson, mapLoaded, selectedWard, maxKSI, onWardClick]);

  return (
    <div className="relative">
      <div ref={mapContainer} className="h-[400px] rounded-lg" />
      {/* Legend */}
      <div className="absolute bottom-4 right-4 bg-white dark:bg-gray-800 rounded-lg shadow-md p-3">
        <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
          KSI Count
        </p>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 rounded" style={{ backgroundColor: "#fee5d9" }} />
          <div className="w-4 h-4 rounded" style={{ backgroundColor: "#fcae91" }} />
          <div className="w-4 h-4 rounded" style={{ backgroundColor: "#fb6a4a" }} />
          <div className="w-4 h-4 rounded" style={{ backgroundColor: "#de2d26" }} />
          <div className="w-4 h-4 rounded" style={{ backgroundColor: "#a50f15" }} />
        </div>
        <div className="flex justify-between text-[10px] text-gray-500 mt-1">
          <span>Low</span>
          <span>High</span>
        </div>
      </div>
    </div>
  );
}
