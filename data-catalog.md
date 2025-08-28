# Chicago Traffic Crash Data Schema & Relationships

## Overview
The City of Chicago provides four interconnected datasets for traffic crash analysis, all sourced from the Chicago Police Department's electronic crash reporting system (E-Crash). These datasets follow the Illinois Department of Transportation SR1050 form format.

## Dataset Summary

| Dataset | Records | Columns | Primary Key | Description |
|---------|---------|---------|-------------|-------------|
| **Traffic Crashes - Crashes** | 979K | 48 | CRASH_RECORD_ID | Main crash event data |
| **Traffic Crashes - People** | 2.15M | 29 | PERSON_ID | Individual people involved in crashes |
| **Traffic Crashes - Vehicles** | 2M | 71 | CRASH_UNIT_ID | Vehicles/units involved in crashes |
| **Traffic Crashes - Vision Zero** | 921 | 8 | Person_ID | Traffic fatalities for Vision Zero program |

## Entity Relationship Diagram

```
┌─────────────────────────┐
│    CRASHES (979K)       │
│ ┌─────────────────────┐ │
│ │ CRASH_RECORD_ID (PK)│ │◄──┐
│ │ CRASH_DATE          │ │   │
│ │ POSTED_SPEED_LIMIT  │ │   │
│ │ WEATHER_CONDITION   │ │   │
│ │ LIGHTING_CONDITION  │ │   │
│ │ FIRST_CRASH_TYPE    │ │   │
│ │ ... (42 more cols)  │ │   │
│ └─────────────────────┘ │   │
└─────────────────────────┘   │
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     │                     ▼
┌─────────────────────────┐   │           ┌─────────────────────────┐
│    PEOPLE (2.15M)       │   │           │   VEHICLES (2M)         │
│ ┌─────────────────────┐ │   │           │ ┌─────────────────────┐ │
│ │ PERSON_ID (PK)      │ │   │           │ │ CRASH_UNIT_ID (PK)  │ │
│ │ CRASH_RECORD_ID (FK)│ │───┘           │ │ CRASH_RECORD_ID (FK)│ │───┘
│ │ VEHICLE_ID (FK)     │ │────────────┐  │ │ VEHICLE_ID          │ │
│ │ PERSON_TYPE         │ │            │  │ │ UNIT_TYPE           │ │
│ │ SEAT_NO             │ │            │  │ │ MAKE                │ │
│ │ AGE                 │ │            │  │ │ MODEL               │ │
│ │ SEX                 │ │            │  │ │ VEHICLE_YEAR        │ │
│ │ INJURY_CLASSIFICATION│ │           │  │ │ ... (64 more cols)  │ │
│ │ ... (21 more cols)  │ │            │  │ └─────────────────────┘ │
│ └─────────────────────┘ │            └──┤                       │
└─────────────────────────┘               └─────────────────────────┘
        │
        │
        ▼
┌─────────────────────────┐
│ VISION ZERO (921)       │
│ ┌─────────────────────┐ │
│ │ Person_ID (PK/FK)   │ │───┐
│ │ Crash_Date          │ │   │
│ │ Crash_Location      │ │   │
│ │ Victim              │ │   │
│ │ Crash_Circumstances │ │   │
│ │ Longitude           │ │   │
│ │ Latitude            │ │   │
│ └─────────────────────┘ │   │
└─────────────────────────┘   │
                              │
        ┌─────────────────────┘
        │ Links to PEOPLE.PERSON_ID
        ▼ (for fatality records only)
```

## Key Relationships & Join Patterns

### 1. **Core Relationship: CRASH_RECORD_ID**
- **Primary Table**: Crashes
- **Foreign Key in**: People, Vehicles
- **Relationship**: One crash can have multiple people and multiple vehicles
- **Join Pattern**: 
```sql
-- Get crash details with all people involved
SELECT c.*, p.*
FROM crashes c
LEFT JOIN people p ON c.crash_record_id = p.crash_record_id

-- Get crash details with all vehicles involved  
SELECT c.*, v.*
FROM crashes c
LEFT JOIN vehicles v ON c.crash_record_id = v.crash_record_id
```

