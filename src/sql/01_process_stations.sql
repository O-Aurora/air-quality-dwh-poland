-- Script: 01_process_stations.sql
-- Description: Cleans, validates, and routes GIOŚ station data into clean and quarantine tables.


DO$$ 
DECLARE
    v_cleaned_count INT;
    v_rejected_count INT;
BEGIN

	CREATE TABLE IF NOT EXISTS stage_stations_api_cleaned (
	    station_id_api INT4,
	    station_code VARCHAR(50),
	    station_name VARCHAR(200),
	    gegr_lat NUMERIC(9, 6),
	    gegr_lon NUMERIC(9, 6),
	    city_id_api INT4,
	    city_name VARCHAR(100),
	    voivodeship VARCHAR(100),
	    street VARCHAR(500)
	);
	
	
	CREATE TABLE IF NOT EXISTS stage_stations_api_rejected (
	    station_id_api TEXT,
	    station_code TEXT,
	    station_name TEXT,
	    raw_lat TEXT,
	    raw_lon TEXT,
	    city_id TEXT,
	    city_name TEXT,
	    gmina TEXT,
	    powiat TEXT,
	    voivodeship TEXT,
	    street TEXT,
	    rejection_reason TEXT  
	);
	
	TRUNCATE TABLE stage_stations_api_cleaned;
	
	INSERT INTO stage_stations_api_cleaned (
	    station_id_api,
	    station_code,
	    station_name,
	    gegr_lat,
	    gegr_lon,
	    city_id_api,
	    city_name,
	    voivodeship,
	    street
	)
	SELECT 
	    "Identyfikator stacji",
	    TRIM("Kod stacji"),
	    TRIM("Nazwa stacji"),
	    TRIM("WGS84 φ N")::NUMERIC(9,6),
	    TRIM("WGS84 λ E")::NUMERIC(9,6),
	    "Identyfikator miasta",
	    TRIM("Nazwa miasta"),
	    TRIM("Województwo"),
	    TRIM("Ulica")
	FROM stage_stations_api
	WHERE "Identyfikator stacji" IS NOT NULL
	  AND "WGS84 φ N" NOT IN ('-999', '-999.0', '', 'NULL')
	  AND "WGS84 λ E" NOT IN ('-999', '-999.0', '', 'NULL')
	  AND "WGS84 φ N" ~ '^-?[0-9]+(\.[0-9]+)?$' = TRUE
	  AND "WGS84 λ E" ~ '^-?[0-9]+(\.[0-9]+)?$' = TRUE
	  AND TRIM("WGS84 φ N")::NUMERIC(9,6) BETWEEN 49.0 AND 55.0
	  AND TRIM("WGS84 λ E")::NUMERIC(9,6) BETWEEN 14.0 AND 25.0;
	
	TRUNCATE TABLE stage_stations_api_rejected;
	
	INSERT INTO stage_stations_api_rejected (
	    station_id_api,
	    station_code,
	    station_name,
	    raw_lat,
	    raw_lon,
	    city_id,
	    city_name,
	    gmina,
	    powiat,
	    voivodeship,
	    street,
	    rejection_reason
	)
	SELECT 
	    "Identyfikator stacji"::TEXT,
	    "Kod stacji",
	    "Nazwa stacji",
	    "WGS84 φ N",
	    "WGS84 λ E",
	    "Identyfikator miasta"::TEXT,
	    "Nazwa miasta",
	    "Gmina",
	    "Powiat",
	    "Województwo",
	    "Ulica",
	    CASE 
	        WHEN "Identyfikator stacji" IS NULL THEN 'Missing Station ID'
	        WHEN "WGS84 φ N" IN ('-999', '-999.0', '', 'NULL') OR "WGS84 λ E" IN ('-999', '-999.0', '', 'NULL') THEN 'Technical placeholder (-999 / empty)'
	        WHEN "WGS84 φ N" ~ '^-?[0-9]+(\.[0-9]+)?$' = FALSE OR "WGS84 λ E" ~ '^-?[0-9]+(\.[0-9]+)?$' = FALSE THEN 'Non-numeric coordinate format'
	        ELSE 'Out of Poland geographic bounds'
	    END AS rejection_reason
	FROM stage_stations_api
	WHERE "Identyfikator stacji" IS NULL
	   OR "WGS84 φ N" IN ('-999', '-999.0', '', 'NULL')
	   OR "WGS84 λ E" IN ('-999', '-999.0', '', 'NULL')
	   OR "WGS84 φ N" ~ '^-?[0-9]+(\.[0-9]+)?$' = FALSE
	   OR "WGS84 λ E" ~ '^-?[0-9]+(\.[0-9]+)?$' = FALSE
	   OR "WGS84 φ N"::NUMERIC(9,6) NOT BETWEEN 49.0 AND 55.0
	   OR "WGS84 λ E"::NUMERIC(9,6) NOT BETWEEN 14.0 AND 25.0;
	
	SELECT COUNT(*) INTO v_cleaned_count FROM stage_stations_api_cleaned;
    SELECT COUNT(*) INTO v_rejected_count FROM stage_stations_api_rejected;

    RAISE NOTICE 'ETL Pipeline finished successfully. Cleaned records: %, Rejected records: %', v_cleaned_count, v_rejected_count;

END $$;