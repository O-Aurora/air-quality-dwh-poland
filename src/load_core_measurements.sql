-- =============================================================================
-- Core Layer: Measurements Table DDL, ETL & Validation
-- Target DB: PostgreSQL / Data Warehouse (zelona_gora_dwh)
-- =============================================================================

-- 1. DDL: Create Core Table with Unique Constraint for Idempotency
CREATE TABLE IF NOT EXISTS core_measurements (
    id BIGSERIAL PRIMARY KEY,
    sensor_id INT NOT NULL,
    measurement_time TIMESTAMP NOT NULL,
    measurement_value NUMERIC(10, 5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_core_sensors 
        FOREIGN KEY (sensor_id) 
        REFERENCES dim_sensors (sensor_id),
        
    CONSTRAINT uq_sensor_measurement_time 
        UNIQUE (sensor_id, measurement_time)
);

CREATE INDEX IF NOT EXISTS idx_core_measurements_time 
ON core_measurements (measurement_time);

-- 2. ETL: Ingest & Deduplicate Data from Staging Area
INSERT INTO core_measurements (sensor_id, measurement_time, measurement_value)
SELECT 
    ds.sensor_id,
    sm.date::TIMESTAMP AS measurement_time,
    REPLACE(TRIM(sm.value), ',', '.')::NUMERIC(10, 5) AS measurement_value
FROM stage_measurements sm
JOIN dim_sensors ds 
    ON sm.sensor_code = ds.sensor_code
WHERE sm.date ~ '^\d{4}-\d{2}-\d{2}'
  AND sm.value IS NOT null
  and sm.value ~ '[0-9]'
ON CONFLICT (sensor_id, measurement_time) 
DO UPDATE SET 
    measurement_value = EXCLUDED.measurement_value,
    created_at = CURRENT_TIMESTAMP;

-- 3. DATA QUALITY CHECKS

-- Check 3.1: Total volume and NULL value checks
SELECT 
    COUNT(*) AS total_rows,
    COUNT(sensor_id) AS valid_sensors,
    COUNT(measurement_time) AS valid_times,
    COUNT(measurement_value) AS valid_values
FROM core_measurements;

-- Check 3.2: Date range verification
SELECT 
    MIN(measurement_time) AS earliest_date,
    MAX(measurement_time) AS latest_date
FROM core_measurements;

-- Check 3.3: Value bounds and anomaly detection
SELECT 
    dp.param_code,
    MIN(cm.measurement_value) AS min_val,
    MAX(cm.measurement_value) AS max_val,
    ROUND(AVG(cm.measurement_value), 3) AS avg_val,
    COUNT(cm.id) AS total_records
FROM core_measurements cm
JOIN dim_sensors ds ON cm.sensor_id = ds.sensor_id
JOIN dim_parameters dp ON ds.param_id = dp.param_id
GROUP BY dp.param_code
ORDER BY dp.param_code;

-- Check 3.4: Active sensor coverage check (must return 0 rows if fully loaded)
SELECT 
    ds.sensor_code,
    dp.param_code,
    ds.start_date,
    ds.end_date,
    COUNT(cm.id) AS total_measurements
FROM dim_sensors ds
JOIN dim_parameters dp ON ds.param_id = dp.param_id
LEFT JOIN core_measurements cm ON ds.sensor_id = cm.sensor_id
WHERE 
    (ds.end_date IS NULL OR ds.end_date >= '2022-01-01')
    AND ds.param_id IN (
        SELECT DISTINCT ds_sub.param_id
        FROM dim_sensors ds_sub
        JOIN core_measurements cm_sub ON ds_sub.sensor_id = cm_sub.sensor_id
    )
GROUP BY 
	ds.sensor_code, 
    dp.param_code, 
    ds.start_date, 
    ds.end_date
HAVING COUNT(cm.id) = 0
ORDER BY ds.sensor_code;