-- Shared by reports and streaming exports. Aggregate children independently so
-- a crash with several people and vehicles never multiplies either population.
cost_rates(year,cpi,muwe,k_e,k_q,a_e,a_q,b_e,b_q,c_e,c_q,o_e,o_q,vehicle_e) AS (
    VALUES __COST_RATES__
), cost_people AS (
    SELECT p.crash_record_id, count(*) AS person_count,
        count(*) FILTER (WHERE injury_classification='FATAL') AS k_count,
        count(*) FILTER (WHERE injury_classification='INCAPACITATING INJURY') AS a_count,
        count(*) FILTER (WHERE injury_classification='NONINCAPACITATING INJURY') AS b_count,
        count(*) FILTER (WHERE injury_classification='REPORTED, NOT EVIDENT') AS c_count,
        count(*) FILTER (WHERE injury_classification='NO INDICATION OF INJURY') AS o_count,
        count(*) FILTER (WHERE injury_classification IS NULL OR injury_classification NOT IN
            ('FATAL','INCAPACITATING INJURY','NONINCAPACITATING INJURY','REPORTED, NOT EVIDENT','NO INDICATION OF INJURY')) AS unknown_injury_count
    FROM crash_people p JOIN selected s USING(crash_record_id) GROUP BY p.crash_record_id
), cost_vehicles AS (
    SELECT v.crash_record_id, count(*) AS vehicle_count
    FROM crash_vehicles v JOIN selected s USING(crash_record_id) GROUP BY v.crash_record_id
), cost_inputs AS (
    SELECT s.crash_record_id, s.crash_date, year(s.crash_date)::INTEGER AS valuation_year,
        coalesce(p.person_count,0) AS person_count, coalesce(v.vehicle_count,0) AS vehicle_count,
        coalesce(p.k_count,0) AS k_count, coalesce(p.a_count,0) AS a_count,
        coalesce(p.b_count,0) AS b_count, coalesce(p.c_count,0) AS c_count,
        coalesce(p.o_count,0) AS o_count, coalesce(p.unknown_injury_count,0) AS unknown_injury_count,
        (s.injuries_total IS NULL OR s.injuries_fatal IS NULL OR s.injuries_incapacitating IS NULL
            OR s.injuries_total != coalesce(p.k_count+p.a_count+p.b_count+p.c_count,0)
            OR s.injuries_fatal != coalesce(p.k_count,0)
            OR s.injuries_incapacitating != coalesce(p.a_count,0)
            OR (s.injuries_non_incapacitating IS NOT NULL AND s.injuries_non_incapacitating != coalesce(p.b_count,0))
            OR (s.injuries_reported_not_evident IS NOT NULL AND s.injuries_reported_not_evident != coalesce(p.c_count,0))
            OR (s.injuries_no_indication IS NOT NULL AND s.injuries_no_indication != coalesce(p.o_count,0))
            OR (s.injuries_unknown IS NOT NULL AND s.injuries_unknown != coalesce(p.unknown_injury_count,0))) AS inconsistent_injuries,
        (s.num_units IS NOT NULL AND s.num_units != coalesce(v.vehicle_count,0)) AS inconsistent_vehicles
    FROM selected s LEFT JOIN cost_people p USING(crash_record_id)
    LEFT JOIN cost_vehicles v USING(crash_record_id)
), cost_values AS (
    SELECT i.*, r.cpi, r.muwe,
        CASE WHEN crash_date IS NULL THEN 'missing_date' WHEN r.year IS NULL THEN 'unsupported_year'
            ELSE 'supported' END AS valuation_status,
        CASE WHEN r.year IS NOT NULL THEN k_count+a_count+b_count+c_count+o_count+vehicle_count
            ELSE 0 END AS priced_component_count,
        k_count*k_e+a_count*a_e+b_count*b_e+c_count*c_e+o_count*o_e+vehicle_count*vehicle_e AS economic,
        k_count*k_q+a_count*a_q+b_count*b_q+c_count*c_q+o_count*o_q AS qaly
    FROM cost_inputs i LEFT JOIN cost_rates r ON i.valuation_year=r.year
), cost_crashes AS (
    SELECT *, CASE WHEN priced_component_count=0 THEN 'unavailable'
        WHEN unknown_injury_count>0 OR person_count=0 OR vehicle_count=0 OR inconsistent_injuries OR inconsistent_vehicles THEN 'partial'
        ELSE 'complete' END AS cost_status,
        CASE WHEN priced_component_count>0 THEN economic END AS estimated_economic_damages,
        CASE WHEN priced_component_count>0 THEN economic+qaly END AS estimated_societal_costs
    FROM cost_values
), cost_years AS (
    SELECT valuation_year AS year, count(*) AS crash_count,
        count(*) FILTER (WHERE cost_status='complete') AS complete_crashes,
        count(*) FILTER (WHERE cost_status='partial') AS partial_crashes,
        count(*) FILTER (WHERE cost_status='unavailable') AS unavailable_crashes,
        count(*) FILTER (WHERE person_count=0) AS missing_people_crashes,
        count(*) FILTER (WHERE vehicle_count=0) AS missing_vehicle_crashes,
        count(*) FILTER (WHERE inconsistent_injuries) AS inconsistent_injury_crashes,
        count(*) FILTER (WHERE inconsistent_vehicles) AS inconsistent_vehicle_crashes,
        sum(unknown_injury_count) AS unknown_injury_count,
        sum(k_count) AS k_count, sum(a_count) AS a_count, sum(b_count) AS b_count,
        sum(c_count) AS c_count, sum(o_count) AS o_count, sum(vehicle_count) AS vehicle_count,
        sum(estimated_economic_damages) AS total_economic,
        sum(estimated_societal_costs) AS total_societal
    FROM cost_crashes GROUP BY valuation_year
)
