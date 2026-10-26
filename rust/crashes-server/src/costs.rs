//! Versioned FHWA person-injury costs, expressed in each crash's dollar year.
//! The October 2025 fact sheet's Step 1 inputs are in 2019 dollars (Step 3),
//! not the 2024 dollars used by its final crash-unit table.

use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::{Value, json};

pub const VERSION: &str = "fhwa-person-injury-crash-year-v1";
pub const SOURCE: &str =
    "https://highways.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf";
const INPUTS: &str = include_str!("../resources/kabco_annual_inputs.json");
const CLASSES: [(&str, &str, &str, i64, i64); 6] = [
    ("k", "FATAL", "Fatal (K)", 1_606_644, 9_651_851),
    (
        "a",
        "INCAPACITATING INJURY",
        "Incapacitating (A)",
        172_179,
        917_345,
    ),
    (
        "b",
        "NONINCAPACITATING INJURY",
        "Non-incapacitating (B)",
        44_490,
        180_107,
    ),
    (
        "c",
        "REPORTED, NOT EVIDENT",
        "Possible injury (C)",
        25_933,
        85_348,
    ),
    (
        "o",
        "NO INDICATION OF INJURY",
        "No indication (O)",
        6_269,
        3_927,
    ),
    ("vehicle", "VEHICLE", "Vehicle records", 7_913, 0),
];

#[derive(Deserialize)]
struct AnnualInput {
    year: i32,
    cpi: f64,
    muwe: f64,
}

#[derive(Deserialize)]
struct Schedule {
    annual_inputs: Vec<AnnualInput>,
}

fn inputs() -> Result<Vec<AnnualInput>> {
    let schedule: Schedule =
        serde_json::from_str(INPUTS).context("Invalid bundled KABCO inputs")?;
    ensure!(!schedule.annual_inputs.is_empty(), "KABCO inputs are empty");
    for (index, input) in schedule.annual_inputs.iter().enumerate() {
        ensure!(
            input.cpi.is_finite()
                && input.cpi > 0.0
                && input.muwe.is_finite()
                && input.muwe > 0.0
                && (index == 0 || schedule.annual_inputs[index - 1].year < input.year),
            "Invalid or unordered KABCO annual input"
        );
    }
    Ok(schedule.annual_inputs)
}

// Round each component's unit rate once to cents. SQL uses those exact decimal
// rates for both per-crash and aggregate values; report and export share them.
fn rate(base: i64, factor: f64) -> f64 {
    (base as f64 * factor * 100.0).round() / 100.0
}

fn rates(input: &AnnualInput) -> Vec<(f64, f64)> {
    CLASSES
        .iter()
        .map(|(_, _, _, economic, qaly)| {
            (
                rate(*economic, input.cpi / 255.657),
                rate(*qaly, input.muwe / 917.0),
            )
        })
        .collect()
}

/// CTEs require a caller-owned `selected` relation with crash identity, date and
/// injury counts. Both callers retain their existing single-snapshot admission.
pub fn ctes() -> Result<String> {
    let values = inputs()?
        .iter()
        .map(|input| {
            let mut fields = vec![
                input.year.to_string(),
                input.cpi.to_string(),
                input.muwe.to_string(),
            ];
            for (index, (economic, qaly)) in rates(input).into_iter().enumerate() {
                fields.push(format!("{economic:.2}::DECIMAL(18,2)"));
                if index < 5 {
                    fields.push(format!("{qaly:.2}::DECIMAL(18,2)"));
                }
            }
            format!("({})", fields.join(","))
        })
        .collect::<Vec<_>>()
        .join(",\n");
    Ok(include_str!("../sql/crash_costs.sql").replace("__COST_RATES__", &values))
}

