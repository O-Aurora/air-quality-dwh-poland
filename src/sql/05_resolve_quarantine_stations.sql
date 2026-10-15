-- Script: 05_resolve_quarantine_stations.sql
-- Description: Applies approved resolutions from quarantine, updates active DWH dimensions, 
--              inserts new stations, revives specific "sleeping" historical stations, 
--              and cleans up processed records.
UPDATE dim_stations 
SET is_active = FALSE, end_date = CURRENT_DATE 
WHERE station_code IN ('PmGdaGrunwalTMP', 'SkSolecZdroj');

BEGIN;

--------------------------------------------------------------------------------
-- STEP 1: Resolve stations with coordinate discrepancies for ACTIVE stations only
--------------------------------------------------------------------------------
UPDATE dim_stations d
SET 
    api_station_id = q.station_id_api,
    gegr_lat = q.gegr_lat,
    gegr_lon = q.gegr_lon
FROM quarantine_stations q
WHERE d.station_code = q.station_code
  AND q.quarantine_reason = 'Business key matches, but coordinates differ'
  AND d.is_active = TRUE         
  AND d.api_station_id IS NULL;


--------------------------------------------------------------------------------
-- STEP 2: Resolve stations with code changes but exact coordinates for ACTIVE stations only
--------------------------------------------------------------------------------
UPDATE dim_stations d
SET api_station_id = q.station_id_api
FROM quarantine_stations q
WHERE ROUND(d.gegr_lat::numeric, 4) = ROUND(q.gegr_lat::numeric, 4)
  AND ROUND(d.gegr_lon::numeric, 4) = ROUND(q.gegr_lon::numeric, 4)
  AND q.quarantine_reason = 'Coordinates match, but business code differs'
  AND d.is_active = TRUE         
  AND d.api_station_id IS NULL;


--------------------------------------------------------------------------------
-- STEP 3: Insert genuinely NEW stations and successors (like OpNysaRodzi2)
-- (Сюда уйдут только те, у которых действительно абсолютно новый код, отсутствующий в DWH)
--------------------------------------------------------------------------------
INSERT INTO dim_stations (station_code, station_name, city_id, gegr_lat, gegr_lon, api_station_id, is_active)
SELECT 
    q.station_code,
    q.station_name,
    dc.city_id,
    q.gegr_lat,
    q.gegr_lon,
    q.station_id_api,
    TRUE
FROM quarantine_stations q
JOIN dim_cities dc ON LOWER(q.city_name) = LOWER(dc.city_name)
WHERE q.quarantine_reason = 'Nothing matches: station code and coordinates are completely new'
  AND NOT EXISTS (
      SELECT 1 FROM dim_stations d WHERE d.station_code = q.station_code
  );


--------------------------------------------------------------------------------
-- STEP 4: SPECIAL CASE — Revive "sleeping" / closed historical stations found in API
-- (Особый случай: код совпал, но станция была выключена, например PmGdaPowWars)
--------------------------------------------------------------------------------
UPDATE dim_stations d
SET 
    api_station_id = q.station_id_api,
    gegr_lat = q.gegr_lat,
    gegr_lon = q.gegr_lon,
    is_active = TRUE,
    end_date = NULL
FROM quarantine_stations q
WHERE d.station_code = q.station_code
  AND d.is_active = FALSE        -- Трогаем только то, что было выключено
  AND d.api_station_id IS NULL;


--------------------------------------------------------------------------------
-- STEP 5: CLEANUP — Remove successfully processed records from quarantine
--------------------------------------------------------------------------------
DELETE FROM quarantine_stations q
USING dim_stations d
WHERE q.station_id_api = d.api_station_id;

COMMIT;

--------------------------------------------------------------------------------
-- POST-CHECK: Audit remaining anomalies after resolution
--------------------------------------------------------------------------------
SELECT 
    d.station_code,
    d.station_name,
    d.gegr_lat,
    d.gegr_lon,
    d.is_active,
    d.end_date,
    'Active in DWH, but no API link' AS anomaly_type
FROM dim_stations d
WHERE d.is_active = TRUE 
  AND d.api_station_id IS NULL

UNION ALL

SELECT 
    d.station_code,
    d.station_name,
    d.gegr_lat,
    d.gegr_lon,
    d.is_active,
    d.end_date,
    'Inactive in DWH, but present in API (Quarantine)' AS anomaly_type
FROM dim_stations d
JOIN quarantine_stations q ON d.station_code = q.station_code
WHERE d.is_active = FALSE;