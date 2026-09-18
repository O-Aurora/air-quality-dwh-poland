"""
Extract raw station and sensor dictionaries from GIOŚ API 
and load them into PostgreSQL staging tables ('stage_stations_api', 'stage_sensors_api').
"""

import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Directory & Path Setup
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent

RAW_DICT_DIR = BASE_DIR / "data" / "raw" / "api_dictionaries"
RAW_DICT_DIR.mkdir(parents=True, exist_ok=True)

# 2. Logging Configuration
LOG_FILE = SCRIPT_DIR / "extract_stations_sensors_api.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 3. Database Connection & Environment Setup
load_dotenv(BASE_DIR / ".env")

DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASS = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'zelona_gora_dwh')

if not DB_PASS:
    raise ValueError("ERROR: DB_PASSWORD variable not found in .env file!")

DATABASE_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
engine = create_engine(DATABASE_URL)

# 4. Configure Requests Session with Retries

def create_http_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,  # Wait 1s, 2s, 4s, 8s, 16s
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def save_raw_json(data_type, identifier, content):
    """Saves raw API JSON response to the local Bronze storage layer."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = RAW_DICT_DIR / f"{data_type}_{identifier}_{timestamp}.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=4)
        logging.info(f"Raw JSON saved: {file_path.name}")
    except Exception as e:
        logging.error(f"Failed to save raw JSON for {data_type}_{identifier}: {e}")

def main():
    logging.info("Starting paginated extraction of stations and sensors from GIOŚ API...")
    session = create_http_session()
    
    page = 0
    size = 20
    all_stations = []
    all_sensors = []

    # --- EXTRACTION PHASE --
    while True:
        url = f"https://api.gios.gov.pl/pjp-api/v1/rest/station/findAll?page={page}&size={size}"  
    
        try:
            response = session.get(url, timeout=15)
            if response.status_code != 200:
                logging.error(f"API error on page {page}: status code {response.status_code}")
                break
            
            data = response.json()
            stations = data.get("Lista stacji pomiarowych", [])
                    
            if not stations:
                logging.info("Reached the end of station pagination. No more data.")
                break
            
            logging.info(f"Processing page {page} (stations fetched: {len(stations)})")
            
            # Save raw stations response (Bronze layer)
            save_raw_json("stations_page", page, data)
            
            for station in stations:
                all_stations.append(station)
                station_id = station.get('Identyfikator stacji')
                
                if not station_id:
                    continue

                # Fetch sensors for each station
                sensor_url = f"https://api.gios.gov.pl/pjp-api/v1/rest/station/sensors/{station_id}"
                try:
                    sensor_resp = session.get(sensor_url, timeout=15)
                    if sensor_resp.status_code == 200:
                        sensor_data = sensor_resp.json()
                        
                        # Save raw sensors response per station (Bronze layer)
                        save_raw_json("sensors_station", station_id, sensor_data)
                        
                        sensors = sensor_data.get("Lista stanowisk pomiarowych dla podanej stacji", [])
                        if isinstance(sensors, list):
                            for sensor in sensors:
                                sensor['station_id'] = station_id
                                all_sensors.append(sensor)
                    else:
                        logging.warning(f"Failed to fetch sensors for station ID {station_id}, status: {sensor_resp.status_code}")
                except Exception as e:
                    logging.error(f"Error requesting sensors for station ID {station_id}: {e}")
                
                time.sleep(0.2) # Polite scraping delay

        except Exception as e:
            logging.error(f"Connection failure on page {page}: {e}")
            break
            
        page += 1
        time.sleep(0.3)

    if not all_stations:
        logging.warning("No station data collected. Exiting database load.")
        return

    # --- TRANSFORMATION & LOAD PHASE ---
    logging.info("Preparing dataframes for database load...")
    df_stations = pd.DataFrame(all_stations)
    df_sensors = pd.DataFrame(all_sensors) if all_sensors else pd.DataFrame()

    logging.info(f"Total stations collected: {len(df_stations)}, Total sensors collected: {len(df_sensors)}")

    try:
        with engine.begin() as connection:
            # Using 'replace' safely on target tables once after full extraction is complete
            logging.info("Writing stations to 'stage_stations_api'...")
            df_stations.to_sql('stage_stations_api', con=connection, if_exists='replace', index=False)
            
            if not df_sensors.empty:
                logging.info("Writing sensors to 'stage_sensors_api'...")
                df_sensors.to_sql('stage_sensors_api', con=connection, if_exists='replace', index=False)
                
        logging.info("Dictionaries successfully loaded into PostgreSQL database.")
    except Exception as e:
        logging.error(f"Database write error: {e}")

if __name__ == '__main__':
    main()