# -*- coding: utf-8 -*-
"""
V2.0.2 - Pase dirigido: extrae los componentes de TODOS los ensamblajes (.sldasm)
y los guarda en buscador.componentes, para la función "¿en qué ensamblajes se usa?".

- Solo procesa ensamblajes (no re-indexa el resto de archivos).
- Resumible: salta los ensamblajes que ya tienen componentes guardados.
- No toca la tabla buscador.archivos.

Uso:  python poblar_componentes.py
"""
import os, sys, json, subprocess, configparser, ntpath, logging, time
import psycopg2

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.expanduser('~/.alsi_busqueda/config.ini')
EXE = os.path.join(BASE, 'SwPropExtractor.exe')

LOG_DIR = os.path.expanduser("~/.alsi_busqueda")
logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(os.path.join(LOG_DIR, "poblar_componentes.log"), encoding='utf-8'),
              logging.StreamHandler()])
log = logging.getLogger("poblar")


def cfg_pg():
    # PG: desde models.PG_CONFIG (lee el config.ini de la app). Clave SW: de ~/.alsi_busqueda
    from models import PG_CONFIG
    c = configparser.ConfigParser(); c.read(CONFIG)
    key = ""
    if c.has_section('SolidWorks') and c.has_option('SolidWorks', 'DocumentManagerKey'):
        key = c['SolidWorks']['DocumentManagerKey'].strip()
    return dict(PG_CONFIG), key


def extraer_componentes(key, ruta):
    si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        r = subprocess.run([EXE, key, ruta], capture_output=True, startupinfo=si, timeout=20)
        data = json.loads(r.stdout.decode('cp850', errors='replace'))
        if isinstance(data, dict):
            return data.get('__COMPONENTES__') or []
    except Exception:
        pass
    return []


def main():
    log.info("=" * 60)
    log.info("POBLADO DIRIGIDO DE COMPONENTES (ensamblajes)")
    pg, key = cfg_pg()
    conn = psycopg2.connect(**pg); cur = conn.cursor()

    # Asegurar tabla (esquema nuevo)
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_schema='buscador' AND table_name='componentes'""")
    cols = {r[0] for r in cur.fetchall()}
    if cols and 'componente_nombre' not in cols:
        cur.execute("DROP TABLE IF EXISTS buscador.componentes")
    cur.execute('''CREATE TABLE IF NOT EXISTS buscador.componentes (
                       ensamblaje_ruta TEXT NOT NULL, componente_nombre TEXT NOT NULL)''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_comp_nombre ON buscador.componentes(componente_nombre)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_comp_ensamblaje ON buscador.componentes(ensamblaje_ruta)')
    conn.commit()

    # Ensamblajes que aún NO tienen componentes (resumible)
    cur.execute("""SELECT a.ruta_completa FROM buscador.archivos a
                   WHERE a.extension='.sldasm'
                     AND NOT EXISTS (SELECT 1 FROM buscador.componentes c
                                     WHERE c.ensamblaje_ruta = a.ruta_completa)""")
    pendientes = [r[0] for r in cur.fetchall()]
    total = len(pendientes)
    log.info(f"Ensamblajes pendientes: {total}")

    procesados = 0; con_comps = 0; errores = 0; t0 = time.time()
    for ruta in pendientes:
        procesados += 1
        try:
            if not os.path.exists(ruta):
                continue
            comps = extraer_componentes(key, ruta)
            nombres = sorted({ntpath.basename(str(c)).upper() for c in comps if c})
            if nombres:
                cur.execute("DELETE FROM buscador.componentes WHERE ensamblaje_ruta=%s", (ruta,))
                cur.executemany(
                    "INSERT INTO buscador.componentes (ensamblaje_ruta, componente_nombre) VALUES (%s,%s)",
                    [(ruta, n) for n in nombres])
                con_comps += 1
        except Exception as e:
            errores += 1
            log.debug(f"Error en {ruta}: {e}")

        if procesados % 100 == 0:
            conn.commit()
        if procesados % 500 == 0:
            vel = procesados / max(1, time.time() - t0)
            eta = (total - procesados) / max(0.1, vel) / 60
            log.info(f"  {procesados}/{total} ({100*procesados//total}%) · con comps: {con_comps} · "
                     f"errores: {errores} · {vel:.1f}/s · ETA {eta:.0f} min")

    conn.commit()
    cur.execute("SELECT count(*) FROM buscador.componentes")
    filas = cur.fetchone()[0]
    conn.close()
    dur = (time.time() - t0) / 60
    log.info(f"COMPLETADO: {procesados} ensamblajes en {dur:.1f} min · "
             f"con componentes: {con_comps} · errores: {errores} · filas totales: {filas}")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