### 2. **People-Vehicle Relationship: VEHICLE_ID**
- **Connection**: People.VEHICLE_ID → Vehicles.VEHICLE_ID
- **Relationship**: One vehicle can have multiple occupants (driver + passengers)
- **Special Cases**:
  - Pedestrians are independent "units" (one-to-one with vehicles table)
  - Vehicle occupants share the same VEHICLE_ID
  - PERSON_ID starting with "P" = passengers, "O" = others (driver, pedestrian, cyclist)

### 3. **Vision Zero Fatalities: PERSON_ID**
- **Connection**: Vision_Zero.Person_ID → People.PERSON_ID  
- **Relationship**: Subset relationship - only fatal crashes
- **Note**: Vision Zero uses standardized criteria that may differ from other crash datasets

## Data Hierarchies

### Crash Level (1:Many)
```
CRASH_RECORD_ID (Crashes)
├── Multiple PEOPLE records
└── Multiple VEHICLE/UNIT records
```

### Vehicle Level (1:Many)
```
VEHICLE_ID (Vehicles)  
├── Driver (PERSON_ID starting with O)
└── Multiple Passengers (PERSON_ID starting with P)
```

### Special Unit Types
- **Motor Vehicles**: Have occupants in People table
- **Pedestrians**: Appear as both a "unit" in Vehicles AND as a person in People
- **Cyclists**: Same pattern as pedestrians
- **Motorcyclists**: Separate unit type

## Key Fields for Analysis

### Crashes Table (Main Event Data)
- **CRASH_RECORD_ID**: Primary key, links to all other tables
- **CRASH_DATE**: Event timestamp
- **POSTED_SPEED_LIMIT**: Speed limit at crash location  
- **WEATHER_CONDITION**: Weather at time of crash
- **FIRST_CRASH_TYPE**: Primary collision type
- **TRAFFIC_CONTROL_DEVICE**: Stop sign, signal, etc.
- Location fields (street names, coordinates)

### People Table (Individual Outcomes)
- **PERSON_ID**: Unique person identifier
- **PERSON_TYPE**: Driver, passenger, pedestrian, cyclist
- **INJURY_CLASSIFICATION**: Injury severity
- **AGE, SEX**: Demographics
- **SEAT_NO**: Position in vehicle (driver=1, passenger positions 2-12)

### Vehicles Table (Unit Details)  
- **CRASH_UNIT_ID**: Unique vehicle/unit identifier
- **UNIT_TYPE**: Vehicle type (car, truck, pedestrian, bicycle)
- **VEHICLE_ID**: Links to people table
- **MAKE, MODEL, VEHICLE_YEAR**: Vehicle details
- Vehicle damage and defect information

### Vision Zero Table (Fatality Focus)
- **Person_ID**: Links to People table
- **Victim**: Activity type (pedestrian, cyclist, driver, etc.)
- **Crash_Circumstances**: Description of fatal crash
- **Longitude, Latitude**: Precise location

## Common Query Patterns

### 1. Complete Crash Analysis
```sql
SELECT 
    c.crash_record_id,
    c.crash_date,
    c.first_crash_type,
    COUNT(DISTINCT p.person_id) as total_people,
    COUNT(DISTINCT v.crash_unit_id) as total_units,
    SUM(CASE WHEN p.injury_classification = 'FATAL' THEN 1 ELSE 0 END) as fatalities
FROM crashes c
LEFT JOIN people p ON c.crash_record_id = p.crash_record_id  
LEFT JOIN vehicles v ON c.crash_record_id = v.crash_record_id
GROUP BY c.crash_record_id, c.crash_date, c.first_crash_type
```

