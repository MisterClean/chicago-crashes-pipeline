"use client";

import { useState, useCallback, useEffect } from "react";
import Map, {
  Source,
  Layer,
  NavigationControl,
  Popup,
  type MapLayerMouseEvent,
} from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  CHICAGO_BOUNDS,
  DEFAULT_VIEW_STATE,
  crashCircleLayer,
  crashHeatmapLayer,
  SEVERITY_LEGEND,
} from "@/lib/mapStyles";
import { fetchCrashesGeoJSON, type CrashGeoJSON, type CrashFeature } from "@/lib/api";

interface CrashMapProps {
  startDate?: string;
  endDate?: string;
}

// PMTiles style for Chicago basemap
const mapStyle = {
  version: 8 as const,
  name: "Chicago Basemap",
  sources: {
    basemap: {
      type: "vector" as const,
      url: "pmtiles:///tiles/chicago-basemap.pmtiles",
    },
  },
  layers: [
    {
      id: "background",
      type: "background" as const,
      paint: { "background-color": "#f0f0f0" },
    },
    {
      id: "water",
      type: "fill" as const,
      source: "basemap",
      "source-layer": "water",
      paint: { "fill-color": "#b3ddf2" },
    },
    {
      id: "landuse-park",
      type: "fill" as const,
      source: "basemap",
      "source-layer": "landuse",
      filter: ["==", ["get", "class"], "park"],
      paint: { "fill-color": "#c8e6c9" },
    },
    {
      id: "roads-minor",
      type: "line" as const,
      source: "basemap",
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["minor", "service"]]],
      paint: {
        "line-color": "#e0e0e0",
        "line-width": 1,
      },
    },
    {
      id: "roads-major",
      type: "line" as const,
      source: "basemap",
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["primary", "secondary", "tertiary"]]],
      paint: {
        "line-color": "#ffffff",
        "line-width": 2,
      },
    },
    {
      id: "roads-highway",
      type: "line" as const,
      source: "basemap",
      "source-layer": "transportation",
      filter: ["==", ["get", "class"], "motorway"],
      paint: {
        "line-color": "#ffd54f",
        "line-width": 3,
      },
    },
    {
      id: "boundaries",
      type: "line" as const,
      source: "basemap",
      "source-layer": "boundary",
      paint: {
        "line-color": "#999",
        "line-width": 1,
        "line-dasharray": [2, 2],
      },
    },
    {
      id: "labels",
      type: "symbol" as const,
      source: "basemap",
      "source-layer": "place",
      layout: {
        "text-field": ["get", "name"],
        "text-size": 12,
      },
      paint: {
        "text-color": "#333",
        "text-halo-color": "#fff",
        "text-halo-width": 1,
      },
    },
  ],
};

export function CrashMap({ startDate, endDate }: CrashMapProps) {
  const [crashes, setCrashes] = useState<CrashGeoJSON | null>(null);
  const [selectedCrash, setSelectedCrash] = useState<CrashFeature | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch crash data
  useEffect(() => {
    setLoading(true);
    setError(null);

    fetchCrashesGeoJSON({
      start_date: startDate,
      end_date: endDate,
      limit: 10000,
    })
      .then(setCrashes)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  const handleClick = useCallback((event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (feature && feature.geometry.type === "Point") {
      setSelectedCrash(feature as unknown as CrashFeature);
    }
  }, []);

  if (loading) {
    return (
      <div className="h-96 bg-gray-100 dark:bg-gray-700 rounded animate-pulse flex items-center justify-center">
        <span className="text-gray-500">Loading crash data...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-96 bg-red-50 dark:bg-red-900/20 rounded flex items-center justify-center">
        <span className="text-red-600 dark:text-red-400">Error: {error}</span>
      </div>
    );
  }

  return (
    <div className="relative">
      <Map
        initialViewState={DEFAULT_VIEW_STATE}
        maxBounds={CHICAGO_BOUNDS}
        style={{ width: "100%", height: "384px", borderRadius: "8px" }}
        mapStyle={mapStyle}
        interactiveLayerIds={["crashes-circle"]}
        onClick={handleClick}
      >
        <NavigationControl position="top-right" />

        {crashes && (
          <Source id="crashes" type="geojson" data={crashes}>
            <Layer {...crashHeatmapLayer} />
            <Layer {...crashCircleLayer} />
          </Source>
        )}

        {selectedCrash && selectedCrash.geometry.type === "Point" && (
          <Popup
            longitude={selectedCrash.geometry.coordinates[0]}
            latitude={selectedCrash.geometry.coordinates[1]}
            onClose={() => setSelectedCrash(null)}
            closeOnClick={false}
            offset={10}
          >
            <CrashPopup crash={selectedCrash} />
          </Popup>
        )}
      </Map>

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm rounded-lg p-3 shadow-md">
        <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
          Severity
        </p>
        <div className="space-y-1">
          {SEVERITY_LEGEND.map((item) => (
            <div key={item.label} className="flex items-center gap-2">
              <span
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-xs text-gray-600 dark:text-gray-400">
                {item.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Crash count */}
      {crashes && (
        <div className="absolute top-4 left-4 bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {crashes.features.length.toLocaleString()} crashes
          </span>
        </div>
      )}
    </div>
  );
}

function CrashPopup({ crash }: { crash: CrashFeature }) {
  const { properties } = crash;
  const date = new Date(properties.crash_date);

  return (
    <div className="min-w-[200px]">
      <p className="font-semibold text-gray-900">
        {date.toLocaleDateString("en-US", {
          year: "numeric",
          month: "short",
          day: "numeric",
        })}
      </p>
      {properties.street_name && (
        <p className="text-sm text-gray-600">{properties.street_name}</p>
      )}
      <div className="mt-2 space-y-1 text-sm">
        {properties.injuries_fatal > 0 && (
          <p className="text-red-600 font-medium">
            {properties.injuries_fatal} fatalities
          </p>
        )}
        {properties.injuries_incapacitating > 0 && (
          <p className="text-orange-600">
            {properties.injuries_incapacitating} incapacitating injuries
          </p>
        )}
        {properties.injuries_total > 0 && (
          <p className="text-yellow-600">
            {properties.injuries_total} total injuries
          </p>
        )}
        {properties.hit_and_run_i && (
          <p className="text-purple-600 font-medium">Hit and Run</p>
        )}
        {properties.crash_type && (
          <p className="text-gray-500">{properties.crash_type}</p>
        )}
      </div>
    </div>
  );
}
