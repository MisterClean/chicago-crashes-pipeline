//! Dashboard and spatial read contracts over the complete DuckDB fact schema.
//!
//! Fact selection and aggregation stay in DuckDB. A report uses one statement
//! so every section observes the same database snapshot during daily publication.

use std::cmp::Ordering;
use std::collections::BTreeMap;

use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Datelike, Duration, NaiveDate, NaiveDateTime, Timelike, Utc};
use chrono_tz::America::Chicago;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::db::Database;

pub const MAP_LIMIT: usize = 5000;
const CYCLIST: &str = "(person_type ILIKE '%BICYCLE%' OR person_type ILIKE '%CYCLIST%' OR person_type ILIKE '%PEDALCYCLIST%')";
const KNOWN: &str = "'FATAL','INCAPACITATING INJURY','NONINCAPACITATING INJURY','REPORTED, NOT EVIDENT','NO INDICATION OF INJURY'";
const MAP_COLUMNS: &str = "crash_record_id, strftime(crash_date,'%Y-%m-%dT%H:%M:%S.%f') AS crash_date, injuries_total, injuries_fatal, injuries_incapacitating, hit_and_run_i, crash_type, street_name, prim_contributory_cause, ST_X(geometry) AS longitude, ST_Y(geometry) AS latitude";
const COSTS: [(&str, i64, i64, &str); 5] = [
    ("FATAL", 1_606_644, 9_651_851, "Fatal (K)"),
    (
        "INCAPACITATING INJURY",
        172_179,
        917_345,
        "Incapacitating (A)",
    ),
    (
        "NONINCAPACITATING INJURY",
        44_490,
        180_107,
        "Non-incapacitating (B)",
    ),
    (
        "REPORTED, NOT EVIDENT",
        25_933,
        85_348,
        "Possible Injury (C)",
    ),
    ("NO INDICATION OF INJURY", 0, 0, "No Indication (O)"),
];
const NATIVE: [(&str, &str, &str, &str); 5] = [
    ("wards", "ward", "Wards", "Ward"),
    (
        "community_areas",
        "area_numbe",
        "Community Areas",
        "Community Area",
    ),
    (
        "house_districts",
        "district",
        "IL House Districts",
        "House District",
    ),
    (
        "senate_districts",
        "district",
        "IL Senate Districts",
        "Senate District",
    ),
    ("police_beats", "beat_num", "Police Beats", "Police Beat"),
];

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DateRange {
    pub start_date: Option<String>,
    pub end_date: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocationRequest {
    pub start_date: Option<String>,
    pub end_date: Option<String>,
    pub latitude: Option<f64>,
    pub longitude: Option<f64>,
    pub radius_feet: Option<f64>,
    pub polygon: Option<Vec<[f64; 2]>>,
    pub place_type: Option<String>,
    pub place_id: Option<String>,
    /// Internal durable export geometry; public HTTP bodies must reject this field.
    pub resolved_area: Option<Value>,
}

impl LocationRequest {
    pub fn dates(&self) -> DateRange {
        DateRange {
            start_date: self.start_date.clone(),
            end_date: self.end_date.clone(),
        }
    }

    pub fn validate(&self) -> Result<()> {
        let radius = [
            self.latitude.is_some(),
            self.longitude.is_some(),
            self.radius_feet.is_some(),
        ];
        ensure!(
            !radius.iter().any(|x| *x) || radius.iter().all(|x| *x),
            "A radius requires latitude, longitude, and radius_feet"
        );
        ensure!(
            self.place_type.is_some() == self.place_id.is_some(),
            "A place requires place_type and place_id"
        );
        ensure!(
            usize::from(radius[0])
                + usize::from(self.place_type.is_some())
                + usize::from(self.polygon.is_some())
                == 1,
            "Choose exactly one radius, polygon, or stored place"
        );
        for value in [&self.place_type, &self.place_id].into_iter().flatten() {
            ensure!(
                value.len() <= 100,
                "Place identifiers must be at most 100 bytes"
            );
        }
        if let (Some(lat), Some(lng), Some(radius)) =
            (self.latitude, self.longitude, self.radius_feet)
        {
            ensure!(
                lat.is_finite()
                    && lng.is_finite()
                    && radius.is_finite()
                    && (-90.0..=90.0).contains(&lat)
                    && (-180.0..=180.0).contains(&lng)
                    && radius > 0.0
                    && radius <= 26400.0,
                "Radius requires valid coordinates and 0 < radius_feet <= 26400"
            );
        }
        if let Some(polygon) = &self.polygon {
            ensure!(
                (3..=10000).contains(&polygon.len()),
                "Polygon must have between 3 and 10000 vertices"
            );
            ensure!(
                polygon.iter().all(|[x, y]| x.is_finite()
                    && y.is_finite()
                    && (-180.0..=180.0).contains(x)
                    && (-90.0..=90.0).contains(y)),
                "Polygon coordinates must be finite longitude/latitude pairs"
            );
        }
        normalized_dates(&self.dates())?;
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct Selection {
    pub sql: String,
    pub params: Vec<Value>,
    pub query_area: Value,
    /// The same positional parameters and spatial predicate apply to Vision Zero.
    pub spatial_sql: String,
    pub date_sql: String,
}

fn now_chicago() -> NaiveDateTime {
    Utc::now().with_timezone(&Chicago).naive_local()
}

/// Interpret offset timestamps in Chicago; naive timestamps are Chicago wall time.
pub fn wall_time(value: &str) -> Result<NaiveDateTime> {
    if let Ok(value) = DateTime::parse_from_rfc3339(value) {
        return Ok(value.with_timezone(&Chicago).naive_local());
    }
    for format in [
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%d %H:%M:%S%.f",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
    ] {
        if let Ok(value) = NaiveDateTime::parse_from_str(value, format) {
            return Ok(value);
        }
    }
    let date = NaiveDate::parse_from_str(value, "%Y-%m-%d").context("Invalid ISO date/time")?;
    date.and_hms_opt(0, 0, 0).context("Invalid date")
}

fn normalized_dates(dates: &DateRange) -> Result<(Option<NaiveDateTime>, Option<NaiveDateTime>)> {
    let start = dates.start_date.as_deref().map(wall_time).transpose()?;
    let mut end = dates.end_date.as_deref().map(wall_time).transpose()?;
    if let Some(value) = end
        && value.time().num_seconds_from_midnight() == 0
        && value.nanosecond() == 0
    {
        end = value.date().and_hms_micro_opt(23, 59, 59, 999_999);
    }
    ensure!(
        !matches!((start,end), (Some(a),Some(b)) if a>b),
        "start_date must not be after end_date"
    );
    Ok((start, end))
}

fn bind(params: &mut Vec<Value>, value: impl Into<Value>) -> String {
    params.push(value.into());
    format!("${}", params.len())
}

pub fn date_predicate(dates: &DateRange) -> Result<(String, Vec<Value>)> {
    let (start, end) = normalized_dates(dates)?;
    let mut params = Vec::new();
    let mut sql = String::from("TRUE");
    for (op, value) in [(">=", start), ("<=", end)] {
        if let Some(value) = value {
            let parameter = bind(
                &mut params,
                value.format("%Y-%m-%d %H:%M:%S%.6f").to_string(),
            );
            sql.push_str(&format!(
                " AND crash_date {op} CAST({parameter} AS TIMESTAMP)"
            ));
        }
    }
    Ok((sql, params))
}

fn row(db: &Database, sql: &str, params: &[Value]) -> Result<Value> {
    db.query(sql, params)?
        .into_iter()
        .next()
        .context("Query returned no row")
}

fn parse_json(value: &Value) -> Result<Value> {
    match value {
        Value::String(s) => Ok(serde_json::from_str(s)?),
        Value::Null => Ok(json!({})),
        _ => Ok(value.clone()),
    }
}

pub fn dashboard_stats(db: &Database, dates: &DateRange) -> Result<Value> {
    let (predicate, params) = date_predicate(dates)?;
    // People use their own date here, including missing dates for all-history.
    row(
        db,
        &format!(
            "SELECT * FROM (SELECT count(*) AS total_crashes, coalesce(sum(injuries_total),0)::BIGINT AS total_injuries, coalesce(sum(injuries_fatal),0)::BIGINT AS total_fatalities, count(*) FILTER (WHERE hit_and_run_i='Y') AS hit_and_run_count FROM crashes WHERE {predicate}) CROSS JOIN (SELECT count(*) FILTER (WHERE person_type ILIKE '%PEDESTRIAN%') AS pedestrians_involved, count(*) FILTER (WHERE {CYCLIST}) AS cyclists_involved FROM crash_people WHERE {predicate})"
        ),
        &params,
    )
}

pub fn weekly_trends(db: &Database, dates: &DateRange, weeks: usize) -> Result<Value> {
    ensure!(
        (1..=104).contains(&weeks),
        "weeks must be between 1 and 104"
    );
    let mut dates = dates.clone();
    if dates.start_date.is_none() && dates.end_date.is_none() {
        dates.start_date = Some((now_chicago() - Duration::weeks(weeks as i64)).to_string());
    }
    let (predicate, params) = date_predicate(&dates)?;
    Ok(json!(db.query(&format!("SELECT strftime(date_trunc('week',crash_date),'%Y-%m-%d') AS week, count(*) AS crashes, coalesce(sum(injuries_total),0)::BIGINT AS injuries, coalesce(sum(injuries_fatal),0)::BIGINT AS fatalities FROM crashes WHERE crash_date IS NOT NULL AND {predicate} GROUP BY 1 ORDER BY 1"),&params)?))
}

fn map_features(rows: Vec<Value>) -> Value {
    json!({"type":"FeatureCollection","features":rows.into_iter().map(|r| {
        let date = r["crash_date"].as_str().map(|s| s.strip_suffix(".000000").unwrap_or(s));
        json!({"type":"Feature","geometry":{"type":"Point","coordinates":[r["longitude"],r["latitude"]]},"properties":{
            "crash_record_id":r["crash_record_id"],"crash_date":date,
            "injuries_total":r["injuries_total"].as_i64().unwrap_or(0),
            "injuries_fatal":r["injuries_fatal"].as_i64().unwrap_or(0),
            "injuries_incapacitating":r["injuries_incapacitating"].as_i64().unwrap_or(0),
            "hit_and_run_i":r["hit_and_run_i"]=="Y", "crash_type":r["crash_type"],
            "street_name":r["street_name"],"primary_contributory_cause":r["prim_contributory_cause"]}})
    }).collect::<Vec<_>>()})
}

pub fn crashes_geojson(db: &Database, dates: &DateRange, limit: usize) -> Result<Value> {
    ensure!(
        (1..=50000).contains(&limit),
        "limit must be between 1 and 50000"
    );
    let (predicate, params) = date_predicate(dates)?;
    Ok(map_features(db.query(&format!("SELECT {MAP_COLUMNS} FROM crashes WHERE geometry IS NOT NULL AND {predicate} ORDER BY crash_date DESC,crash_record_id LIMIT {limit}"),&params)?))
}

pub fn crashes_by_hour(db: &Database, dates: &DateRange) -> Result<Value> {
    let (predicate, params) = date_predicate(dates)?;
    Ok(json!(db.query(&format!("SELECT hour(crash_date) AS hour, count(*) AS crashes, coalesce(sum(injuries_total),0)::BIGINT AS injuries, coalesce(sum(injuries_fatal),0)::BIGINT AS fatalities FROM crashes WHERE crash_date IS NOT NULL AND {predicate} GROUP BY 1 ORDER BY 1"),&params)?))
}

pub fn crashes_by_cause(db: &Database, dates: &DateRange, limit: usize) -> Result<Value> {
    ensure!((1..=50).contains(&limit), "limit must be between 1 and 50");
    let (predicate, params) = date_predicate(dates)?;
    Ok(json!(db.query(&format!("SELECT prim_contributory_cause AS cause, count(*) AS crashes, coalesce(sum(injuries_total),0)::BIGINT AS injuries, coalesce(sum(injuries_fatal),0)::BIGINT AS fatalities FROM crashes WHERE prim_contributory_cause IS NOT NULL AND prim_contributory_cause!='' AND {predicate} GROUP BY 1 ORDER BY crashes DESC,cause LIMIT {limit}"),&params)?))
}

pub fn layers(db: &Database) -> Result<Value> {
    Ok(json!(
        db.query("SELECT * FROM spatial_layers ORDER BY id", &[])?
    ))
}

fn table_exists(db: &Database, name: &str) -> Result<bool> {
    Ok(row(db,"SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='main' AND table_name=$1",&[json!(name)])?["n"].as_i64().unwrap_or(0)>0)
}

pub fn place_types(db: &Database) -> Result<Value> {
    let mut result = Vec::new();
    for (table, _, name, _) in NATIVE {
        if table_exists(db, table)? {
            let n = row(db, &format!("SELECT count(*) AS n FROM {table}"), &[])?["n"]
                .as_i64()
                .unwrap_or(0);
            if n > 0 {
                result.push(json!({"id":table,"name":name,"source":"native","feature_count":n}));
            }
        }
    }
    for layer in db.query(
        "SELECT * FROM spatial_layers WHERE is_active ORDER BY id",
        &[],
    )? {
        result.push(json!({"id":format!("layer:{}",layer["id"]),"name":layer["name"],"source":"uploaded","feature_count":layer["feature_count"]}));
    }
    Ok(json!(result))
}

fn layer(db: &Database, id: i64) -> Result<Value> {
    db.query(
        "SELECT * FROM spatial_layers WHERE id=$1 AND is_active",
        &[json!(id)],
    )?
    .into_iter()
    .next()
    .with_context(|| format!("Layer not found or inactive: {id}"))
}

fn layer_id(place_type: &str) -> Result<Option<i64>> {
    place_type
        .strip_prefix("layer:")
        .map(|v| v.parse::<i64>().context("Invalid layer ID"))
        .transpose()
}

fn value_label(value: &Value) -> String {
    match value {
        Value::String(value) => value.clone(),
        Value::Number(n) if n.is_i64() || n.is_u64() => n.to_string(),
        Value::Number(n) if n.as_f64().is_some_and(|v| v.fract() == 0.0) => {
            format!("{:.0}", n.as_f64().unwrap_or(0.0))
        }
        Value::Null => "None".to_owned(),
        Value::Bool(true) => "True".to_owned(),
        Value::Bool(false) => "False".to_owned(),
        _ => value.to_string(),
    }
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::String(s) => !s.is_empty(),
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn feature_name(properties: &Value, id: i64, label: Option<&str>) -> String {
    if let Some(value) = label.and_then(|key| properties.get(key)) {
        return value_label(value);
    }
    for key in [
        "name",
        "NAME",
        "Name",
        "title",
        "TITLE",
        "Title",
        "label",
        "LABEL",
        "Label",
        "display_name",
        "DISPLAY_NAME",
    ] {
        if let Some(value) = properties.get(key).filter(|v| truthy(v)) {
            return value_label(value);
        }
    }
    for (key, prefix) in [
        ("ward", "Ward"),
        ("district", "District"),
        ("dist_num", "District"),
        ("beat_num", "Beat"),
        ("community", ""),
        ("area_numbe", "Area"),
        ("objectid", "Feature"),
    ] {
        if let Some(value) = properties
            .get(key)
            .filter(|v| truthy(v))
            .or_else(|| properties.get(key.to_uppercase()).filter(|v| truthy(v)))
        {
            return format!("{prefix} {}", value_label(value)).trim().to_owned();
        }
    }
    format!("Feature {id}")
}

fn native(place_type: &str) -> Result<(&'static str, &'static str, &'static str, &'static str)> {
    NATIVE
        .into_iter()
        .find(|r| r.0 == place_type)
        .with_context(|| format!("Unknown place type: {place_type}"))
}

fn numeric_key(value: &str) -> Option<u128> {
    let digits: String = value
        .chars()
        .skip_while(|c| !c.is_ascii_digit())
        .take_while(char::is_ascii_digit)
        .collect();
    digits.parse().ok()
}

fn natural_cmp(a: &str, b: &str) -> Ordering {
    fn parts(value: &str) -> Vec<(bool, &str)> {
        let mut result = Vec::new();
        let mut start = 0;
        let mut digit = false;
        for (index, character) in value.char_indices() {
            let next = character.is_ascii_digit();
            if next != digit {
                result.push((digit, &value[start..index]));
                start = index;
                digit = next;
            }
        }
        result.push((digit, &value[start..]));
        if digit {
            result.push((false, ""));
        }
        result
    }
    let (a, b) = (a.to_lowercase(), b.to_lowercase());
    let (a, b) = (parts(&a), parts(&b));
    for ((digit_a, a), (digit_b, b)) in a.iter().zip(&b) {
        let order = digit_a.cmp(digit_b).then_with(|| {
            if *digit_a {
                let (a, b) = (a.trim_start_matches('0'), b.trim_start_matches('0'));
                a.len().cmp(&b.len()).then_with(|| a.cmp(b))
            } else {
                a.cmp(b)
            }
        });
        if order != Ordering::Equal {
            return order;
        }
    }
    a.len().cmp(&b.len())
}

pub fn places(db: &Database, place_type: &str) -> Result<Value> {
    if let Some(id) = layer_id(place_type)? {
        let layer = layer(db, id)?;
        let mut items = Vec::new();
        for feature in db.query(
            "SELECT id,properties FROM spatial_layer_features WHERE layer_id=$1 ORDER BY id",
            &[json!(id)],
        )? {
            let feature_id = feature["id"].as_i64().context("Invalid feature identity")?;
            let name = feature_name(
                &parse_json(&feature["properties"])?,
                feature_id,
                layer["label_field"].as_str(),
            );
            items.push(json!({"id":feature_id.to_string(),"name":name,"display_name":name}));
        }
        items.sort_by(|a, b| {
            let (a, b) = (
                a["name"].as_str().unwrap_or(""),
                b["name"].as_str().unwrap_or(""),
            );
            match layer["sort_type"].as_str() {
                Some("numeric") => numeric_key(a)
                    .unwrap_or(u128::MAX)
                    .cmp(&numeric_key(b).unwrap_or(u128::MAX))
                    .then_with(|| a.cmp(b)),
                Some("natural") => natural_cmp(a, b),
                _ => a.to_lowercase().cmp(&b.to_lowercase()),
            }
        });
        return Ok(json!(items));
    }
    let (table, key, _, prefix) = native(place_type)?;
    ensure!(table_exists(db, table)?, "Unknown place type: {place_type}");
    let item_prefix = match table {
        "house_districts" | "senate_districts" => "District",
        "police_beats" => "Beat",
        _ => prefix,
    };
    let mut items = Vec::new();
    for r in db.query(
        &format!("SELECT * EXCLUDE (geometry) FROM {table} ORDER BY {key}"),
        &[],
    )? {
        let id = value_label(&r[key]);
        let name = r
            .get("community")
            .filter(|v| truthy(v))
            .map(value_label)
            .unwrap_or_else(|| format!("{item_prefix} {id}"));
        let person = ["alderman", "rep_name", "senator_name"]
            .into_iter()
            .find_map(|k| r.get(k).filter(|v| truthy(v)));
        let display =
            person.map_or_else(|| name.clone(), |p| format!("{name} - {}", value_label(p)));
        items.push(json!({"id":id,"name":name,"display_name":display}));
    }
    Ok(json!(items))
}

pub fn place_geometry(db: &Database, place_type: &str, place_id: &str) -> Result<Value> {
    let (geometry, name) = if let Some(id) = layer_id(place_type)? {
        let layer = layer(db, id)?;
        let feature_id: i64 = place_id.parse().context("Invalid feature ID")?;
        let r=db.query("SELECT id,properties,ST_AsGeoJSON(geometry) AS geometry FROM spatial_layer_features WHERE layer_id=$1 AND id=$2",&[json!(id),json!(feature_id)])?.into_iter().next().context("Feature not found in layer")?;
        (
            parse_json(&r["geometry"])?,
            feature_name(
                &parse_json(&r["properties"])?,
                feature_id,
                layer["label_field"].as_str(),
            ),
        )
    } else {
        let (table, key, _, _) = native(place_type)?;
        ensure!(table_exists(db, table)?, "Unknown place type: {place_type}");
        let r = db
            .query(
                &format!(
                    "SELECT ST_AsGeoJSON(geometry) AS geometry FROM {table} WHERE {key}::VARCHAR=$1"
                ),
                &[json!(place_id)],
            )?
            .into_iter()
            .next()
            .context("Place not found")?;
        let items = places(db, place_type)?;
        let name = items
            .as_array()
            .and_then(|items| items.iter().find(|item| item["id"] == place_id))
            .and_then(|v| v["name"].as_str())
            .context("Place label not found")?
            .to_owned();
        (parse_json(&r["geometry"])?, name)
    };
    Ok(json!({"place_type":place_type,"place_id":place_id,"name":name,"geometry":geometry}))
}

pub fn layer_geojson(db: &Database, id: i64) -> Result<Value> {
    layer(db, id)?;
    let mut features = Vec::new();
    for r in db.query("SELECT id,properties,ST_AsGeoJSON(geometry) AS geometry FROM spatial_layer_features WHERE layer_id=$1 ORDER BY id",&[json!(id)])? {
        features.push(json!({"type":"Feature","id":r["id"],"properties":parse_json(&r["properties"])? ,"geometry":parse_json(&r["geometry"])?}));
    }
    Ok(json!({"type":"FeatureCollection","features":features}))
}

fn polygon_predicate(db: &Database, geometry: &Value, params: &mut Vec<Value>) -> Result<String> {
    ensure!(
        matches!(geometry["type"].as_str(), Some("Polygon" | "MultiPolygon")),
        "Selection geometry must be Polygon or MultiPolygon"
    );
    let encoded = serde_json::to_string(geometry)?;
    let check = row(
        db,
        "SELECT ST_IsValid(g) AS valid, ST_IsEmpty(g) AS empty, ST_XMin(g) AS min_lng, ST_YMin(g) AS min_lat, ST_XMax(g) AS max_lng, ST_YMax(g) AS max_lat FROM (SELECT ST_GeomFromGeoJSON($1) AS g)",
        &[json!(encoded)],
    )?;
    ensure!(
        check["valid"] == true && check["empty"] == false,
        "Selection geometry must be valid and nonempty"
    );
    let area = bind(params, encoded);
    let min_lng = bind(params, check["min_lng"].clone());
    let max_lng = bind(params, check["max_lng"].clone());
    let min_lat = bind(params, check["min_lat"].clone());
    let max_lat = bind(params, check["max_lat"].clone());
    Ok(format!(
        "longitude BETWEEN {min_lng} AND {max_lng} AND latitude BETWEEN {min_lat} AND {max_lat} AND ST_Contains(ST_GeomFromGeoJSON({area}),geometry)"
    ))
}

pub fn selected_crashes(db: &Database, request: &LocationRequest) -> Result<Selection> {
    request.validate()?;
    let (date_sql, mut params) = date_predicate(&request.dates())?;
    let (spatial_sql, query_area) = if let (Some(lat), Some(lng), Some(radius)) =
        (request.latitude, request.longitude, request.radius_feet)
    {
        ensure!(
            lat.is_finite()
                && lng.is_finite()
                && radius.is_finite()
                && (-90.0..=90.0).contains(&lat)
                && (-180.0..=180.0).contains(&lng)
                && radius > 0.0
                && radius <= 26400.0,
            "Radius requires valid coordinates and 0 < radius_feet <= 26400"
        );
        let meters = radius * 0.3048;
        let delta_lat = meters / 110000.0;
        let min_lat = (-90.0_f64).max(lat - delta_lat);
        let max_lat = 90.0_f64.min(lat + delta_lat);
        let delta_lng = meters
            / (110000.0
                * min_lat
                    .abs()
                    .max(max_lat.abs())
                    .to_radians()
                    .cos()
                    .max(0.000001));
        let a = bind(&mut params, min_lat);
        let b = bind(&mut params, max_lat);
        let x = bind(&mut params, lng);
        let y = bind(&mut params, lat);
        let r = bind(&mut params, meters);
        let mut predicate = format!(
            "latitude BETWEEN {a} AND {b} AND ST_Distance_Spheroid(geometry,ST_Point({x},{y}))<={r}"
        );
        if lng - delta_lng >= -180.0 && lng + delta_lng <= 180.0 {
            let a = bind(&mut params, lng - delta_lng);
            let b = bind(&mut params, lng + delta_lng);
            predicate.push_str(&format!(" AND longitude BETWEEN {a} AND {b}"));
        }
        // Freeze display geometry only. It must never replace inclusive geodesic selection.
        let area = if let Some(area) = &request.resolved_area {
            area.clone()
        } else {
            let projection =
                format!("+proj=aeqd +lat_0={lat} +lon_0={lng} +datum=WGS84 +units=m +no_defs");
            let r = row(
                db,
                "SELECT ST_AsGeoJSON(ST_Transform(ST_Buffer(ST_Transform(ST_Point($1,$2),'EPSG:4326',$3,always_xy := true),$4),$3,'EPSG:4326',always_xy := true)) AS geometry",
                &[json!(lng), json!(lat), json!(projection), json!(meters)],
            )?;
            json!({"type":"Feature","geometry":parse_json(&r["geometry"])? ,"properties":{"type":"radius","center":[lng,lat],"radius_feet":radius}})
        };
        (predicate, area)
    } else if let Some(area) = &request.resolved_area {
        let geometry = area.get("geometry").unwrap_or(area);
        let spatial = polygon_predicate(db, geometry, &mut params)?;
        let area = if area["type"] == "Feature" {
            area.clone()
        } else {
            json!({"type":"Feature","geometry":geometry,"properties":{"type":"place"}})
        };
        (spatial, area)
    } else if let (Some(kind), Some(id)) = (&request.place_type, &request.place_id) {
        let place = place_geometry(db, kind, id)?;
        let spatial = polygon_predicate(db, &place["geometry"], &mut params)?;
        let name = if let Some(layer) = layer_id(kind)? {
            let feature_id: i64 = id.parse().context("Invalid feature ID")?;
            let properties = parse_json(
                &row(
                    db,
                    "SELECT properties FROM spatial_layer_features WHERE layer_id=$1 AND id=$2",
                    &[json!(layer), json!(feature_id)],
                )?["properties"],
            )?;
            ["name", "NAME", "title", "TITLE"]
                .into_iter()
                .find_map(|k| properties.get(k).filter(|v| truthy(v)))
                .cloned()
                .unwrap_or_else(|| json!(format!("Feature {id}")))
        } else if kind != "community_areas" {
            json!(format!("{} {id}", native(kind)?.3))
        } else {
            place["name"].clone()
        };
        (
            spatial,
            json!({"type":"Feature","geometry":place["geometry"],"properties":{"type":"place","place_type":kind,"place_id":id,"name":name}}),
        )
    } else if let Some(polygon) = &request.polygon {
        ensure!(
            (3..=10000).contains(&polygon.len()),
            "Polygon must have between 3 and 10000 vertices"
        );
        ensure!(
            polygon.iter().all(|[x, y]| x.is_finite()
                && y.is_finite()
                && (-180.0..=180.0).contains(x)
                && (-90.0..=90.0).contains(y)),
            "Polygon coordinates must be finite longitude/latitude pairs"
        );
        let mut coordinates = polygon.clone();
        if coordinates.first() != coordinates.last() {
            coordinates.push(coordinates[0]);
        }
        let geometry = json!({"type":"Polygon","coordinates":[coordinates]});
        let spatial = polygon_predicate(db, &geometry, &mut params)?;
        (
            spatial,
            json!({"type":"Feature","geometry":geometry,"properties":{"type":"polygon"}}),
        )
    } else {
        bail!("Provide radius coordinates, polygon, or place_type/place_id")
    };
    Ok(Selection {
        sql: format!(
            "SELECT c.* FROM crashes c WHERE geometry IS NOT NULL AND {spatial_sql} AND {date_sql}"
        ),
        params,
        query_area,
        spatial_sql,
        date_sql,
    })
}

fn costs(counts: &[Value], pdo: i64) -> Value {
    let mut total_economic = pdo * 6269;
    let mut total_societal = pdo * (6269 + 3927);
    let injury_costs=COSTS.into_iter().map(|(class,economic,qaly,label)| {
        let n=counts.iter().find(|r|r["injury_classification"]==class).and_then(|r|r["count"].as_i64()).unwrap_or(0);
        total_economic+=n*economic; total_societal+=n*(economic+qaly);
        json!({"classification":class,"classification_label":label,"count":n,"unit_economic_cost":economic,"unit_qaly_cost":qaly,"subtotal_economic":n*economic,"subtotal_societal":n*(economic+qaly)})
    }).collect::<Vec<_>>();
    json!({"injury_costs":injury_costs,"vehicle_costs":{"count":pdo,"unit_economic_cost":6269,"unit_qaly_cost":3927,"subtotal_economic":pdo*6269,"subtotal_societal":pdo*(6269+3927)},"total_economic":total_economic,"total_societal":total_societal})
}

pub fn fill_report_months(rows: &[Value], dates: &DateRange, now: NaiveDateTime) -> Result<Value> {
    let (start, end) = normalized_dates(dates)?;
    let months = rows
        .iter()
        .filter_map(|row| row["month"].as_str().map(|m| (m, row)))
        .collect::<BTreeMap<_, _>>();
    let first = start.or(months
        .first_key_value()
        .map(|(m, _)| wall_time(&format!("{m}-01")))
        .transpose()?);
    let last = end.or(months
        .last_key_value()
        .map(|(m, _)| wall_time(&format!("{m}-01")))
        .transpose()?);
    let (Some(first), Some(last)) = (first, last) else {
        return Ok(json!([]));
    };
    let mut cursor = first
        .date()
        .with_day(1)
        .and_then(|d| d.and_hms_opt(0, 0, 0))
        .context("Invalid month")?;
    let mut result = Vec::new();
    while cursor <= last {
        let following = (cursor + Duration::days(32))
            .date()
            .with_day(1)
            .and_then(|d| d.and_hms_opt(0, 0, 0))
            .context("Month exceeds supported range")?;
        let month = cursor.format("%Y-%m").to_string();
        let row = months.get(month.as_str());
        result.push(json!({"month":month,"partial":first>cursor || (end.is_some() && last<following-Duration::microseconds(1)) || now<following,"crashes":row.map_or(0,|r|r["crashes"].as_i64().unwrap_or(0)),"injuries":row.map_or(0,|r|r["injuries"].as_i64().unwrap_or(0)),"fatalities":row.map_or(0,|r|r["fatalities"].as_i64().unwrap_or(0))}));
        cursor = following;
    }
    Ok(json!(result))
}

pub fn location_report(db: &Database, request: &LocationRequest) -> Result<Value> {
    location_report_at(db, request, now_chicago())
}

pub fn location_report_at(
    db: &Database,
    request: &LocationRequest,
    now: NaiveDateTime,
) -> Result<Value> {
    let selection = selected_crashes(db, request)?;
    let sql = include_str!("../sql/location_report.sql")
        .replace("__SELECTION__", &selection.sql)
        .replace("__CYCLIST__", CYCLIST)
        .replace("__KNOWN__", KNOWN);
    let mut report = parse_json(&row(db, &sql, &selection.params)?["payload"])?;
    let total = report["stats"]["total_crashes"]
        .as_i64()
        .unwrap_or(0)
        .max(1) as f64;
    if let Some(causes) = report["causes"].as_array_mut() {
        for cause in causes {
            let percentage = cause["crashes"].as_i64().unwrap_or(0) as f64 / total * 100.0;
            // Decimal formatting matches Python round's binary-float tie behavior.
            cause["percentage"] = json!(format!("{percentage:.1}").parse::<f64>()?);
        }
    }
    let counts = report["injury_counts"]
        .as_array()
        .context("Missing injury counts")?;
    let pdo = report["stats"]["pdo_vehicles"]
        .as_i64()
        .context("Missing vehicle count")?;
    let costs = costs(counts, pdo);
    report["stats"]["estimated_economic_damages"] = costs["total_economic"].clone();
    report["stats"]["estimated_societal_costs"] = costs["total_societal"].clone();
    report["stats"]["cost_breakdown"] = costs;
    if let Some(stats) = report["stats"].as_object_mut() {
        stats.remove("pdo_vehicles");
    }
    report["monthly_trends"] = fill_report_months(
        report["monthly_trends"]
            .as_array()
            .context("Missing months")?,
        &request.dates(),
        now,
    )?;
    let points = report["map_points"]
        .as_array_mut()
        .context("Missing map points")?;
    let points = std::mem::take(points);
    report["map_truncated"] =
        json!(report["stats"]["total_crashes"].as_u64().unwrap_or(0) > points.len() as u64);
    report["crashes_geojson"] = map_features(points);
    report["query_area_geojson"] = selection.query_area;
    report["map_limit"] = json!(MAP_LIMIT);
    if let Some(object) = report.as_object_mut() {
        object.remove("injury_counts");
        object.remove("map_points");
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dates_should_apply_chicago_offset_and_inclusive_midnight() {
        let dates = DateRange {
            start_date: Some("2024-02-01T05:00:00Z".into()),
            end_date: Some("2024-01-31".into()),
        };
        let (_, params) = date_predicate(&dates).unwrap();
        assert_eq!(
            params,
            vec![
                json!("2024-01-31 23:00:00.000000"),
                json!("2024-01-31 23:59:59.999999")
            ]
        );
    }

    #[test]
    fn dates_should_reject_reversed_window() {
        assert!(
            date_predicate(&DateRange {
                start_date: Some("2025-01-01".into()),
                end_date: Some("2024-01-01".into())
            })
            .is_err()
        );
    }

    #[test]
    fn selection_should_reject_ambiguous_modes() {
        assert!(
            LocationRequest {
                polygon: Some(vec![[0.0, 0.0]; 3]),
                place_type: Some("wards".into()),
                place_id: Some("1".into()),
                ..Default::default()
            }
            .validate()
            .is_err()
        );
    }

    #[test]
    fn months_should_fill_gaps_and_preserve_partial_flags() {
        let dates = DateRange {
            start_date: Some("2024-01-15".into()),
            end_date: Some("2024-03-15".into()),
        };
        let months = fill_report_months(
            &[json!({"month":"2024-01","crashes":1,"injuries":1,"fatalities":0})],
            &dates,
            wall_time("2025-01-01").unwrap(),
        )
        .unwrap();
        assert_eq!(
            months,
            json!([{"month":"2024-01","partial":true,"crashes":1,"injuries":1,"fatalities":0},{"month":"2024-02","partial":false,"crashes":0,"injuries":0,"fatalities":0},{"month":"2024-03","partial":true,"crashes":0,"injuries":0,"fatalities":0}])
        );
    }

    #[test]
    fn costs_should_count_people_once_and_only_pdo_vehicles() {
        let c = costs(
            &[json!({"injury_classification":"INCAPACITATING INJURY","count":1})],
            2,
        );
        assert_eq!(
            (c["total_economic"].as_i64(), c["total_societal"].as_i64()),
            (Some(184717), Some(1109916))
        );
    }

    #[test]
    fn natural_order_should_compare_digit_runs_without_overflow() {
        assert_eq!(natural_cmp("District 2", "District 10"), Ordering::Less);
        assert_eq!(natural_cmp("Ward 0002", "Ward 2"), Ordering::Equal);
    }
    fn fixture() -> Option<(Database, tempfile::TempDir)> {
        let library = crate::test_support::library();
        let directory = tempfile::tempdir().unwrap();
        let db = Database::open(
            &directory.path().join("fixture.duckdb"),
            &library,
            "256MB",
            2,
            &directory.path().join("spill"),
        )
        .unwrap();
        crate::test_support::load_spatial(&db);
        db.execute("SET geometry_always_xy=true", &[]).unwrap();
        for statement in include_str!("../sql/query_fixture.sql")
            .split(';')
            .filter(|s| !s.trim().is_empty())
        {
            db.execute(statement, &[]).unwrap();
        }
        Some((db, directory))
    }

    #[test]
    fn real_engine_should_preserve_parent_dates_costs_and_no_join_fanout() {
        let Some((db, _directory)) = fixture() else {
            return;
        };
        let dates = DateRange {
            start_date: Some("2024-01-01".into()),
            end_date: Some("2024-01-31".into()),
        };
        let city = dashboard_stats(&db, &dates).unwrap();
        assert_eq!(
            city,
            json!({"total_crashes":3,"total_injuries":1,"total_fatalities":0,"hit_and_run_count":1,"pedestrians_involved":0,"cyclists_involved":1})
        );
        let request = LocationRequest {
            place_type: Some("layer:4".into()),
            place_id: Some("259".into()),
            start_date: dates.start_date,
            end_date: dates.end_date,
            ..Default::default()
        };
        let report = location_report_at(&db, &request, wall_time("2025-01-01").unwrap()).unwrap();
        assert_eq!(report["stats"]["total_crashes"], 1);
        assert_eq!(report["stats"]["pedestrians_involved"], 1);
        assert_eq!(report["stats"]["cyclists_involved"], 0);
        assert_eq!(report["stats"]["children_injured"], 1);
        assert_eq!(report["stats"]["unknown_injury_count"], 1);
        assert_eq!(report["stats"]["total_vehicles"], 3);
        assert_eq!(report["stats"]["estimated_economic_damages"], 172179);
        assert_eq!(report["stats"]["estimated_societal_costs"], 1089524);
        assert_eq!(report["hour_day_counts"].as_array().unwrap().len(), 168);
        assert_eq!(report["hour_day_counts"][22]["severe_crashes"], 1);
    }

    #[test]
    fn real_engine_should_exclude_polygon_holes_and_edges_and_keep_uploaded_ids() {
        let Some((db, _directory)) = fixture() else {
            return;
        };
        let selection = selected_crashes(
            &db,
            &LocationRequest {
                place_type: Some("layer:4".into()),
                place_id: Some("259".into()),
                ..Default::default()
            },
        )
        .unwrap();
        let rows = db
            .query(
                &format!("SELECT crash_record_id FROM ({}) ORDER BY 1", selection.sql),
                &selection.params,
            )
            .unwrap();
        assert_eq!(
            rows,
            vec![
                json!({"crash_record_id":"a"}),
                json!({"crash_record_id":"d"})
            ]
        );
        assert_eq!(
            places(&db, "layer:4")
                .unwrap()
                .as_array()
                .unwrap()
                .iter()
                .map(|p| p["id"].as_str().unwrap())
                .collect::<Vec<_>>(),
            vec!["261", "260", "259"]
        );
        assert_eq!(place_geometry(&db, "layer:4", "259").unwrap()["name"], "10");
    }

    #[test]
    fn real_engine_should_use_inclusive_spheroid_radius_even_with_frozen_display_polygon() {
        let Some((db, _directory)) = fixture() else {
            return;
        };
        let distance = row(
            &db,
            "SELECT ST_Distance_Spheroid(ST_Point(-87.65,41.75),ST_Point(-87.649,41.75)) AS meters",
            &[],
        )
        .unwrap()["meters"]
            .as_f64()
            .unwrap();
        let mut request = LocationRequest {
            latitude: Some(41.75),
            longitude: Some(-87.65),
            radius_feet: Some(distance / 0.3048),
            resolved_area: Some(
                json!({"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]},"properties":{"type":"radius"}}),
            ),
            ..Default::default()
        };
        let selection = selected_crashes(&db, &request).unwrap();
        let rows = db
            .query(
                &format!("SELECT crash_record_id FROM ({}) ORDER BY 1", selection.sql),
                &selection.params,
            )
            .unwrap();
        assert_eq!(rows.len(), 2);
        request.radius_feet = Some(distance / 0.3048 - 0.01);
        let selection = selected_crashes(&db, &request).unwrap();
        let rows = db
            .query(
                &format!("SELECT crash_record_id FROM ({})", selection.sql),
                &selection.params,
            )
            .unwrap();
        assert_eq!(rows, vec![json!({"crash_record_id":"a"})]);
    }

    #[test]
    fn real_engine_should_cap_only_map_points_and_gap_fill_months() {
        let Some((db, _directory)) = fixture() else {
            return;
        };
        db.execute("INSERT INTO crashes (crash_record_id,crash_date,latitude,longitude,geometry,injuries_total) SELECT 'large-' || i,'2024-04-01'::TIMESTAMP,41.75,-87.65,ST_Point(-87.65,41.75),1 FROM range(5001) t(i)",&[]).unwrap();
        let report = location_report_at(
            &db,
            &LocationRequest {
                place_type: Some("layer:4".into()),
                place_id: Some("259".into()),
                start_date: Some("2024-04-01".into()),
                end_date: Some("2024-06-30".into()),
                ..Default::default()
            },
            wall_time("2025-01-01").unwrap(),
        )
        .unwrap();
        assert_eq!(report["stats"]["total_crashes"], 5001);
        assert_eq!(
            report["crashes_geojson"]["features"]
                .as_array()
                .unwrap()
                .len(),
            5000
        );
        assert_eq!(report["map_truncated"], true);
        assert_eq!(
            report["hour_day_counts"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v["crashes"].as_i64().unwrap())
                .sum::<i64>(),
            5001
        );
        assert_eq!(report["monthly_trends"].as_array().unwrap().len(), 3);
        assert_eq!(report["monthly_trends"][1]["crashes"], 0);
    }
    #[test]
    fn uploaded_integer_labels_preserve_full_json_integer_precision() {
        assert_eq!(
            feature_name(
                &json!({"district":9_007_199_254_740_993_u64}),
                1,
                Some("district")
            ),
            "9007199254740993"
        );
    }
}