pub fn methodology() -> Result<Value> {
    let mut metadata: Value = serde_json::from_str(INPUTS)?;
    metadata["dollar_basis"] =
        json!("Crash-year nominal USD; multi-year sums are not constant-dollar comparisons");
    metadata["supported_years"] = json!(inputs()?.iter().map(|i| i.year).collect::<Vec<_>>());
    metadata["calculation"] = json!(
        "Sum K/A/B/C/O person costs and economic costs for all linked vehicle records; economic × annual CPI-U / 2019 CPI-U; QALY × mean of four quarterly NSA weekly earnings / 2019 mean; unit components rounded to cents"
    );
    metadata["completeness_policy"] = json!(
        "Partial estimates sum known components only. Unknown classifications are excluded, not classified as O. Missing people/vehicle records and inconsistent parent injury counts flag incomplete coverage. Unsupported or missing crash years have no estimate. Completeness describes observed consistency, not proof that the source has published every record."
    );
    Ok(metadata)
}

/// A separate dataset preserves the exact schemas of existing raw exports.
/// Standalone CSVs carry their own provenance and unit rates; ZIPs also include
/// the complete versioned schedule in the existing manifest.
pub fn export_query(selection: &str) -> Result<String> {
    Ok(format!(
        "WITH selected AS MATERIALIZED ({selection}), {} 
        SELECT c.crash_record_id,c.crash_date,c.valuation_year,c.valuation_status,c.cost_status,
            c.estimated_economic_damages,c.estimated_societal_costs,
            c.person_count,c.vehicle_count,c.k_count,c.a_count,c.b_count,c.c_count,c.o_count,
            c.unknown_injury_count,c.person_count=0 AS missing_people,c.vehicle_count=0 AS missing_vehicles,
            c.inconsistent_injuries,c.inconsistent_vehicles,c.cpi,c.muwe,'{VERSION}' AS methodology_version,
            2019 AS base_dollar_year,2025 AS publication_year,'{SOURCE}' AS source_url,
            'Crash-year nominal USD; partial estimates include known components only' AS dollar_basis,
            to_json(struct_pack(k_economic:=r.k_e,k_qaly:=r.k_q,a_economic:=r.a_e,a_qaly:=r.a_q,
                b_economic:=r.b_e,b_qaly:=r.b_q,c_economic:=r.c_e,c_qaly:=r.c_q,
                o_economic:=r.o_e,o_qaly:=r.o_q,vehicle_economic:=r.vehicle_e,vehicle_qaly:=0)) AS unit_costs
        FROM cost_crashes c LEFT JOIN cost_rates r ON c.valuation_year=r.year ORDER BY c.crash_record_id",
        ctes()?
    ))
}

fn integer(row: &Value, key: &str) -> Result<i64> {
    row[key]
        .as_i64()
        .with_context(|| format!("Missing cost count: {key}"))
}

const COVERAGE_COUNTS: [&str; 9] = [
    "crash_count",
    "complete_crashes",
    "partial_crashes",
    "unavailable_crashes",
    "unknown_injury_count",
    "missing_people_crashes",
    "missing_vehicle_crashes",
    "inconsistent_injury_crashes",
    "inconsistent_vehicle_crashes",
];

fn coverage(row: &Value) -> Result<Value> {
    let mut result = json!({});
    for key in COVERAGE_COUNTS {
        result[key] = json!(integer(row, key)?);
    }
    result["status"] = json!(if integer(row, "crash_count")? == 0 {
        "empty"
    } else if integer(row, "complete_crashes")? == integer(row, "crash_count")? {
        "complete"
    } else if integer(row, "complete_crashes")? + integer(row, "partial_crashes")? > 0 {
        "partial"
    } else {
        "unavailable"
    });
    Ok(result)
}

