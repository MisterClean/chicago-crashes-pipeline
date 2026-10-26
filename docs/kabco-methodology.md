# Crash-year cost estimates

Location reports estimate economic and societal costs in the nominal dollar year
of each parent crash's Chicago-local date. A 2023 crash uses 2023-dollar rates;
a 2024 crash uses 2024-dollar rates. A multi-year total is a sum of those nominal
values, not an inflation-adjusted comparison in a common dollar year.

## Sources and adjustment

Method version: `fhwa-person-injury-crash-year-v1`.

The [FHWA October 2025 fact sheet](https://highways.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf)
provides person-injury KABCO and vehicle inputs in Step 1. Step 3 identifies their
dollar year as **2019**. Its final crash-unit table is in 2024 dollars and is a
different aggregation. Publication year, input dollar year and valuation year
are recorded separately.

Following the component adjustment described in Step 4, the application derives
annual person/vehicle rates using:

```
economic unit rate(year) = 2019 economic rate × CPI-U(year) / 255.657
QALY unit rate(year)     = 2019 QALY rate × mean quarterly earnings(year) / 917
societal unit rate      = economic unit rate + QALY unit rate
```

Each economic/QALY unit component is rounded to cents before multiplication.
Economic and QALY factors are separate. The USDOT value-of-statistical-life
series is not substituted for the full KABCO schedule. No state income adjustment
is applied.

Annual input observations and provenance are checked into
[`kabco_annual_inputs.json`](../rust/crashes-server/resources/kabco_annual_inputs.json):

- CPI-U: BLS `CUUR0000SA0`, all items, U.S. city average, not seasonally adjusted,
  published annual-average `M13` observations.
- Earnings: BLS `LEU0252881500`, median usual weekly earnings of full-time wage
  and salary workers, not seasonally adjusted. Use the arithmetic mean of all
  four quarterly medians, not a seasonally adjusted series or an annual median.
- API sources: [CPI-U](https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0)
  and [weekly earnings](https://api.bls.gov/publicAPI/v2/timeseries/data/LEU0252881500).
  Fetch 2013–2022 and 2023–2025 separately; unauthenticated requests allow at most
  ten years. Request `annualaverage=true` for CPI.

Supported years are **2013–2024**. BLS did not produce fourth-quarter 2025 earnings
because October observations were not collected during the government shutdown.
Its published 2025 CPI alone is insufficient. Full-year 2026 inputs are not yet
available. Neither year receives an older year's rates or a three-quarter proxy.
These are derived annual valuations under the FHWA method, not claims of a
separate federal KABCO publication for every year.

## Calculation and completeness

For each crash, sum every linked person's K/A/B/C/O components and every linked
vehicle record's economic component. The vehicle's base economic rate is $7,913
and QALY is zero. People and vehicle records are aggregated independently before
joining the parent; their own dates do not change the valuation year. This is a
record-based estimate; the vehicle dataset includes its provider's various unit
types. Counts and exports expose the included records for inspection.

Unknown/blank/unrecognized person classifications receive no inferred rate and
are not recoded as O. Missing people/vehicles or disagreement between known person
injuries and parent total/fatal/incapacitating counts flag incomplete inputs.
Other available parent injury-category counts (including O and unknown) and the
expected vehicle-unit count are also compared to linked records; mismatches are
reported separately for injuries and vehicles.
`complete` means those observed checks passed; it cannot prove that every child
record has been published upstream.

- `complete`: supported year, linked people/vehicles present, classifications known,
  and observed injury and vehicle counts agree with available parent counts.
- `partial`: at least one priced component, with incomplete input checks. The
  estimate includes **known components only**; excluded components are not zero.
- `unavailable`: no priced component or missing/unsupported crash year. Estimates
  are JSON `null` / empty CSV fields, displayed as “Unavailable”.
- Empty selections have zero totals and coverage status `empty`.

Report selection retains its existing geometry/date semantics. Crashes without
usable coordinates are outside a spatial report; missing dates are included only
when no date restriction excludes them. All selected crashes contribute to the
cost summary; only map points are capped.

This corrects the previous implementation's fixed label and PDO substitution:
2019-dollar rates were labeled `2024$`, O people were assigned zero, and PDO vehicle
records used O-person rates including QALY. Revised totals are therefore not
directly comparable with that former implementation.

## API and exports

`stats.cost_breakdown` includes overall and yearly classification costs, priced
record counts, coverage, and versioned source/annual-input metadata. Overall unit
rates are null across multiple years; expand a year for its actual rates. Headline
totals and map summaries disclose partial coverage.

Select the additive **`crash_costs`** export for one row per selected crash,
including its counts, rates, annual adjustment inputs, valuation/status fields,
and method/source identifiers. A standalone CSV carries that provenance in its
columns. ZIP manifests also include the full schedule. Existing raw `crashes`,
`people`, `vehicles`, and `vision_zero` CSV columns retain schema version 1.

Reports and exports use the same SQL calculations in their existing single read
snapshot. Costs are computed on read; accepted facts, ingestion, publication
receipts, ownership and historical values are unchanged. No production migration
is needed. Shipping this source change is separate from deploying it.

## Updating the schedule

Verify both BLS series and all required periods before adding a year. Record the
four earnings observations, CPI annual average, source retrieval date and any
limitations in the resource. Do not extrapolate an incomplete year. Change the
method version for a changed basis, rate revision or adjustment policy, preserve
source attribution, and update the supported-year UI text and regression cases.
The resource is included in the backend source digest. Existing exports retain
their recorded method metadata; new queries use the bundled schedule.

Regression tests cover independent 2023/2024 values, local year boundaries,
parent/child date differences, join fan-out, partial/unavailable/empty selections,
report/export reconciliation and exact existing export schemas.
