"""
ETL Script: Load Air Quality Measurements into Stage Layer.
Extracts raw Excel files (_1g and _24g), transforms wide format to narrow (melt),
and loads data into PostgreSQL stage_measurements table with audit tracking.
"""

import os
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(SCRIPT_DIR /"load_stage_measurements.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
# 1. Database Connection & Environment Setup
load_dotenv(BASE_DIR / ".env")

DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASS = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'zelona_gora_dwh')

# Safety check: stop execution if password is missing from environment
if not DB_PASS:
    raise ValueError("ERROR: DB_PASSWORD variable not found in .env file!")

DATABASE_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
engine = create_engine(DATABASE_URL)
data_dir = BASE_DIR / "raw_data"

valid_sensors = set(pd.read_sql("SELECT sensor_code FROM dim_sensors", engine)["sensor_code"])

# Ensure Stage table DDL with audit column exists
with engine.connect() as conn:
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS stage_measurements (
            id SERIAL PRIMARY KEY,
            sensor_code VARCHAR(50),
            date VARCHAR(50),
            value VARCHAR(50),
            loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    )
    conn.commit()

#2. Search for Excel files with '_1g' and '_24g' excluding 'Prekursory'
files = [
    f for f in data_dir.rglob("*.xlsx") 
    if ("_1g" in f.name or "_24g" in f.name) and "Prekursory" not in f.name
]
logging.info(f"Total files found: {len(files)}")

TABLE_NAME = "stage_measurements"
# 3. Data Lineage & Audit Control
with engine.begin() as conn:
    # Create audit table if it does not exist
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS meta_loaded_files (
            file_name VARCHAR(255) PRIMARY KEY,
            loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rows_count INT
        );
    """
        )
    )

    # Fetch the set of already processed files
    result = conn.execute(
        text("SELECT file_name FROM meta_loaded_files;")
    ).fetchall()
    loaded_files = {row[0] for row in result}

# 4. Main Processing Loop
for idx, file_path in enumerate(files, 1):
    file_name = file_path.name
    # Skip file if it has already been processed
    if file_name in loaded_files:
        logging.info(f"[{idx}/{len(files)}] Skipped (already in DB): {file_name}")
        continue
            
    logging.info(f"[{idx}/{len(files)}] Processing new file: {file_name}...")
    # Read raw Excel file without headers
    
    try:
        df_raw = pd.read_excel(file_path, header=None)

    # Search for header row containing sensors code
    
        header_idx = None
        for idx_row in range(min(10, len(df_raw))):
            row_values = set(df_raw.iloc[idx_row].dropna().astype(str).str.strip())
            if not row_values.isdisjoint(valid_sensors):
                header_idx = idx_row
                break

        if header_idx is None:
            logging.error(f"[{idx}/{len(files)}] Header row with valid sensor codes not found in {file_name}")
            continue

        df_clean = df_raw.iloc[header_idx + 1:].copy()    
    # Safely rename the first column to 'date'
        cols = list(df_raw.iloc[header_idx])
        cols[0] = "date"
        df_clean.columns = cols

    # Transform wide format to narrow format (unpivot)
        df_melted = df_clean.melt(
            id_vars=["date"], var_name="sensor_code", value_name="value"
        )

    # Drop missing values
        df_melted = df_melted.dropna(subset=["value"])
        rows_inserted = len(df_melted)
    # Append data to DWH and register in audit table
        with engine.begin() as conn:
            df_melted.to_sql(
                name=TABLE_NAME,
                con=conn,
                if_exists="append",  
                index=False,
                chunksize=30000,
            )
            conn.execute(
                text(
                    """
                    INSERT INTO meta_loaded_files (file_name, rows_count)
                    VALUES (:file_name, :rows_count);
                """
                ),
                {"file_name": file_name, "rows_count": rows_inserted},
            )
    except Exception as e:
        logging.error(
            f"[{idx}/{len(files)}] Failed to process {file_name}. Error: {e}"
        )
logging.info("Data loading completed successfully!")