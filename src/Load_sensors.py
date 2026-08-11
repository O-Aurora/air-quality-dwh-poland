import os
import pandas as pd
from sqlalchemy import create_engine, text 
from dotenv import load_dotenv

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

# 2. Extract & Clean Staging Data
df_sensors = pd.read_sql_table('stage_sensors', con=engine)
df_clean = df_sensors[[
    'nr',
    'kod_stanowiska',
    'kod_stacji',
    'wskaźnik_-_kod',
    'wskaźnik',
    'typ_pomiaru',
    'data_uruchomienia',
    'data_zamknięcia'
]].copy()

# Rename columns to standard English naming
df_clean.columns = [
    'sensor_id',
    'sensor_code',
    'station_code',
    'param_code',
    'param_name',
    'measurement_type',
    'start_date',
    'end_date'
]
# Strip leading/trailing whitespace from string fields
text_columns = ['sensor_code', 'station_code', 'param_code', 'param_name', 'measurement_type']
for col in text_columns:
    df_clean[col] = df_clean[col].str.strip()

# 3. Create & Load Parameters Dimension (dim_parameters)
dim_parameters = df_clean[['param_code', 'param_name']].drop_duplicates().reset_index(drop=True)

# Truncate table and restart identity counter
with engine.connect() as connection:
    connection.execute(text("TRUNCATE TABLE dim_parameters RESTART IDENTITY CASCADE;"))
    connection.commit()

# Save parameters to DWH
dim_parameters.to_sql('dim_parameters', con=engine, if_exists='append', index=False)

# Reload parameters with DB-generated IDs for downstream merging
df_db_parameters = pd.read_sql_table('dim_parameters', con=engine)
print(f"[INFO] Successfully loaded parameters into dim_parameters: {len(df_db_parameters)}")

#4. Map Foreign Keys (station_id, param_id) & Validate Data Integrity
df_db_stations = pd.read_sql_table('dim_stations', con=engine)[['station_id', 'station_code']]

# Merge station_id and param_id using business keys
df_sensors_with_ids = df_clean.merge(
    df_db_stations,
    on='station_code',
    how='left'
).merge(
    df_db_parameters,
    on=['param_code', 'param_name'],
    how='left'
)

# Identify invalid rows missing required foreign keys
bad_rows = df_sensors_with_ids[
    (df_sensors_with_ids['station_id'].isna()) | (df_sensors_with_ids['param_id'].isna())
]

if not bad_rows.empty:
    print(f"[WARNING] Found {len(bad_rows)} rows missing station_id or param_id:")
    print(bad_rows[['sensor_code', 'station_code', 'param_code']])
else:
    print("[INFO] All sensors successfully matched with station_id and param_id.")

# 5. Filter Invalid Data, Remove Duplicates & Cast Types
df_sensors_final = (
    df_sensors_with_ids
    .dropna(subset=['station_id', 'param_id'])
    .drop_duplicates(subset=['sensor_code'])[[
        'sensor_code',
        'station_id',
        'param_id',
        'measurement_type',
        'start_date',
        'end_date'
    ]]
    .copy()
)

# Cast ID columns back to integer (left merge creates float types due to NaN values)
df_sensors_final['station_id'] = df_sensors_final['station_id'].astype(int)
df_sensors_final['param_id'] = df_sensors_final['param_id'].astype(int)

#6. Truncate & Load Sensors Dimension (dim_sensors)
with engine.connect() as connection:
    connection.execute(text("TRUNCATE TABLE dim_sensors RESTART IDENTITY CASCADE;"))
    connection.commit()

df_sensors_final.to_sql('dim_sensors', con=engine, if_exists='append', index=False)
print(f"[SUCCESS] Successfully loaded {len(df_sensors_final)} sensors into dim_sensors!")
