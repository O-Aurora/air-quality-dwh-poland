import os
import pandas as pd
from sqlalchemy import create_engine 
from dotenv import load_dotenv

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

# Load metadata excel file
excel_file = '../Metadane oraz kody stacji i stanowisk pomiarowych.xlsx'
df_sensors = pd.read_excel(excel_file, sheet_name='STANOWISKA')

# Clean and normalize column names for PostgreSQL compatibility
python_columns = list(df_sensors.columns)
replacements = str.maketrans({
     ' ': '_'
})
py_lowercase_columns = [col.lower().translate(replacements) for col in python_columns]
df_sensors.columns = py_lowercase_columns


# Load transformed data into PostgreSQL staging table
df_sensors.to_sql(
    name='stage_sensors',          
    con=engine,                    
    if_exists='replace',           
    index=False                    )

print ("Data successfully loaded to stage_sensors table.")