### 2. Vehicle Occupant Analysis
```sql
SELECT 
    v.crash_record_id,
    v.vehicle_id,
    v.make,
    v.model,
    COUNT(p.person_id) as occupants,
    p.person_type
FROM vehicles v
LEFT JOIN people p ON v.vehicle_id = p.vehicle_id
WHERE v.unit_type IN ('MOTOR VEHICLE', 'TRUCK', 'BUS')
GROUP BY v.crash_record_id, v.vehicle_id, v.make, v.model, p.person_type
```

### 3. Vision Zero Fatality Details
```sql
SELECT 
    vz.*,
    p.age,
    p.sex,
    p.injury_classification,
    c.first_crash_type,
    c.weather_condition
FROM vision_zero vz
JOIN people p ON vz.person_id = p.person_id
JOIN crashes c ON p.crash_record_id = c.crash_record_id
```

## Data Quality Notes

1. **Time Period**: Citywide data available from September 2017 - present
2. **Reporting**: ~50% self-reported at police stations, 50% recorded at scene
3. **Updates**: Records can be amended after initial report
4. **Privacy**: RD_NO (police report numbers) removed as of November 2023
5. **Jurisdiction**: Only includes CPD jurisdiction (excludes expressways, some boundary areas)
6. **Vision Zero Criteria**: Uses standardized definition of "traffic fatality" that may differ from other sources

## Usage Recommendations

1. **Use CRASH_RECORD_ID** as primary join key between Crashes, People, and Vehicles
2. **Use VEHICLE_ID** to link people to their specific vehicle/unit
3. **Filter by date** >= September 2017 for complete citywide coverage
4. **Consider UNIT_TYPE** when analyzing vehicles (includes pedestrians, cyclists)
5. **Use Vision Zero dataset** for official fatality statistics and location analysis
6. **Account for data updates** - crashes can be amended after initial reporting

# Chicago Traffic Crash Data: Comprehensive Data Dictionary

## Overview

This comprehensive data dictionary covers four interconnected Chicago traffic crash datasets maintained by the Chicago Police Department and Chicago Department of Transportation. All data follows the Illinois Department of Transportation SR1050 Traffic Crash Report format and is updated daily (except Vision Zero, which updates monthly).

**Data Coverage**: 2015 to present (Citywide coverage from September 2017 onwards)  
**Last Updated**: August 27, 2025  
**Source**: City of Chicago Data Portal

---

## Dataset 1: Traffic Crashes - Crashes
**Dataset ID**: 85ca-t3if  
**Records**: 979K  
**Columns**: 48  
**Primary Key**: CRASH_RECORD_ID  
**Description**: Main crash event data containing information about each traffic crash on city streets within Chicago Police Department jurisdiction.

### Dataset Description
Crash data shows information about each traffic crash on city streets within the City of Chicago limits and under the jurisdiction of Chicago Police Department (CPD). Data are shown as is from the electronic crash reporting system (E-Crash) at CPD, excluding any personally identifiable information. Records are added to the data portal when a crash report is finalized or when amendments are made to an existing report in E-Crash. Data from E-Crash are available for some police districts in 2015, but citywide data are not available until September 2017. About half of all crash reports, mostly minor crashes, are self-reported at the police district by the driver(s) involved and the other half are recorded at the scene by the police officer responding to the crash. Many of the crash parameters, including street condition data, weather condition, and posted speed limits, are recorded by the reporting officer based on best available information at the time, but many of these may disagree with posted information or other assessments on road conditions. If any new or updated information on a crash is received, the reporting officer may amend the crash report at a later time. A traffic crash within the city limits for which CPD is not the responding police agency, typically crashes on interstate highways, freeway ramps, and on local roads along the City boundary, are excluded from this dataset.

All crashes are recorded as per the format specified in the Traffic Crash Report, SR1050, of the Illinois Department of Transportation. The crash data published on the Chicago data portal mostly follows the data elements in SR1050 form.

