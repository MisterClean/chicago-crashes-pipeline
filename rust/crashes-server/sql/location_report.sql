WITH selected AS MATERIALIZED (
    SELECT crash_record_id, crash_date, injuries_total, injuries_fatal,
        injuries_incapacitating, injuries_non_incapacitating, injuries_reported_not_evident,
        injuries_no_indication, injuries_unknown, num_units, hit_and_run_i, crash_type, street_name,
        prim_contributory_cause, longitude, latitude, geometry
    FROM (__SELECTION__)
), __COST_CTES__, people AS MATERIALIZED (
    SELECT p.person_type, p.injury_classification, p.age
    FROM crash_people p JOIN selected c USING(crash_record_id)
), crash_stats AS (
    SELECT count(*) AS total_crashes,
        coalesce(sum(injuries_total),0)::BIGINT AS total_injuries,
        coalesce(sum(injuries_fatal),0)::BIGINT AS total_fatalities,
        coalesce(sum(injuries_incapacitating),0)::BIGINT AS incapacitating_injuries,
        count(*) FILTER (WHERE injuries_total>0) AS crashes_with_injuries,
        count(*) FILTER (WHERE injuries_fatal>0) AS crashes_with_fatalities,
        count(*) FILTER (WHERE hit_and_run_i='Y') AS hit_and_run_count
    FROM selected
), people_stats AS (
    SELECT count(*) FILTER (WHERE person_type ILIKE '%PEDESTRIAN%') AS pedestrians_involved,
        count(*) FILTER (WHERE __CYCLIST__) AS cyclists_involved,
        count(*) FILTER (WHERE injury_classification IS NULL OR injury_classification NOT IN (__KNOWN__)) AS unknown_injury_count,
        count(*) FILTER (WHERE age>=0 AND age<18 AND injury_classification IN
            ('FATAL','INCAPACITATING INJURY','NONINCAPACITATING INJURY','REPORTED, NOT EVIDENT')) AS children_injured
    FROM people
), vehicle_stats AS (
    SELECT count(*) AS total_vehicles
    FROM crash_vehicles v JOIN selected c USING(crash_record_id)
), causes AS (
    SELECT coalesce(nullif(prim_contributory_cause,''),'UNKNOWN') AS cause, prim_contributory_cause AS source,
        count(*) AS crashes, coalesce(sum(injuries_total),0)::BIGINT AS injuries,
        coalesce(sum(injuries_fatal),0)::BIGINT AS fatalities,
        round(count(*)*100.0/greatest((SELECT total_crashes FROM crash_stats),1),1) AS percentage
    FROM selected GROUP BY prim_contributory_cause
    ORDER BY crashes DESC, cause, prim_contributory_cause NULLS FIRST LIMIT 15
), monthly AS (
    SELECT strftime(crash_date,'%Y-%m') AS month, count(*) AS crashes,
        coalesce(sum(injuries_total),0)::BIGINT AS injuries,
        coalesce(sum(injuries_fatal),0)::BIGINT AS fatalities
    FROM selected GROUP BY 1 ORDER BY 1
), hourly AS (
    SELECT isodow(crash_date)-1 AS day, hour(crash_date) AS hour, count(*) AS crashes,
        count(*) FILTER (WHERE injuries_total>0) AS injury_crashes,
        count(*) FILTER (WHERE injuries_fatal>0 OR injuries_incapacitating>0) AS severe_crashes
    FROM selected GROUP BY 1,2
), heatmap AS (
    SELECT d.day, h.hour, coalesce(x.crashes,0) AS crashes,
        coalesce(x.injury_crashes,0) AS injury_crashes, coalesce(x.severe_crashes,0) AS severe_crashes
    FROM range(7) d(day) CROSS JOIN range(24) h(hour)
    LEFT JOIN hourly x ON x.day=d.day AND x.hour=h.hour ORDER BY d.day,h.hour
), road_users AS (
    SELECT CASE WHEN person_type ILIKE '%PEDESTRIAN%' THEN 'Pedestrian'
        WHEN person_type ILIKE '%BICYCLE%' OR person_type ILIKE '%CYCLIST%' THEN 'Cyclist'
        WHEN person_type='DRIVER' THEN 'Driver' WHEN person_type='PASSENGER' THEN 'Passenger'
        ELSE 'Other / unknown' END AS road_user,
        count(*) AS people, count(*) FILTER (WHERE injury_classification='FATAL') AS fatal,
        count(*) FILTER (WHERE injury_classification='INCAPACITATING INJURY') AS incapacitating,
        count(*) FILTER (WHERE injury_classification IN ('NONINCAPACITATING INJURY','REPORTED, NOT EVIDENT')) AS other_injury,
        count(*) FILTER (WHERE injury_classification='NO INDICATION OF INJURY') AS no_injury,
        count(*) FILTER (WHERE injury_classification IS NULL OR injury_classification NOT IN (__KNOWN__)) AS unknown
    FROM people GROUP BY 1 ORDER BY people DESC,road_user
), map_points AS (
    SELECT s.crash_record_id, strftime(s.crash_date,'%Y-%m-%dT%H:%M:%S.%f') AS crash_date,
        injuries_total, injuries_fatal, injuries_incapacitating, hit_and_run_i,
        crash_type, street_name, prim_contributory_cause, ST_X(geometry) AS longitude, ST_Y(geometry) AS latitude,
        costs.valuation_year, costs.valuation_status, costs.cost_status,
        costs.estimated_economic_damages, costs.estimated_societal_costs
    FROM selected s JOIN cost_crashes costs USING(crash_record_id)
    ORDER BY s.crash_date DESC,s.crash_record_id LIMIT 5000
)
SELECT to_json(struct_pack(
    stats := (SELECT c FROM (SELECT * FROM crash_stats CROSS JOIN people_stats CROSS JOIN vehicle_stats) c),
    cost_years := coalesce((SELECT list(y ORDER BY year NULLS LAST) FROM cost_years y),[]),
    causes := coalesce((SELECT list(struct_pack(cause := c.cause, crashes := c.crashes, injuries := c.injuries, fatalities := c.fatalities, percentage := c.percentage) ORDER BY c.crashes DESC,c.cause,c.source NULLS FIRST) FROM causes c),[]),
    monthly_trends := coalesce((SELECT list(m ORDER BY m.month) FROM monthly m),[]),
    hour_day_counts := (SELECT list(h ORDER BY h.day,h.hour) FROM heatmap h),
    road_user_severity := coalesce((SELECT list(r ORDER BY r.people DESC,r.road_user) FROM road_users r),[]),
    map_points := coalesce((SELECT list(m ORDER BY m.crash_date DESC,m.crash_record_id) FROM map_points m),[])
))::VARCHAR AS payload
