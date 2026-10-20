# Polish Air Quality Data Warehouse (GIOŚ DWH)

> Status: Active Development (WIP)

## Overview
An end-to-end Data Warehouse and ETL pipeline built on **PostgreSQL** to ingest, clean, and integrate air quality monitoring data from the **GIOŚ API** (Polish Chief Inspectorate for Environmental Protection) with historical archives.

---

## DWH Architecture (Dimensional Model)

The production schema follows a normalized Dimensional Model (Snowflake / Star Schema) designed for scalable sensor measurement processing:

```text
+--------------------+ 
| core_measurements  | (Fact Table)
+--------------------+ 
          | 
          | FK: sensor_id
          v
+--------------------+         +--------------------+
|    dim_sensors     | ------> |   dim_parameters   |
+--------------------+         +--------------------+
          | FK: station_id
          v
+--------------------+         +--------------------+         +--------------------+
|    dim_stations    | ------> |     dim_cities     | ------> |  dim_voivodeships  |
+--------------------+         +--------------------+         +--------------------+
```

### Core Production Tables:

* core_measurements: Main fact table storing time-series air quality measurements linked to specific sensors.
* dim_sensors: Dimension mapping individual station sensors to parameters and lifetime intervals (start_date, end_date).
* dim_parameters: Dictionary of measurement parameters (param_code, param_name).
* dim_stations: Monitoring stations registry with spatial coordinates (gegr_lat, gegr_lon) and active state tracking (is_active).
* dim_cities & dim_voivodeships: Geographic dimension hierarchy.

### Staging, Cleaning & Quarantine Layer:
* Staging & Processing: stage_measurements, stage_sensors, stage_stations, stage_stations_api, stage_stations_api_cleaned, stage_stations_api_rejected.
* Clean Registry: clean_stations (intermediate validated station records).
* Quarantine: quarantine_cities, quarantine_stations (isolates unmatched business keys, coordinate drifts, and schema anomalies before promotion to core dimensions).
* Metadata Audit: meta_loaded_files (tracks payload file loading lineage).

## Project Structure

```text
src/
├── extract_sensors.py               # Extracts sensor metadata from historical archives
├── extract_stations.py              # Extracts monitoring stations metadata from historical archives
├── extract_stations_sensors_api.py  # Unified extraction script for stations & sensors via GIOŚ API
├── Load_sensors.py                  # Ingests and populates sensor dimension tables from historical archives
├── load_stations.py                 # Ingests and populates station dimension tables from historical archives
├── load_stage_measurements.py       # Stages historical/archive measurement datasets into PostgreSQL
└── sql/                             # DDL & DML transformation scripts
    ├── 01_process_stations.sql      # Cleans, validates, and routes GIOŚ station data into clean and rejected staging tables
    ├── 02_reconcile_cities.sql      # Enriching city dimension with API IDs, matching entities, and routing unmatched cities to quarantine
    ├── 03_reconcile_stations.sql    # Adds API station ID to dim_stations, updates matching records, and routes unmatched records to quarantine with categorized reasons
    ├── 04_audit_quarantine.sql      # Diagnostic queries to analyze and categorize data quality issues in quarantine_stations
    ├── 05_resolve_quarantine.sql    # Applies approved resolutions from quarantine, updates dimensions, inserts new stations, and revives historical records
    └── load_core_measurements.sql   # Core Layer DDL for fact measurements, idempotent ingestion, and validation (Archives & API streams)
```
## Technical Stack
* Database: PostgreSQL (Advanced DDL/DML, CTEs, Window Functions, Transactions)
* Languages: Python, SQL
* Tools: Git (Conventional Commits), Docker, DBeaver