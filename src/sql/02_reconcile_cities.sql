-- Script: 02_reconcile_cities.sql
-- Description: Adds API city ID, updates matches, and routes unmatched cities to quarantine.
rollback;

DO $$

DECLARE
    v_updated_count INT;
    v_quarantine_count INT;
	v_total_incoming INT;

BEGIN
	
	ALTER TABLE dim_cities 
	ADD COLUMN IF NOT EXISTS api_city_id INTEGER;
	
	RAISE NOTICE 'Column api_city_id checked/added to dim_cities.';
	

    WITH dwh_city_reference AS (
        SELECT 
            c.city_id,
            c.city_name,
            v.voivodeship_name
        FROM dim_cities c
        JOIN dim_voivodeships v ON c.voivodeship_id = v.voivodeship_id
    ),

    incoming_api_cities AS (
        SELECT DISTINCT 
            city_name,
            voivodeship,
            city_id_api
        FROM stage_stations_api_cleaned
        WHERE city_id_api IS NOT NULL
    ),

    valid_reconciliation AS (
        SELECT 
            d.city_id,
            i.city_id_api
        FROM dwh_city_reference d
        JOIN incoming_api_cities i 
          ON lower(d.city_name) = lower(i.city_name) 
         AND lower(d.voivodeship_name) = lower(i.voivodeship)
    )

    UPDATE dim_cities
    SET api_city_id = v.city_id_api
    FROM valid_reconciliation v
    WHERE dim_cities.city_id = v.city_id
      AND (dim_cities.api_city_id IS DISTINCT FROM v.city_id_api);
    
RAISE NOTICE 'Matched cities updated with api_city_id using composite key.';
	
	
	CREATE TABLE IF NOT EXISTS quarantine_cities (
		station_id_api INTEGER,
	    city_name VARCHAR(255),
	    voivodeship VARCHAR(255),
	    city_id_api INTEGER,
	    quarantine_reason TEXT,
	    quarantine_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);
	
	TRUNCATE TABLE quarantine_cities;
	
	
	INSERT INTO quarantine_cities (station_id_api, city_name, voivodeship, city_id_api, quarantine_reason)
	SELECT DISTINCT 
	    s.station_id_api,
		s.city_name,
	    s.voivodeship,
	    s.city_id_api,
	    'City and voivodeship composite pair from API not found in dim_cities reference table'
	FROM stage_stations_api_cleaned s
	LEFT JOIN dim_voivodeships v ON lower(s.voivodeship) = lower(v.voivodeship_name)
	LEFT JOIN dim_cities c ON lower(c.city_name) = lower(s.city_name) AND c.voivodeship_id = v.voivodeship_id
	WHERE c.city_id IS NULL;

	SELECT COUNT(*) INTO v_total_incoming
	FROM (
	    SELECT DISTINCT city_name, voivodeship 
	    FROM stage_stations_api_cleaned 
	    WHERE city_id_api IS NOT NULL
	) t;

	SELECT COUNT(*) INTO v_updated_count FROM dim_cities WHERE api_city_id IS NOT NULL;
    SELECT COUNT(*) INTO v_quarantine_count FROM quarantine_cities;

    RAISE NOTICE 'City reconciliation finished. Total incoming unique: %, Updated cities: %, Quarantined records: %', 
        v_total_incoming, v_updated_count, v_quarantine_count;
END $$;

