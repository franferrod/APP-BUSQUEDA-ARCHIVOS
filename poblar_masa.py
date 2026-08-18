# -*- coding: utf-8 -*-
"""
Poblado de PESO / VOLUMEN / SUPERFICIE (V2.0.8).

Necesario aparte de poblar_propiedades.py: ese pase solo mira archivos que aún
NO tienen propiedades, y la inmensa mayoría ya las tiene — así que la masa no
se rellenaría nunca por esa vía.

  - Solo piezas y ensamblajes (los planos no tienen masa).
  - Solo lo que aún no tiene masa, de más nuevo a más viejo: lo que se consulta
    de verdad se rellena primero.
  - REANUDABLE: si se corta, al relanzarlo sigue por donde iba.
  - Todo valor pasa por el filtro de densidad de models.fisicas_creibles():
    un dato absurdo en la rejilla destruye la confianza en el resto.

Uso:
  python poblar_masa.py [anio_minimo]     (por defecto 2020)
"""
import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2
from models import PG_CONFIG, fisicas_creibles
import reindexar_diario as rd

LOG_DIR = os.path.expanduser("~/.alsi_busqueda")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "poblar_masa.log")

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")
log = logging.getLogger("masa")
log.propagate = False   # si no, cada linea sale dos veces
log.addHandler(logging.FileHandler(LOG_FILE, encoding="utf-8"))
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)

LOTE = 200
COMMIT_CADA = 100   # guardar a menudo: si se corta, no se pierde el trabajo
PAUSA_CADA = 500    # respiro para no saturar el NAS
PAUSA_SEG = 2.0


def main():
    anio_min = int(sys.argv[1]) if len(sys.argv) > 1 else 2020
    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("""SELECT count(*) FROM buscador.archivos
                   WHERE extension IN ('.sldprt', '.sldasm')
                     AND anio >= %s AND sw_masa_kg IS NULL""", (anio_min,))
    total = cur.fetchone()[0]
    log.info("=" * 62)
    log.info(f"POBLADO DE MASA/SUPERFICIE — desde {anio_min} — {total:,} archivos")
    log.info("=" * 62)

    t0 = time.time()
    hechos = con_masa = sin_masa = inaccesibles = errores = 0
    ultimo_id = 0

    while True:
        # Se avanza por id para no repetir filas ya visitadas en esta pasada:
        # el filtro sw_masa_kg IS NULL por sí solo haría que las que no dan
        # masa volvieran a salir en cada consulta (bucle infinito).
        cur.execute("""SELECT id, ruta_completa FROM buscador.archivos
                       WHERE extension IN ('.sldprt', '.sldasm')
                         AND anio >= %s AND sw_masa_kg IS NULL AND id > %s
                       ORDER BY id
                       LIMIT %s""", (anio_min, ultimo_id, LOTE))
        filas = cur.fetchall()
        if not filas:
            break

        for archivo_id, ruta in filas:
            ultimo_id = archivo_id
            hechos += 1
            try:
                accesible = rd.resolver_ruta_nas(ruta, reintentos=1, espera=1)
                if not accesible or not os.path.exists(accesible):
                    inaccesibles += 1
                    continue
                props = rd.extraer_sw_props(accesible, masa=True)
                m, v, a = fisicas_creibles(props.get("__MASA_KG__"),
                                           props.get("__VOLUMEN_M3__"),
                                           props.get("__AREA_M2__"))
                if m:
                    cur.execute("""UPDATE buscador.archivos
                                   SET sw_masa_kg=%s, sw_volumen_m3=%s, sw_area_m2=%s
                                   WHERE id=%s""", (m, v, a, archivo_id))
                    con_masa += 1
                else:
                    sin_masa += 1
            except Exception as e:
                errores += 1
                log.debug(f"  error en id={archivo_id}: {str(e)[:90]}")

            if hechos % COMMIT_CADA == 0:
                conn.commit()
            if hechos % PAUSA_CADA == 0:
                pct = 100.0 * hechos / max(total, 1)
                vel = hechos / max(time.time() - t0, 1)
                queda = (total - hechos) / max(vel, 0.01) / 3600
                log.info(f"  {hechos:,}/{total:,} ({pct:.1f}%) · con masa {con_masa:,} · "
                         f"sin masa {sin_masa:,} · inaccesibles {inaccesibles:,} · "
                         f"{vel:.1f}/s · queda ~{queda:.1f} h")
                conn.commit()
                time.sleep(PAUSA_SEG)

    conn.commit()
    dur = (time.time() - t0) / 60
    log.info("-" * 62)
    log.info(f"TERMINADO en {dur:.0f} min — procesados {hechos:,}")
    log.info(f"  con masa:      {con_masa:,}")
    log.info(f"  sin masa:      {sin_masa:,}  (sin material asignado, normalmente tornillería)")
    log.info(f"  inaccesibles:  {inaccesibles:,}")
    log.info(f"  errores:       {errores:,}")

    cur.execute("""SELECT count(*), round(avg(sw_masa_kg)::numeric, 2),
                          round(max(sw_masa_kg)::numeric, 1),
                          round(sum(sw_area_m2)::numeric, 0)
                   FROM buscador.archivos WHERE sw_masa_kg IS NOT NULL""")
    n, media, maximo, area = cur.fetchone()
    log.info(f"  EN BD AHORA: {n:,} archivos con masa · media {media} kg · "
             f"máx {maximo} kg · superficie total {area} m2")
    conn.close()


if __name__ == "__main__":
    main()
