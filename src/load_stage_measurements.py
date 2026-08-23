import os
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pathlib import Path

# 1. Database Connection & Environment Setup
load_dotenv('../.env')

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
data_dir = Path("../raw_data")

#2. Search for Excel files with '_1g' excluding 'Prekursory'
files = [
    f for f in data_dir.rglob("*.xlsx") 
    if "_1g" in f.name and "Prekursory" not in f.name
]

print(f"Total files found: {len(files)}")

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
        print(f"[{idx}/{len(files)}] Skipped (already in DB): {file_name}")
        continue

    print(f"[{idx}/{len(files)}] Processing new file: {file_name}...")
    
    # Read raw Excel file without headers
    df_raw = pd.read_excel(file_path, header=None)

    # Search for header row containing the keyword 'Kod'
    mask = df_raw.apply(
        lambda row: row.astype(str).str.contains("Kod", case=False).any(),
        axis=1,
    )
    header_idx = df_raw[mask].index[0]
    df_clean = df_raw.iloc[header_idx + 1 :].copy()

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
            method="multi",
            chunksize=10000,
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
print("\nData loading completed successfully!")