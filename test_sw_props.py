import os, json, subprocess, configparser
import psycopg2

config_path = os.path.expanduser('~/.alsi_busqueda/config.ini')
config = configparser.ConfigParser()
config.read(config_path)
license_key = config['SolidWorks']['DocumentManagerKey'].strip()
exe_path = r'c:\Users\OFITEC 4\Desktop\ANTIGRAVITY\BÚSQUEDA PIEZAS\SwPropExtractor.exe'

conn = psycopg2.connect(host='192.168.1.10', port=5433, dbname='ALSI', user='ALSI', password='alsi_super_password_2026')
cur = conn.cursor()
cur.execute("SELECT ruta_completa FROM buscador.archivos WHERE extension IN ('.sldprt', '.sldasm') LIMIT 50")
rows = cur.fetchall()

print('Revisando 50 archivos para ver qué propiedades arroja SolidWorks:')
for r in rows:
    filepath = r[0]
    res = subprocess.run([exe_path, license_key, filepath], capture_output=True, text=True, encoding='latin-1', errors='replace')
    out = res.stdout.strip() if res.stdout else ''
    if out and len(out) > 2 and 'error' not in out.lower():
        print(f'{os.path.basename(filepath)} -> {out}')
conn.close()