/// Only bounded year aggregates cross the SQL boundary, never all crash rows.
pub fn breakdown(years: &[Value]) -> Result<Value> {
    let annual = inputs()?;
    let mut year_results = Vec::with_capacity(years.len());
    for row in years {
        let input = row["year"]
            .as_i64()
            .and_then(|year| annual.iter().find(|i| i64::from(i.year) == year));
        let units = input.map(rates);
        let mut components = Vec::with_capacity(6);
        for (index, (key, class, label, _, _)) in CLASSES.iter().enumerate() {
            let count = integer(row, &format!("{key}_count"))?;
            let unit = units.as_ref().map(|u| u[index]);
            components.push(
                json!({"classification":class,"classification_label":label,"count":count,
                "priced_count":if unit.is_some() {count} else {0},
                "unit_economic_cost":unit.map(|u|u.0),"unit_qaly_cost":unit.map(|u|u.1),
                "subtotal_economic":unit.map(|u|rate(count,u.0)),
                "subtotal_societal":unit.map(|u|rate(count,u.0+u.1))}),
            );
        }
        let vehicle = components.pop().context("Missing vehicle cost component")?;
        year_results.push(json!({"year":row["year"],"crash_count":row["crash_count"],"injury_costs":components,
            "vehicle_costs":vehicle,"total_economic":row["total_economic"],"total_societal":row["total_societal"],
            "coverage":coverage(row)?}));
    }
    let mut totals = json!({});
    for key in COVERAGE_COUNTS {
        totals[key] = json!(
            years
                .iter()
                .map(|r| integer(r, key))
                .collect::<Result<Vec<_>>>()?
                .iter()
                .sum::<i64>()
        );
    }
    let sum = |key: &str| -> Option<f64> {
        let values = year_results
            .iter()
            .filter_map(|y| y[key].as_f64())
            .collect::<Vec<_>>();
        if values.is_empty() && !years.is_empty() {
            None
        } else {
            Some((values.iter().sum::<f64>() * 100.0).round() / 100.0)
        }
    };
    let aggregate_component = |index: usize| -> Value {
        let rows = year_results
            .iter()
            .map(|y| {
                if index == 5 {
                    &y["vehicle_costs"]
                } else {
                    &y["injury_costs"][index]
                }
            })
            .collect::<Vec<_>>();
        let mut result =
            json!({"classification":CLASSES[index].1,"classification_label":CLASSES[index].2});
        for key in ["count", "priced_count"] {
            result[key] = json!(rows.iter().filter_map(|r| r[key].as_i64()).sum::<i64>());
        }
        for key in ["unit_economic_cost", "unit_qaly_cost"] {
            result[key] = if rows.len() == 1 {
                rows[0][key].clone()
            } else {
                Value::Null
            };
        }
        for key in ["subtotal_economic", "subtotal_societal"] {
            let values = rows
                .iter()
                .filter_map(|r| r[key].as_f64())
                .collect::<Vec<_>>();
            result[key] = if values.is_empty() && !rows.is_empty() {
                Value::Null
            } else {
                json!((values.iter().sum::<f64>() * 100.0).round() / 100.0)
            };
        }
        result
    };
    Ok(
        json!({"total_economic":sum("total_economic"),"total_societal":sum("total_societal"),
        "injury_costs":(0..5).map(aggregate_component).collect::<Vec<_>>(),"vehicle_costs":aggregate_component(5),
        "years":year_results,"coverage":coverage(&totals)?,"methodology":methodology()?}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_year_and_independent_adjustment_components_are_explicit() {
        let annual = inputs().unwrap();
        let base = annual.iter().find(|i| i.year == 2019).unwrap();
        let units = rates(base);
        assert_eq!(units[0], (1_606_644.0, 9_651_851.0));
        assert_eq!(units[4], (6_269.0, 3_927.0));
        assert_eq!(units[5], (7_913.0, 0.0));
        let year = annual.iter().find(|i| i.year == 2023).unwrap();
        assert_eq!(rates(year)[1], (205_209.66, 1_116_169.78));
        assert!(!annual.iter().any(|i| i.year == 2025 || i.year == 2026));
        let metadata = methodology().unwrap();
        assert_eq!(metadata["version"], VERSION);
        assert_eq!(metadata["source_url"], SOURCE);
        assert_eq!(metadata["base_dollar_year"], 2019);
        for row in metadata["annual_inputs"].as_array().unwrap() {
            let quarters = row["quarterly_earnings"].as_array().unwrap();
            assert_eq!(quarters.len(), 4);
            let average = quarters.iter().map(|q| q.as_f64().unwrap()).sum::<f64>() / 4.0;
            assert_eq!(row["muwe"], average);
        }
    }
}
