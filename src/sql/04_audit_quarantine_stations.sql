-- Script: 04_audit_quarantine_stations.sql
-- Description: Diagnostic queries to analyze and categorize data quality issues in quarantine_stations.

-- 1. Summary of quarantine records grouped by failure reason
SELECT 
    quarantine_reason, 
    COUNT(*) AS records_count
FROM quarantine_stations
GROUP BY quarantine_reason
ORDER BY records_count DESC;

-- 2. Analyze coordinate shifts for stations with matching business codes
SELECT 
    q.station_code,
    q.station_name AS api_station_name,
    d.station_name AS dwh_station_name,
    q.gegr_lat AS api_lat,
    d.gegr_lat AS dwh_lat,
    q.gegr_lon AS api_lon,
    d.gegr_lon AS dwh_lon,
    d.station_address as dwh_address,
    ABS(q.gegr_lat - d.gegr_lat) AS lat_diff,
    ABS(q.gegr_lon - d.gegr_lon) AS lon_diff
FROM quarantine_stations q
JOIN dim_stations d ON q.station_code = d.station_code
WHERE q.quarantine_reason = 'Business key matches, but coordinates differ';

-- 3. Diagnostic: Find quarantine traces for active DWH stations that lost API connectivity
SELECT 
    d.station_code AS dwh_code,
    d.station_name AS dwh_name,
    d.gegr_lat AS dwh_lat,
    d.gegr_lon AS dwh_lon,
    q.station_code AS quarantine_code,
    q.station_name AS quarantine_name,
    q.gegr_lat AS q_lat,
    q.gegr_lon AS q_lon,
    -- Calculate coordinate difference in degrees
    ABS(q.gegr_lat - d.gegr_lat) AS lat_diff,
    ABS(q.gegr_lon - d.gegr_lon) AS lon_diff,
    q.quarantine_reason
FROM dim_stations d
-- Cross-join to detect potential spatial matches within a defined search radius
CROSS JOIN quarantine_stations q
WHERE d.is_active = TRUE 
  AND d.api_station_id IS NULL
  -- Restrict search boundary to approximately ~10-15 km radius
  AND ABS(q.gegr_lat - d.gegr_lat) < 0.1
  AND ABS(q.gegr_lon - d.gegr_lon) < 0.1
  AND q.quarantine_reason = 'Nothing matches: station code and coordinates are completely new'
ORDER BY d.station_code, lat_diff;

-- 4. Find stations where coordinates match but business codes have changed
SELECT 
    q.station_code AS api_station_code,
    d.station_code AS dwh_station_code,
    q.station_name AS api_station_name,
    d.station_name AS dwh_station_name,
    q.gegr_lat,
    q.gegr_lon
FROM quarantine_stations q
JOIN dim_stations d 
  ON ROUND(d.gegr_lat::numeric, 4) = ROUND(q.gegr_lat::numeric, 4)
 AND ROUND(d.gegr_lon::numeric, 4) = ROUND(q.gegr_lon::numeric, 4)
WHERE q.quarantine_reason = 'Coordinates match, but business code differs';

-- 5. Retrieve completely new stations that failed all matching criteria
SELECT 
    station_code,
    station_name,
    city_name,
    voivodeship,
    gegr_lat,
    gegr_lon
FROM quarantine_stations
WHERE quarantine_reason = 'Nothing matches: station code and coordinates are completely new';

-- 6. Search among quarantine "strangers" for stations located in the same city (via dim_cities) 
-- but having different codes or coordinates compared to historical reference data
SELECT 
    q.station_code AS api_code,
    q.station_name AS api_name,
    q.city_name AS api_city_text,
    dc.city_name AS dwh_city_name,
    d.station_code AS dwh_code,
    d.station_address AS dwh_address,
    q.gegr_lat AS api_lat,
    d.gegr_lat AS dwh_lat,
    ABS(q.gegr_lat - d.gegr_lat) AS lat_diff,
    ABS(q.gegr_lon - d.gegr_lon) AS lon_diff,
    d.is_active as activity,
    d. end_date 
FROM quarantine_stations q
-- Link to city reference via case-insensitive text match on city name
JOIN dim_cities dc ON LOWER(q.city_name) = LOWER(dc.city_name)
-- Link to stations via the resolved city_id
JOIN dim_stations d ON dc.city_id = d.city_id
WHERE q.quarantine_reason = 'Nothing matches: station code and coordinates are completely new'
  -- Verify physical proximity (within 2 decimal places / ~1km)
  AND ROUND(q.gegr_lat::numeric, 2) = ROUND(d.gegr_lat::numeric, 2)
  AND ROUND(q.gegr_lon::numeric, 2) = ROUND(d.gegr_lon::numeric, 2)
ORDER BY dc.city_name;

-- 7. Search remaining quarantine "strangers" by matching street names within the same city
SELECT 
    q.station_code AS api_code,
    q.station_name AS api_name,
    q.street AS api_street,
    dc.city_name AS city_name,
    d.station_code AS dwh_code,
    d.station_name AS dwh_name,
    d.station_address AS dwh_address,
    q.gegr_lat AS api_lat,
    d.gegr_lat AS dwh_lat
FROM quarantine_stations q
JOIN dim_cities dc ON LOWER(q.city_name) = LOWER(dc.city_name)
JOIN dim_stations d ON dc.city_id = d.city_id
WHERE q.quarantine_reason = 'Nothing matches: station code and coordinates are completely new'
  -- Match by key street part (taking text before comma) or matching station code prefix
  AND (
        LOWER(d.station_address) LIKE '%' || LOWER(split_part(q.street, ',', 1)) || '%'
     OR LOWER(q.street) LIKE '%' || LOWER(split_part(d.station_address, ',', 1)) || '%'
     or LEFT(q.station_code, 7) = LEFT(d.station_code, 7)
  )
ORDER BY dc.city_name;