As per Illinois statute, only crashes with a property damage value of $1,500 or more or involving bodily injury to any person(s) and that happen on a public roadway and that involve at least one moving vehicle, except bike dooring, are considered reportable crashes. However, CPD records every reported traffic crash event, regardless of the statute of limitations, and hence any formal Chicago crash dataset released by Illinois Department of Transportation may not include all the crashes listed here.

**Change 11/21/2023**: RD_NO (Chicago Police Department report number) removed for privacy reasons.

### Complete Column Definitions

| Column Name | Description | Data Type | API Field |
|-------------|-------------|-----------|-----------|
| **CRASH_RECORD_ID** | This number can be used to link to the same crash in the Vehicles and People datasets. This number also serves as a unique ID in this dataset. | Text | crash_record_id |
| **CRASH_DATE_EST_I** | Crash date estimated by desk officer or reporting party (only used in cases where crash is reported at police station days after the crash) | Text | crash_date_est_i |
| **CRASH_DATE** | Date and time of crash as entered by the reporting officer | Floating Timestamp | crash_date |
| **POSTED_SPEED_LIMIT** | Posted speed limit, as determined by reporting officer | Number | posted_speed_limit |
| **TRAFFIC_CONTROL_DEVICE** | Traffic control device present at crash location, as determined by reporting officer | Text | traffic_control_device |
| **DEVICE_CONDITION** | Condition of traffic control device, as determined by reporting officer | Text | device_condition |
| **WEATHER_CONDITION** | Weather condition at time of crash, as determined by reporting officer | Text | weather_condition |
| **LIGHTING_CONDITION** | Light condition at time of crash, as determined by reporting officer | Text | lighting_condition |
| **FIRST_CRASH_TYPE** | Type of first collision in crash | Text | first_crash_type |
| **TRAFFICWAY_TYPE** | Trafficway type, as determined by reporting officer | Text | trafficway_type |
| **LANE_CNT** | Total number of through lanes in either direction, excluding turn lanes, as determined by reporting officer (0 = intersection) | Number | lane_cnt |
| **ALIGNMENT** | Street alignment at crash location, as determined by reporting officer | Text | alignment |
| **ROADWAY_SURFACE_COND** | Road surface condition, as determined by reporting officer | Text | roadway_surface_cond |
| **ROAD_DEFECT** | Road defects, as determined by reporting officer | Text | road_defect |
| **REPORT_TYPE** | Administrative report type (at scene, at desk, amended) | Text | report_type |
| **CRASH_TYPE** | A general severity classification for the crash. Can be either Injury and/or Tow Due to Crash or No Injury / Drive Away | Text | crash_type |
| **INTERSECTION_RELATED_I** | A field observation by the police officer whether an intersection played a role in the crash. Does not represent whether or not the crash occurred within the intersection. | Text | intersection_related_i |
| **NOT_RIGHT_OF_WAY_I** | Whether the crash begun or first contact was made outside of the public right-of-way. | Text | private_property_i |
| **HIT_AND_RUN_I** | Crash did/did not involve a driver who caused the crash and fled the scene without exchanging information and/or rendering aid | Text | hit_and_run_i |
| **DAMAGE** | A field observation of estimated damage. | Text | damage |
| **DATE_POLICE_NOTIFIED** | Calendar date on which police were notified of the crash | Floating Timestamp | date_police_notified |
| **PRIM_CONTRIBUTORY_CAUSE** | The factor which was most significant in causing the crash, as determined by officer judgment | Text | prim_contributory_cause |
| **SEC_CONTRIBUTORY_CAUSE** | The factor which was second most significant in causing the crash, as determined by officer judgment | Text | sec_contributory_cause |
| **STREET_NO** | Street address number of crash location, as determined by reporting officer | Number | street_no |
| **STREET_DIRECTION** | Street address direction (N,E,S,W) of crash location, as determined by reporting officer | Text | street_direction |
| **STREET_NAME** | Street address name of crash location, as determined by reporting officer | Text | street_name |
| **BEAT_OF_OCCURRENCE** | Chicago Police Department Beat ID. Boundaries available at https://data.cityofchicago.org/d/aerh-rz74 | Number | beat_of_occurrence |
| **PHOTOS_TAKEN_I** | Whether the Chicago Police Department took photos at the location of the crash | Text | photos_taken_i |
| **STATEMENTS_TAKEN_I** | Whether statements were taken from unit(s) involved in crash | Text | statements_taken_i |
| **DOORING_I** | Whether crash involved a motor vehicle occupant opening a door into the travel path of a bicyclist, causing a crash | Text | dooring_i |
| **WORK_ZONE_I** | Whether the crash occurred in an active work zone | Text | work_zone_i |
| **WORK_ZONE_TYPE** | The type of work zone, if any | Text | work_zone_type |
| **WORKERS_PRESENT_I** | Whether construction workers were present in an active work zone at crash location | Text | workers_present_i |
| **NUM_UNITS** | Number of units involved in the crash. A unit can be a motor vehicle, a pedestrian, a bicyclist, or another non-passenger roadway user. Each unit represents a mode of traffic with an independent trajectory. | Number | num_units |
| **MOST_SEVERE_INJURY** | Most severe injury sustained by any person involved in the crash | Text | most_severe_injury |
| **INJURIES_TOTAL** | Total persons sustaining fatal, incapacitating, non-incapacitating, and possible injuries as determined by the reporting officer | Number | injuries_total |
| **INJURIES_FATAL** | Total persons sustaining fatal injuries in the crash | Number | injuries_fatal |
| **INJURIES_INCAPACITATING** | Total persons sustaining incapacitating/serious injuries in the crash as determined by the reporting officer. Any injury other than fatal injury, which prevents the injured person from walking, driving, or normally continuing the activities they were capable of performing before the injury occurred. Includes severe lacerations, broken limbs, skull or chest injuries, and abdominal injuries. | Number | injuries_incapacitating |
| **INJURIES_NON_INCAPACITATING** | Total persons sustaining non-incapacitating injuries in the crash as determined by the reporting officer. Any injury, other than fatal or incapacitating injury, which is evident to observers at the scene of the crash. Includes lump on head, abrasions, bruises, and minor lacerations. | Number | injuries_non_incapacitating |
| **INJURIES_REPORTED_NOT_EVIDENT** | Total persons sustaining possible injuries in the crash as determined by the reporting officer. Includes momentary unconsciousness, claims of injuries not evident, limping, complaint of pain, nausea, and hysteria. | Number | injuries_reported_not_evident |
| **INJURIES_NO_INDICATION** | Total persons sustaining no injuries in the crash as determined by the reporting officer | Number | injuries_no_indication |
| **INJURIES_UNKNOWN** | Total persons for whom injuries sustained, if any, are unknown | Number | injuries_unknown |
| **CRASH_HOUR** | The hour of the day component of CRASH_DATE. | Number | crash_hour |
| **CRASH_DAY_OF_WEEK** | The day of the week component of CRASH_DATE. Sunday=1 | Number | crash_day_of_week |
| **CRASH_MONTH** | The month component of CRASH_DATE. | Number | crash_month |
| **LATITUDE** | The latitude of the crash location, as determined by reporting officer, as derived from the reported address of crash | Number | latitude |
| **LONGITUDE** | The longitude of the crash location, as determined by reporting officer, as derived from the reported address of crash | Number | longitude |
| **LOCATION** | The crash location, as determined by reporting officer, as derived from the reported address of crash, in a column type that allows for mapping and other geographic analysis in the data portal software | Point | location |
| **Boundaries - ZIP Codes** | This column was automatically created in order to record in what polygon from the dataset 'Boundaries - ZIP Codes' (rpca-8um6) the point in column 'location' is located. This enables the creation of region maps (choropleths) in the visualization canvas and data lens. | Number | :@computed_region_rpca_8um6 |

