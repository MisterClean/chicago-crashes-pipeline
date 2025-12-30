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
  DEFAULT_VIEW_STATE,
  MIN_ZOOM,
  MAX_ZOOM,
  MAP_METRICS,
  type MapMetric,
} from "@/lib/mapStyles";
import { fetchCrashesGeoJSON, type CrashGeoJSON, type CrashFeature } from "@/lib/api";

interface CrashMapProps {
  startDate?: string;
  endDate?: string;
}

// Simple basemap style - uses Protomaps free tiles
// In production, this would use self-hosted PMTiles
const BASEMAP_STYLE_URL =
  process.env.NEXT_PUBLIC_BASEMAP_URL ||
  "https://api.protomaps.com/styles/v4/light/en.json?key=1003762e067defa9";

export function CrashMap({ startDate, endDate }: CrashMapProps) {
  const [crashes, setCrashes] = useState<CrashGeoJSON | null>(null);
  const [selectedCrash, setSelectedCrash] = useState<CrashFeature | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMetric, setSelectedMetric] = useState<MapMetric>("severity");
  const [visibleCategories, setVisibleCategories] = useState<Set<string>>(new Set());

  const currentMetricConfig = MAP_METRICS.find((m) => m.id === selectedMetric) || MAP_METRICS[0];

  // Reset visible categories when metric changes
  useEffect(() => {
    setVisibleCategories(new Set(currentMetricConfig.legend.map((item) => item.label)));
  }, [currentMetricConfig]);

  const toggleCategory = (label: string) => {
    setVisibleCategories((prev) => {
      const next = new Set(prev);
      if (next.has(label)) {
        next.delete(label);
      } else {
        next.add(label);
      }
      return next;
    });
  };

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
      <div className="h-[600px] bg-gray-100 dark:bg-gray-700 rounded animate-pulse flex items-center justify-center">
        <span className="text-gray-500">Loading crash data...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-[600px] bg-red-50 dark:bg-red-900/20 rounded flex items-center justify-center">
        <span className="text-red-600 dark:text-red-400">Error: {error}</span>
      </div>
    );
  }

  return (
    <div className="relative">
      <Map
        initialViewState={DEFAULT_VIEW_STATE}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        style={{ width: "100%", height: "600px", borderRadius: "8px" }}
        mapStyle={BASEMAP_STYLE_URL}
        interactiveLayerIds={["crashes-circle"]}
        onClick={handleClick}
      >
        <NavigationControl position="top-right" />

        {crashes && (
          <Source id="crashes" type="geojson" data={crashes}>
            <Layer
              id="crashes-circle"
              type="circle"
              filter={currentMetricConfig.getFilterExpression(visibleCategories) as never}
              paint={{
                "circle-radius": 5,
                "circle-color": currentMetricConfig.colorExpression as unknown as string,
                "circle-opacity": 0.7,
                "circle-stroke-width": 1,
                "circle-stroke-color": "#ffffff",
              }}
            />
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

      {/* Metric Selector */}
      <div className="absolute top-4 right-16 bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm rounded-lg shadow-md">
        <select
          value={selectedMetric}
          onChange={(e) => setSelectedMetric(e.target.value as MapMetric)}
          className="px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-transparent border-0 focus:ring-2 focus:ring-blue-500 rounded-lg cursor-pointer"
        >
          {MAP_METRICS.map((metric) => (
            <option key={metric.id} value={metric.id}>
              {metric.label}
            </option>
          ))}
        </select>
      </div>

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm rounded-lg p-3 shadow-md">
        <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
          {currentMetricConfig.label}
        </p>
        <div className="space-y-1">
          {currentMetricConfig.legend.map((item) => {
            const isVisible = visibleCategories.has(item.label);
            return (
              <button
                key={item.label}
                onClick={() => toggleCategory(item.label)}
                className={`flex items-center gap-2 w-full text-left transition-opacity ${
                  isVisible ? "opacity-100" : "opacity-40"
                }`}
              >
                <span
                  className="w-3 h-3 rounded-full border-2 transition-colors"
                  style={{
                    backgroundColor: isVisible ? item.color : "transparent",
                    borderColor: item.color,
                  }}
                />
                <span className="text-xs text-gray-600 dark:text-gray-400">
                  {item.label}
                </span>
              </button>
            );
          })}
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
