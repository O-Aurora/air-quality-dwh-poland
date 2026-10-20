import os
import logging
from datetime import datetime
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert
from urllib3.util import Retry

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent

# 2. Логирование прямо в папку src (рядом со скриптом)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(SCRIPT_DIR / "ingest_api.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
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

BASE_URL = 'https://api.gios.gov.pl/pjp-api/v1/rest'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def get_active_sensors(engine):
    
    query = text("""
        SELECT "Identyfikator stanowiska" 
        FROM dim_sensors_api;
    """)
    #query = text("""
     #   SELECT sensor_id 
     #   FROM dim_sensors 
     #   WHERE end_date IS NULL OR end_date > NOW();
    #""")

    with engine.connect() as conn:
        result = conn.execute(query)
        sensor_ids = [row[0] for row in result.fetchall()]
    
    logging.info(f"Найдено активных датчиков в DWH: {len(sensor_ids)}")
    return sensor_ids



def fetch_sensor_data(sensor_id):
    """Отправляет GET-запрос к API GIOŚ и возвращает JSON с замерами."""
    url = f"{BASE_URL}/data/getData/{sensor_id}"

    # Создаем сессию с автоматическими повторными попытками
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,  # Паузы: 1s, 2s, 4s
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        response = session.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()  # Вызовет ошибку, если статус ответа не 200 OK
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Не удалось получить данные для sensor_id {sensor_id} после 3 попыток: {e}")
        return None
                    

def parse_sensor_data(sensor_id, raw_json):
    """Преобразует сырой JSON нового API GIOŚ в список словарей для DWH."""
    if not raw_json:
        return []

    measurements = raw_json.get('Lista danych pomiarowych')
    
    if not isinstance(measurements, list):
        return []

    parsed_rows = []

    for entry in measurements:
        # Берем ключи из нового API: 'Wartość' и 'Data'
        raw_val = entry.get('Wartość') if entry.get('Wartość') is not None else entry.get('val')
        raw_date = entry.get('Data') if entry.get('Data') is not None else entry.get('date')

        if raw_val is None or not raw_date:
            continue

        try:
            measurement_time = datetime.strptime(raw_date, '%Y-%m-%d %H:%M:%S')
            
            parsed_rows.append({
                'sensor_id': sensor_id,
                'measurement_time': measurement_time,
                'value': float(raw_val)
            })
        except ValueError as e:
            logging.warning(f"Ошибка формата даты '{raw_date}' для sensor_id {sensor_id}: {e}")
            continue

    return parsed_rows

# --- ТЕСТОВЫЙ БЛОК (ставим в самый конец) ---
if __name__ == '__main__':
    logging.info("--- СТАРТ ТЕСТОВОГО ПРОГОНА (ЭКСТРАКТ + ПАРСИНГ) ---")
    
    # 1. Достаем ID датчиков из новой таблицы dim_sensors_api
    sensors = get_active_sensors(engine)
    
    # 2. Берем первые 3 датчика для проверки из нашей базы
    test_sensors = sensors[:3] if sensors else []
    logging.info(f"Тестируем датчики: {test_sensors}")
    
    for s_id in test_sensors:
        # Экстракт
        raw_data = fetch_sensor_data(s_id)
        
        if raw_data:
            measurements_list = raw_data.get('Lista danych pomiarowych', [])
            parsed = parse_sensor_data(s_id, raw_data)
            
            measurements_list = raw_data.get('Lista danych pomiarowych', [])
            parsed = parse_sensor_data(s_id, raw_data)
            
            raw_count = len(measurements_list) if measurements_list else 0
            logging.info(f"Sensor {s_id}: получено сырых записей: {raw_count}, распаршено: {len(parsed)}")
            
            if parsed:
                logging.info(f"Пример распаршенных данных для Sensor {s_id}: {parsed[:2]}")
        else:
            logging.warning(f"Не удалось получить сырые данные для sensor_id={s_id}")
            
    logging.info("--- ТЕСТ ЗАВЕРШЕН ---")