---

## Dataset 2: Traffic Crashes - People
**Dataset ID**: u6pd-qa9d  
**Records**: 2.15M  
**Columns**: 29  
**Primary Key**: PERSON_ID  
**Description**: Information about people involved in crashes and injuries sustained.

### Dataset Description
This data contains information about people involved in a crash and if any injuries were sustained. This dataset should be used in combination with the traffic Crash and Vehicle dataset. Each record corresponds to an occupant in a vehicle listed in the Crash dataset. Some people involved in a crash may not have been an occupant in a motor vehicle, but may have been a pedestrian, bicyclist, or using another non-motor vehicle mode of transportation. Injuries reported are reported by the responding police officer. Fatalities that occur after the initial reports are typically updated in these records up to 30 days after the date of the crash. Person data can be linked with the Crash and Vehicle dataset using the "CRASH_RECORD_ID" field. A vehicle can have multiple occupants and hence have a one to many relationship between Vehicle and Person dataset. However, a pedestrian is a "unit" by itself and have a one to one relationship between the Vehicle and Person table.

The Chicago Police Department reports crashes on IL Traffic Crash Reporting form SR1050. The crash data published on the Chicago data portal mostly follows the data elements in SR1050 form.

**Change 11/21/2023**: RD_NO (Chicago Police Department report number) removed for privacy reasons.

