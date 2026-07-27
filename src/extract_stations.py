import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine 

load_dotenv('../.env')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASS = os.getenv('DB_PASSWORD', 'your_password_here')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'zelona_gora_dwh')


DATABASE_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
engine = create_engine(DATABASE_URL)

# Load metadata excel file
excel_file='../Metadane oraz kody stacji i stanowisk pomiarowych.xlsx'
df_stations = pd.read_excel(excel_file, sheet_name='STACJE')

# Clean and normalize column names for PostgreSQL compatibility
python_columns = list(df_stations.columns)
replacements = str.maketrans({
    'φ': 'lat',
    'λ': 'lon',
    ' ': '_',
    '\n': ''
})
clean_columns = [col.lower().translate(replacements) for col in df_stations.columns]
df_stations.columns = clean_columns

# Load transformed data into PostgreSQL staging table
df_stations.to_sql(
    name='stage_stations',         
    con=engine,                     
    if_exists='replace',            
    index=False                    
)

print ("Data successfully loaded to stage_stations table.")
