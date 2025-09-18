---
title: Data Catalog & Schema Reference
sidebar_position: 1
description: Up-to-date table definitions, relationships, and query examples for the Chicago Crash Data pipeline warehouse.
---

> **Validation tip:** Confirm schema details against your target warehouse before running analyses; the sample queries below can help spot drift.

## Pipeline Tables at a Glance

| Table | Source Dataset | Primary Key | Schema Notes |
| --- | --- | --- | --- |
| `public.crashes` | Traffic Crashes – Crashes (`85ca-t3if`) | `crash_record_id` | Retains portal field names, adds PostGIS geometry and aggregated injury statistics. |
| `public.crash_people` | Traffic Crashes – People (`u6pd-qa9d`) | (`crash_record_id`, `person_id`) | Captures occupants and vulnerable road users; widened driver fields and vehicle linkage via `vehicle_id`. |
| `public.crash_vehicles` | Traffic Crashes – Vehicles (`68nd-jvt3`) | `crash_unit_id` | Vehicle/unit roster with normalized descriptors and hazmat flags; indexes support analytics. |
| `public.vision_zero_fatalities` | Vision Zero Traffic Fatalities (`gzaz-isa6`) | `person_id` | Fatality subset with pipeline-restored RD numbers and spatial geometry. |

*Use `SELECT COUNT(*) FROM <table>` to inspect current volumes when capacity planning.*

## Entity Relationships

```
crashes.crash_record_id (PK)
├── crash_people.crash_record_id (FK)
└── crash_vehicles.crash_record_id (FK)

crash_vehicles.vehicle_id
└── crash_people.vehicle_id (mul)

vision_zero_fatalities.person_id (PK)
└── crash_people.person_id (subset)
```

- All spatial analysis should prefer the `geometry` column on `crashes` and `vision_zero_fatalities` instead of lat/long floats.
- Pedestrians and cyclists exist both as vehicle "units" and as people records; downstream analytics should filter on `unit_type`/`person_type` rather than assuming motor vehicles only.

## Source ➜ Warehouse Mapping

| Warehouse Table | Source Identifier | Transform Highlights |
| --- | --- | --- |
| `crashes` | `85ca-t3if` | Column names normalized to snake_case; numeric indicators converted to integers; `geometry` populated via `ST_SetSRID(ST_Point(longitude, latitude), 4326)`; ETL timestamps stored in `created_at`/`updated_at`. |
| `crash_people` | `u6pd-qa9d` | Composite key maintained, driver-centric fields widened (`drivers_license_class`, `ems_unit`); includes `driver_action` and `driver_vision` fields from recent portal schema updates. |
| `crash_vehicles` | `68nd-jvt3` | Vehicle descriptors widened; hazmat flag columns trimmed to core indicators; indexes on `vehicle_type`, `vehicle_year`, and `make` added for analytics. |
| `vision_zero_fatalities` | `gzaz-isa6` | `rd_no` retained for linkage despite portal deprecation; coordinates normalized; pipeline geometry built for spatial joins. |

## Table-Level Detail

### Crashes (`public.crashes`)

- **Primary key:** `crash_record_id`
- **Indexes:** `crash_date`, `beat_of_occurrence`, `injuries_total`, `injuries_fatal`, `hit_and_run_i`, `GIST(geometry)`, composite `(crash_date, latitude, longitude)`.
- **Refresh cadence:** Defined by the incremental jobs in `scheduled_jobs`; confirm the active window before reporting.
- **Spatial completeness:** Latitude/longitude can be null on a small subset of records; `geometry` is omitted when coordinates are missing.

**Key analytic fields**
- Event timing: `crash_date`, `date_police_notified`, `crash_date_est_i` (indicator when reported after the fact).
- Location context: `street_no`, `street_direction`, `street_name`, optional second street fields, `beat_of_occurrence`.
- Crash descriptors: `crash_type`, `prim_contributory_cause`, `sec_contributory_cause`, `traffic_control_device`, `device_condition`, `weather_condition`, `lighting_condition`.
- Injury rollups: `injuries_total`, `injuries_fatal`, `injuries_incapacitating`, `injuries_non_incapacitating`, `injuries_reported_not_evident`, `injuries_no_indication`, `injuries_unknown`, `most_severe_injury`.
- Operational flags: `hit_and_run_i`, `dooring_i`, `intersection_related_i`, `not_right_of_way_i`, `work_zone_i`, `workers_present_i`, `photos_taken_i`, `statements_taken_i`.
- Roadway conditions: `posted_speed_limit`, `lane_cnt`, `alignment`, `roadway_surface_cond`, `road_defect`, `damage`.
- Derived spatial: `geometry` (`POINT`, SRID 4326).
- Pipeline metadata: `created_at`, `updated_at` track ingestion not crash occurrence.