### Complete Column Definitions

| Column Name | Description | Data Type | API Field |
|-------------|-------------|-----------|-----------|
| **PERSON_ID** | A unique identifier for each person record. IDs starting with P indicate passengers. IDs starting with O indicate a person who was not a passenger in the vehicle (e.g., driver, pedestrian, cyclist, etc.). | Text | person_id |
| **PERSON_TYPE** | Type of roadway user involved in crash | Text | person_type |
| **CRASH_RECORD_ID** | This number can be used to link to the same crash in the Crashes and Vehicles datasets. This number also serves as a unique ID in the Crashes dataset. | Text | crash_record_id |
| **VEHICLE_ID** | The corresponding CRASH_UNIT_ID from the Vehicles dataset. | Text | vehicle_id |
| **CRASH_DATE** | Date and time of crash as entered by the reporting officer | Floating Timestamp | crash_date |
| **SEAT_NO** | Code for seating position of motor vehicle occupant: 1= driver, 2= center front, 3 = front passenger, 4 = second row left, 5 = second row center, 6 = second row right, 7 = enclosed passengers, 8 = exposed passengers, 9= unknown position, 10 = third row left, 11 = third row center, 12 = third row right | Text | seat_no |
| **CITY** | City of residence of person involved in crash | Text | city |
| **STATE** | State of residence of person involved in crash | Text | state |
| **ZIPCODE** | ZIP Code of residence of person involved in crash | Text | zipcode |
| **SEX** | Gender of person involved in crash, as determined by reporting officer | Text | sex |
| **AGE** | Age of person involved in crash | Number | age |
| **DRIVERS_LICENSE_STATE** | State issuing driver's license of person involved in crash | Text | drivers_license_state |
| **DRIVERS_LICENSE_CLASS** | Class of driver's license of person involved in crash | Text | drivers_license_class |
| **SAFETY_EQUIPMENT** | Safety equipment used by vehicle occupant in crash, if any | Text | safety_equipment |
| **AIRBAG_DEPLOYED** | Whether vehicle occupant airbag deployed as result of crash | Text | airbag_deployed |
| **EJECTION** | Whether vehicle occupant was ejected or extricated from the vehicle as a result of crash | Text | ejection |
| **INJURY_CLASSIFICATION** | Severity of injury person sustained in the crash | Text | injury_classification |
| **HOSPITAL** | Hospital to which person injured in the crash was taken | Text | hospital |
| **EMS_AGENCY** | EMS agency who transported person injured in crash to the hospital | Text | ems_agency |
| **EMS_RUN_NO** | EMS agency run number | Text | ems_run_no |
| **DRIVER_ACTION** | Driver action that contributed to the crash, as determined by reporting officer | Text | driver_action |
| **DRIVER_VISION** | What, if any, objects obscured the driver's vision at time of crash | Text | driver_vision |
| **PHYSICAL_CONDITION** | Driver's apparent physical condition at time of crash, as observed by the reporting officer | Text | physical_condition |
| **PEDPEDAL_ACTION** | Action of pedestrian or cyclist at the time of crash | Text | pedpedal_action |
| **PEDPEDAL_VISIBILITY** | Visibility of pedestrian of cyclist safety equipment in use at time of crash | Text | pedpedal_visibility |
| **PEDPEDAL_LOCATION** | Location of pedestrian or cyclist at the time of crash | Text | pedpedal_location |
| **BAC_RESULT** | Status of blood alcohol concentration testing for driver or other person involved in crash | Text | bac_result |
| **BAC_RESULT VALUE** | Driver's blood alcohol concentration test result (fatal crashes may include pedestrian or cyclist results) | Number | bac_result_value |
| **CELL_PHONE_USE** | Whether person was/was not using cellphone at the time of the crash, as determined by the reporting officer | Text | cell_phone_use |

