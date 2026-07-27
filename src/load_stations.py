import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Database Connection & Environment Setup
load_dotenv('../.env')

DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASS = os.getenv('DB_PASSWORD', 'your_password_here')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'zelona_gora_dwh')

DATABASE_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
engine = create_engine(DATABASE_URL)

# 2. Extract & Clean Staging Data
df_stations = pd.read_sql_table('stage_stations', con=engine)
df_stations.dropna(subset=['kod_stacji'], inplace=True)

# Normalize text values (capitalize city and voivodeship)
df_stations['miejscowość'] = df_stations['miejscowość'].str.strip().str.capitalize()
df_stations['województwo'] = df_stations['województwo'].str.strip().str.capitalize()

# Validate spatial coordinates (Poland boundary limits)
lat_mask = (df_stations['wgs84_lat_n'] < 49) | (df_stations['wgs84_lat_n'] > 55)
lon_mask = (df_stations['wgs84_lon_e'] < 14) | (df_stations['wgs84_lon_e'] > 25)
df_stations.loc[lat_mask, 'wgs84_lat_n'] = None
df_stations.loc[lon_mask, 'wgs84_lon_e'] = None

# Lowercase dictionary codes and classifications
columns_to_lower = ['typ_stacji', 'typ_obszaru', 'rodzaj_stacji']

for col in columns_to_lower:
    df_stations[col] = df_stations[col].str.strip().str.lower()

# Strip whitespace from string identifiers
columns_to_strip = ['nazwa_stacji', 'stary_kod_stacji_(o_ile_inny_od_aktualnego)', 'adres','kod_stacji', 'kod_międzynarodowy']
for col in columns_to_strip:
    df_stations[col] = df_stations[col].str.strip()

# Validate station start/close dates & active status
data_mask = df_stations['data_zamknięcia'] < df_stations['data_uruchomienia']
df_stations.loc[data_mask, 'data_zamknięcia'] = None
df_stations['is_active']=df_stations['data_zamknięcia'].isna()

# Save processed staging data
df_stations.to_sql('clean_stations', con=engine, if_exists='replace', index=False)


# 2. Populate dim_voivodeships
df_voivodeships=df_stations[['województwo']].drop_duplicates().copy()
df_voivodeships.rename(columns={'województwo': 'voivodeship_name'}, inplace=True)
# Truncate and reload voivodeship dictionar
with engine.connect() as connection:
    connection.execute(text("TRUNCATE TABLE dim_voivodeships RESTART IDENTITY CASCADE;"))
    connection.commit()

df_voivodeships.to_sql('dim_voivodeships', con=engine, if_exists='append', index=False)
df_db_voivodships = pd.read_sql_table('dim_voivodeships', con=engine)

# 4. Populate Dimension: Cities
df_cities=df_stations[['miejscowość', 'województwo']].drop_duplicates().copy()
# Map voivodeship_id into cities dataframe
df_cities_with_id = df_cities.merge(
    df_db_voivodships, 
    left_on='województwo', 
    right_on='voivodeship_name', 
    how='inner'
)
#Słownik miast
df_cities_with_id.rename(columns={'miejscowość': 'city_name'}, inplace=True)
df_cities_with_id=df_cities_with_id[['city_name', 'voivodeship_id']]
df_cities_with_id.reset_index(drop=True, inplace=True)
# Truncate and reload city dictionary
with engine.connect() as connection:
    connection.execute(text("TRUNCATE TABLE dim_cities RESTART IDENTITY CASCADE;"))
    connection.commit()

df_cities_with_id.to_sql('dim_cities', con=engine, if_exists='append', index=False)
df_db_cities = pd.read_sql_table('dim_cities', con=engine)

# 5. Populate Dimension: Stations
# Build complete reference mapping (city + voivodeship to city_id)
df_cities_complete = df_db_cities.merge(
    df_db_voivodships,
    on='voivodeship_id',
    how='inner'
)
# Merge city_id back to cleaned stations dataset
df_stations_with_id = df_stations.merge(
    df_cities_complete, 
    left_on=['miejscowość', 'województwo'], 
    right_on=['city_name', 'voivodeship_name'], 
    how='inner'
)

# Rename columns to match DWH schema
df_stations_with_id.rename(columns={
    'kod_stacji': 'station_code',  
    'nazwa_stacji': 'station_name',
    'wgs84_lat_n': 'gegr_lat',
    'wgs84_lon_e': 'gegr_lon',
    'adres': 'station_address',
    'data_uruchomienia': 'start_date',
    'data_zamknięcia': 'end_date',
    'typ_stacji': 'station_type',
    'typ_obszaru': 'area_type',
    'rodzaj_stacji': 'measurement_type'
}, inplace=True)

# Select target columns for dim_stations
df_stations_final = df_stations_with_id[[
    'station_code', 'station_name', 'gegr_lat', 'gegr_lon', 'city_id',
    'station_address', 'start_date', 'end_date', 'station_type', 'area_type', 'measurement_type', 'is_active'
]]
# Truncate and reload stations dictionary
with engine.connect() as connection:
    connection.execute(text("TRUNCATE TABLE dim_stations RESTART IDENTITY CASCADE;"))
    connection.commit()

df_stations_final.to_sql('dim_stations', con=engine, if_exists='append', index=False, chunksize=100)

print("Dimensions successfully processed and loaded into DWH!")