> For a full field-by-field reference, consult the [Traffic Crashes data dictionary](https://dev.socrata.com/foundry/data.cityofchicago.org/85ca-t3if). Column names in the warehouse map directly to the lowercase API field names.

### People (`public.crash_people`)

- **Primary key:** (`crash_record_id`, `person_id`)
- **Indexes:** `person_type`, `injury_classification`, `age`.
- **Common roles:** DRIVER, PASSENGER, BICYCLE, PEDESTRIAN, NON-MOTOR VEHICLE, NON-CONTACT VEHICLE.
- **Data gaps:** `crash_date` is frequently null from the upstream portal; rely on the parent crash record for event timing.

**Key analytic fields**
- Demographics: `age`, `sex`.
- Classification: `person_type`, `injury_classification`, `physical_condition`.
- Vehicle linkage: `vehicle_id` (ties back to `crash_vehicles.vehicle_id`).
- Safety indicators: `safety_equipment`, `airbag_deployed`, `ejection`, `cell_phone_use`, `bac_result`, `bac_result_value`.
- EMS routing: `hospital`, `ems_agency`, `ems_unit`.
- Driver focus: `drivers_license_state`, `drivers_license_class`, `driver_action`, `driver_vision`.
- Pedestrian/cyclist context: `pedpedal_action`, `pedpedal_visibility`, `pedpedal_location`.
- Injury body area flags: `area_00_i` … `area_12_i` (Y/N series from SR1050 form indicating injury zones; see SR1050 manual for code meanings).
- Pipeline metadata: `created_at`, `updated_at`.

### Vehicles (`public.crash_vehicles`)

- **Primary key:** `crash_unit_id`
- **Foreign key:** `crash_record_id` → `crashes.crash_record_id`
- **Indexes:** `vehicle_type`, `vehicle_year`, `make`, `crash_record_id`.
- **Common unit types:** DRIVER, PARKED, BICYCLE, PEDESTRIAN, DRIVERLESS, NON-MOTOR VEHICLE.

**Key analytic fields**
- Unit descriptors: `unit_no`, `unit_type`, `vehicle_use`.
- Vehicle identity: `vehicle_id`, `make`, `model`, `vehicle_year`, `lic_plate_state`, `cmv_id`.
- Occupancy & maneuvering: `num_passengers`, `occupant_cnt`, `travel_direction`, `maneuver`.
- Incident flags: `towed_i`, `fire_i`, `hazmat_placard_i`, `hazmat_present_i`, `hazmat_name`.
- Damage details: `first_contact_point`, `vehicle_defect`.
- Pipeline metadata: `created_at`, `updated_at`.

### Vision Zero Fatalities (`public.vision_zero_fatalities`)

- **Primary key:** `person_id` (links to `crash_people.person_id` where available)
- **Indexes:** `crash_date`, `victim`, `rd_no`, `GIST(geometry)`.
- **Refresh cadence:** Mirrors the Vision Zero scheduled job window configured in `scheduled_jobs`.
- **Victim categories:** PEDESTRIAN, DRIVER, BICYCLIST, PASSENGER, and other roles defined in the source dataset.

**Key analytic fields**
- Case identifiers: `person_id`, `rd_no` (Chicago Police RD number reinstated by pipeline).
- Narrative fields: `crash_location`, `crash_circumstances`, `victim` role.
- Spatial: `longitude`, `latitude`, `geometry` for mapping.
- Pipeline metadata: `created_at`, `updated_at`.

## Spatial Reference Tables

| Table | Geometry | Purpose |
| --- | --- | --- |
| `wards`, `community_areas`, `census_tracts`, `police_beats`, `house_districts`, `senate_districts` | Polygon | Pre-loaded shapefile boundaries for common joins. |
| `spatial_layers` | — | Registry of uploaded shapefiles. Fields: `name`, `slug`, `geometry_type`, `srid`, `feature_count`, `is_active`. |
| `spatial_layer_features` | Geometry (`mixed`) | Stores features for dynamic layers with `properties` JSON payloads. |

All spatial layers use SRID 4326 to match crash geometry. Use spatial indices (`GIST`) plus `ST_Intersects`/`ST_Within` for performant boundary joins.

## Operational Tables

| Table | Purpose |
| --- | --- |
| `scheduled_jobs` | Defines ETL jobs (`name`, `job_type`, `recurrence_type`, cron, retry policy). |
| `job_executions` | Execution log with `records_processed`, `records_inserted`, and `duration_seconds`. Join to `scheduled_jobs` on `job_id` for run metadata. |
| `data_deletion_logs` | Audits purge operations initiated by retention tooling. |

Recent job history (sample):

```sql
SELECT e.execution_id,
       s.name,
       s.job_type,
       e.status,
       e.started_at,
       e.completed_at,
       e.records_processed
FROM job_executions e
JOIN scheduled_jobs s ON s.id = e.job_id
ORDER BY e.started_at DESC
LIMIT 5;
```

## Example Queries

```sql
-- Crash with people and vehicle occupant rollup
SELECT c.crash_record_id,
       c.crash_date,
       c.prim_contributory_cause,
       v.vehicle_id,
       v.unit_type,
       jsonb_agg(jsonb_build_object(
         'person_id', p.person_id,
         'person_type', p.person_type,
         'injury', p.injury_classification
       ) ORDER BY p.person_type) AS occupants
FROM crashes c
JOIN crash_vehicles v ON v.crash_record_id = c.crash_record_id
LEFT JOIN crash_people p ON p.vehicle_id = v.vehicle_id
WHERE c.crash_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY c.crash_record_id, c.crash_date, c.prim_contributory_cause, v.vehicle_id, v.unit_type;
```

```sql
-- Fatal crashes with mapped geometry
SELECT vz.person_id,
       vz.victim,
       vz.crash_date,
       c.crash_record_id,
       ST_AsGeoJSON(vz.geometry) AS geom
FROM vision_zero_fatalities vz
LEFT JOIN crash_people p ON p.person_id = vz.person_id
LEFT JOIN crashes c ON c.crash_record_id = p.crash_record_id
WHERE vz.crash_date >= CURRENT_DATE - INTERVAL '180 days';
```

```sql
-- Hotspots by police beat using spatial join
SELECT b.beat,
       COUNT(*) AS crash_count
FROM crashes c
JOIN police_beats b
  ON ST_Within(c.geometry, b.geom)
GROUP BY b.beat
ORDER BY crash_count DESC
LIMIT 10;
```

## Data Quality Notes

- **Temporal coverage:** Incremental jobs refresh recent windows as defined in `scheduled_jobs`; run the `initial-load` CLI task for a full-history backfill.
- **Coordinate accuracy:** Records without lat/long cannot be spatially joined; the pipeline skips geometry creation when either coordinate is null.
- **RD numbers:** `vision_zero_fatalities.rd_no` is retained internally even though the public portal removes it; treat as sensitive and avoid exposing externally.
- **Null crash dates in people data:** Use the parent crash timestamp instead of `crash_people.crash_date` when building timelines.
- **Amended reports:** Records can be updated post-ingestion; rely on `updated_at` to detect changes during CDC-style processes.

## Usage Recommendations

1. Join on `crashes.crash_record_id` for core relationships; use `crash_people.vehicle_id` when you need occupant-to-unit linkage.
2. Filter by `unit_type`/`person_type` to differentiate between motor vehicles, pedestrians, cyclists, and parked units.
3. Prefer geometry-based joins (`ST_Within`, `ST_Intersects`) against boundary tables; fall back to lat/long only when PostGIS is unavailable.
4. Track refresh status with `job_executions` to confirm data recency before publishing derived dashboards.
5. When exporting, include the ETL validation window (e.g., "data through &lt;YYYY-MM-DD&gt;") to set expectations about coverage.

For deeper column-level descriptions, keep the historical [data portal documentation](https://data.cityofchicago.org/browse?q=Traffic%20Crashes) handy; the warehouse mirrors those definitions while adding spatial and operational metadata.