---

## Dataset 3: Traffic Crashes - Vehicles
**Dataset ID**: 68nd-jvt3  
**Records**: 2M  
**Columns**: 71  
**Primary Key**: CRASH_UNIT_ID  
**Description**: Information about vehicles (units) involved in traffic crashes.

### Dataset Description
This dataset contains information about vehicles (or units as they are identified in crash reports) involved in a traffic crash. This dataset should be used in conjunction with the traffic Crash and People dataset available in the portal. "Vehicle" information includes motor vehicle and non-motor vehicle modes of transportation, such as bicycles and pedestrians. Each mode of transportation involved in a crash is a "unit" and get one entry here. Each vehicle, each pedestrian, each motorcyclist, and each bicyclist is considered an independent unit that can have a trajectory separate from the other units. However, people inside a vehicle including the driver do not have a trajectory separate from the vehicle in which they are travelling and hence only the vehicle they are travelling in get any entry here. This type of identification of "units" is needed to determine how each movement affected the crash. Data for occupants who do not make up an independent unit, typically drivers and passengers, are available in the People table. Many of the fields are coded to denote the type and location of damage on the vehicle. Vehicle information can be linked back to Crash data using the "CRASH_RECORD_ID" field. Since this dataset is a combination of vehicles, pedestrians, and pedal cyclists not all columns are applicable to each record. Look at the Unit Type field to determine what additional data may be available for that record.

The Chicago Police Department reports crashes on IL Traffic Crash Reporting form SR1050. The crash data published on the Chicago data portal mostly follows the data elements in SR1050 form.

**Change 11/21/2023**: RD_NO (Chicago Police Department report number) removed for privacy reasons.

### Complete Column Definitions

