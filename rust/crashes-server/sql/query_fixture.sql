CREATE TABLE crashes (
    crash_record_id VARCHAR, crash_date TIMESTAMP, latitude DOUBLE, longitude DOUBLE, geometry GEOMETRY,
    injuries_total BIGINT, injuries_fatal BIGINT, injuries_incapacitating BIGINT,
    hit_and_run_i VARCHAR, prim_contributory_cause VARCHAR, crash_type VARCHAR,street_name VARCHAR
);
CREATE TABLE crash_people (crash_record_id VARCHAR, person_id VARCHAR, crash_date TIMESTAMP,
    person_type VARCHAR, injury_classification VARCHAR, age INTEGER);
CREATE TABLE crash_vehicles (crash_unit_id VARCHAR,crash_record_id VARCHAR);
CREATE TABLE spatial_layers (id BIGINT, name VARCHAR, feature_count BIGINT,is_active BOOLEAN,label_field VARCHAR,sort_type VARCHAR);
CREATE TABLE spatial_layer_features (id BIGINT,layer_id BIGINT,properties JSON,geometry GEOMETRY);
INSERT INTO crashes (crash_record_id,crash_date,latitude,longitude,geometry,injuries_total,injuries_fatal,
    injuries_incapacitating,hit_and_run_i,prim_contributory_cause) VALUES
    ('a','2024-01-15 22:30',41.75,-87.65,ST_Point(-87.65,41.75),1,0,1,'Y','FOLLOWING TOO CLOSELY'),
    ('b','2024-01-31 23:59:59.999999',41.8,-87.6,ST_Point(-87.6,41.8),0,0,0,'N',NULL),
    ('c','2024-02-01',41.75,-87.7,ST_Point(-87.7,41.75),0,0,0,'N',NULL),
    ('d','2024-03-02',41.75,-87.649,ST_Point(-87.649,41.75),0,0,0,'N',NULL),
    ('e','2024-01-20',NULL,NULL,NULL,0,0,0,'N',NULL);
INSERT INTO crash_people VALUES
    ('a','p1','2024-02-01','PEDESTRIAN','INCAPACITATING INJURY',12),
    ('a','p2','2024-02-01','PASSENGER',NULL,40),
    ('d','p3','2024-01-15','PEDALCYCLIST','NO INDICATION OF INJURY',25);
INSERT INTO crash_vehicles VALUES ('v1','a'),('v2','a'),('v3','a'),('v4','d'),('v5','d');
INSERT INTO spatial_layers VALUES (4,'Communities',3,true,'district','numeric');
INSERT INTO spatial_layer_features
    SELECT id,4,json_object('district',district),ST_GeomFromGeoJSON('{"type":"Polygon","coordinates":[[[-87.7,41.7],[-87.5,41.7],[-87.5,41.9],[-87.7,41.9],[-87.7,41.7]],[[-87.61,41.79],[-87.59,41.79],[-87.59,41.81],[-87.61,41.81],[-87.61,41.79]]]}')
    FROM (VALUES (259,10),(260,2),(261,1)) t(id,district);
