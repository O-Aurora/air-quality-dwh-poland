-- Script: 03_reconcile_stations.sql
-- Description: Adds API station ID to dim_stations, updates matching records, and routes unmatched records to quarantine with categorized reasons.
rollback;

DO $$

DECLARE
    v_updated_count INT;
    v_quarantine_count INT;
    v_total_incoming INT;

BEGIN

    ALTER TABLE dim_stations 
    ADD COLUMN IF NOT EXISTS api_station_id INTEGER;
    
    RAISE NOTICE 'Column api_station_id checked/added to dim_stations.';

    WITH valid_station_reconciliation AS (
        SELECT 
            d.station_id,
            s.station_id_api
        FROM dim_stations d
        JOIN stage_stations_api_cleaned s 
          ON d.station_code = s.station_code
         AND ROUND(d.gegr_lat::numeric, 4) = ROUND(s.gegr_lat::numeric, 4)
         AND ROUND(d.gegr_lon::numeric, 4) = ROUND(s.gegr_lon::numeric, 4)
        WHERE s.station_id_api IS NOT NULL
    )
    UPDATE dim_stations
    SET api_station_id = v.station_id_api
    FROM valid_station_reconciliation v
    WHERE dim_stations.station_id = v.station_id
      AND (dim_stations.api_station_id IS DISTINCT FROM v.station_id_api);
    
    RAISE NOTICE 'Matched stations updated with api_station_id.';

    CREATE TABLE IF NOT EXISTS quarantine_stations (
        station_id_api INTEGER,
        station_code VARCHAR(100),
        station_name VARCHAR(255),
        gegr_lat NUMERIC,
        gegr_lon NUMERIC,
        city_name VARCHAR(255),
        voivodeship VARCHAR(255),
        street VARCHAR(255),
        quarantine_reason TEXT,
        quarantine_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    TRUNCATE TABLE quarantine_stations;

    INSERT INTO quarantine_stations (
        station_id_api, station_code, station_name, gegr_lat, gegr_lon, city_name, voivodeship, street, quarantine_reason
    )
    SELECT DISTINCT 
        s.station_id_api,
        s.station_code,
        s.station_name,
        s.gegr_lat,
        s.gegr_lon,
        s.city_name,
        s.voivodeship,
        s.street,
        'Business key matches, but coordinates differ'
    FROM stage_stations_api_cleaned s
    JOIN dim_stations d ON d.station_code = s.station_code
    WHERE s.station_id_api IS NOT NULL
      AND (
            ROUND(d.gegr_lat::numeric, 4) <> ROUND(s.gegr_lat::numeric, 4)
         OR ROUND(d.gegr_lon::numeric, 4) <> ROUND(s.gegr_lon::numeric, 4)
      );


    INSERT INTO quarantine_stations (
        station_id_api, station_code, station_name, gegr_lat, gegr_lon, city_name, voivodeship, street, quarantine_reason
    )
    SELECT DISTINCT 
        s.station_id_api,
        s.station_code,
        s.station_name,
        s.gegr_lat,
        s.gegr_lon,
        s.city_name,
        s.voivodeship,
        s.street,
        'Coordinates match, but business code differs'
    FROM stage_stations_api_cleaned s
    JOIN dim_stations d 
      ON ROUND(d.gegr_lat::numeric, 4) = ROUND(s.gegr_lat::numeric, 4)
     AND ROUND(d.gegr_lon::numeric, 4) = ROUND(s.gegr_lon::numeric, 4)
    WHERE s.station_id_api IS NOT NULL
      AND d.station_code <> s.station_code

      AND NOT EXISTS (
          SELECT 1 FROM quarantine_stations q 
          WHERE q.station_id_api = s.station_id_api
      );

    INSERT INTO quarantine_stations (
        station_id_api, station_code, station_name, gegr_lat, gegr_lon, city_name, voivodeship, street, quarantine_reason
    )
    SELECT DISTINCT 
        s.station_id_api,
        s.station_code,
        s.station_name,
        s.gegr_lat,
        s.gegr_lon,
        s.city_name,
        s.voivodeship,
        s.street,
        'Nothing matches: station code and coordinates are completely new'
    FROM stage_stations_api_cleaned s
    WHERE s.station_id_api IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM dim_stations d 
          WHERE d.station_code = s.station_code
             OR (
                    ROUND(d.gegr_lat::numeric, 4) = ROUND(s.gegr_lat::numeric, 4)
                AND ROUND(d.gegr_lon::numeric, 4) = ROUND(s.gegr_lon::numeric, 4)
             )
      )
      AND NOT EXISTS (
          SELECT 1 FROM quarantine_stations q 
          WHERE q.station_id_api = s.station_id_api
      );

    SELECT COUNT(*) INTO v_total_incoming
    FROM stage_stations_api_cleaned 
    WHERE station_id_api IS NOT NULL;

    SELECT COUNT(*) INTO v_updated_count FROM dim_stations WHERE api_station_id IS NOT NULL;
    SELECT COUNT(*) INTO v_quarantine_count FROM quarantine_stations;

    RAISE NOTICE 'Station reconciliation finished. Total incoming: %, Updated stations: %, Quarantined records: %', 
        v_total_incoming, v_updated_count, v_quarantine_count;

END $$;