| Column Name | Description | Data Type | API Field |
|-------------|-------------|-----------|-----------|
| **CRASH_UNIT_ID** | A unique identifier for each vehicle record. | Number | crash_unit_id |
| **CRASH_RECORD_ID** | This number can be used to link to the same crash in the Crashes and People datasets. This number also serves as a unique ID in the Crashes dataset. | Text | crash_record_id |
| **CRASH_DATE** | Date and time of crash as entered by the reporting officer | Floating Timestamp | crash_date |
| **UNIT_NO** | A unique ID for each unit within a specific crash report. | Number | unit_no |
| **UNIT_TYPE** | The type of unit | Text | unit_type |
| **NUM_PASSENGERS** | Number of passengers in the vehicle. The driver is not included. More information on passengers is in the People dataset. | Number | num_passengers |
| **VEHICLE_ID** | | Number | vehicle_id |
| **CMRC_VEH_I** | | Text | cmrc_veh_i |
| **MAKE** | The make (brand) of the vehicle, if relevant | Text | make |
| **MODEL** | The model of the vehicle, if relevant | Text | model |
| **LIC_PLATE_STATE** | The state issuing the license plate of the vehicle, if relevant | Text | lic_plate_state |
| **VEHICLE_YEAR** | The model year of the vehicle, if relevant | Number | vehicle_year |
| **VEHICLE_DEFECT** | | Text | vehicle_defect |
| **VEHICLE_TYPE** | The type of vehicle, if relevant | Text | vehicle_type |
| **VEHICLE_USE** | The normal use of the vehicle, if relevant | Text | vehicle_use |
| **TRAVEL_DIRECTION** | The direction in which the unit was traveling prior to the crash, as determined by the reporting officer | Text | travel_direction |
| **MANEUVER** | The action the unit was taking prior to the crash, as determined by the reporting officer | Text | maneuver |
| **TOWED_I** | Indicator of whether the vehicle was towed | Text | towed_i |
| **FIRE_I** | | Text | fire_i |
| **OCCUPANT_CNT** | The number of people in the unit, as determined by the reporting officer | Number | occupant_cnt |
| **EXCEED_SPEED_LIMIT_I** | Indicator of whether the unit was speeding, as determined by the reporting officer | Text | exceed_speed_limit_i |
| **TOWED_BY** | Entity that towed the unit, if relevant | Text | towed_by |
| **TOWED_TO** | Location to which the unit was towed, if relevant | Text | towed_to |
| **AREA_00_I** | | Text | area_00_i |
| **AREA_01_I** | | Text | area_01_i |
| **AREA_02_I** | | Text | area_02_i |
| **AREA_03_I** | | Text | area_03_i |
| **AREA_04_I** | | Text | area_04_i |
| **AREA_05_I** | | Text | area_05_i |
| **AREA_06_I** | | Text | area_06_i |
| **AREA_07_I** | | Text | area_07_i |
| **AREA_08_I** | | Text | area_08_i |
| **AREA_09_I** | | Text | area_09_i |
| **AREA_10_I** | | Text | area_10_i |
| **AREA_11_I** | | Text | area_11_i |
| **AREA_12_I** | | Text | area_12_i |
| **AREA_99_I** | | Text | area_99_i |
| **FIRST_CONTACT_POINT** | | Text | first_contact_point |
| **CMV_ID** | | Number | cmv_id |
| **USDOT_NO** | | Text | usdot_no |
| **CCMC_NO** | | Text | ccmc_no |
| **ILCC_NO** | | Text | ilcc_no |
| **COMMERCIAL_SRC** | | Text | commercial_src |
| **GVWR** | | Text | gvwr |
| **CARRIER_NAME** | | Text | carrier_name |
| **CARRIER_STATE** | | Text | carrier_state |
| **CARRIER_CITY** | | Text | carrier_city |
| **HAZMAT_PLACARDS_I** | | Text | hazmat_placards_i |
| **HAZMAT_NAME** | | Text | hazmat_name |
| **UN_NO** | | Text | un_no |
| **HAZMAT_PRESENT_I** | | Text | hazmat_present_i |
| **HAZMAT_REPORT_I** | | Text | hazmat_report_i |
| **HAZMAT_REPORT_NO** | | Text | hazmat_report_no |
| **MCS_REPORT_I** | | Text | mcs_report_i |
| **MCS_REPORT_NO** | | Text | mcs_report_no |
| **HAZMAT_VIO_CAUSE_CRASH_I** | | Text | hazmat_vio_cause_crash_i |
| **MCS_VIO_CAUSE_CRASH_I** | | Text | mcs_vio_cause_crash_i |
| **IDOT_PERMIT_NO** | | Text | idot_permit_no |
| **WIDE_LOAD_I** | | Text | wide_load_i |
| **TRAILER1_WIDTH** | | Text | trailer1_width |
| **TRAILER2_WIDTH** | | Text | trailer2_width |
| **TRAILER1_LENGTH** | | Number | trailer1_length |
| **TRAILER2