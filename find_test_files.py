import psycopg2
conn = psycopg2.connect(host='192.168.1.10', port=5433, dbname='ALSI', user='ALSI', password='alsi_super_password_2026')
cur = conn.cursor()
cur.execute("SELECT ruta_completa FROM buscador.archivos WHERE (nombre_archivo ILIKE '%banda%' OR nombre_archivo ILIKE '%cinta%') AND extension = '.sldprt' AND anio >= 2022 LIMIT 10")
for r in cur.fetchall():
    print(r[0])
conn.close()
