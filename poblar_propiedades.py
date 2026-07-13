# -*- coding: utf-8 -*-
"""
Pase dirigido: re-extrae las propiedades SolidWorks (MATERIAL, LÁSER, MONTAJE,
SOLDADURA, TORNO, FRESA, PINTURA, ESPESOR, TRATAMIENTO, tipo de cierre, etc.)
de TODAS las piezas y ensamblajes (.sldprt/.sldasm) y actualiza las columnas
sw_* de buscador.archivos.

Motivo: hasta v2.0.1 el reindexado diario decodificaba la salida del extractor
como utf-8 y reventaba con los bytes acentuados (LÁSER/SÍ...), dejando todas las
propiedades a NULL. Ya está corregido en reindexar_diario.py; este pase rellena
lo que quedó vacío en el histórico.

- Solo hace UPDATE de columnas sw_* (no toca metadata ni re-escanea el disco).
- Resumible: guarda un checkpoint del último id procesado.
- Reutiliza reindexar_diario.extraer_sw_props (misma lógica ya corregida).

Uso:  python poblar_propiedades.py
"""
import os, sys, ntpath, logging, time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from models import PG_CONFIG
import psycopg2
import reindexar_diario as rd

LOG_DIR = os.path.expanduser("~/.alsi_busqueda")
os.makedirs(LOG_DIR, exist_ok=True)
CHECKPOINT = os.path.join(LOG_DIR, "poblar_propiedades.checkpoint")

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(os.path.join(LOG_DIR, "poblar_propiedades.log"), encoding='utf-8'),
              logging.StreamHandler()])
log = logging.getLogger("poblar_props")


def valores_sw(p):
    """Mapea el dict de propiedades a la tupla de columnas sw_* (mismo orden y
    mismas claves que reindexar_diario.upsert_archivo)."""
    return (
        p.get('MATERIAL') or p.get('material') or None,
        p.get('TRATAMIENTO') or None,
        p.get('ESPESOR') or p.get('espesor') or None,
        p.get('LÁSER') or p.get('LASER') or None,
        p.get('TORNO') or None,
        p.get('FRESA') or None,
        p.get('SOLDADURA') or None,
        p.get('PINTURA') or None,
        p.get('MONTAJE') or None,
        p.get('TIPO DE CIERRE') or None,
        p.get('FILO GUIADO') or None,
        p.get('ONDA') or None,
        p.get('CANGILÓN') or p.get('CANGILON') or None,
        p.get('RUNER') or None,
    )


UPDATE_SQL = """UPDATE buscador.archivos SET
    sw_material=%s, sw_tratamiento=%s, sw_espesor=%s, sw_laser=%s, sw_torno=%s,
    sw_fresa=%s, sw_soldadura=%s, sw_pintura=%s, sw_montaje=%s, sw_tipo_cierre=%s,
    sw_filo_guiado=%s, sw_onda=%s, sw_cangilon=%s, sw_runer=%s
    WHERE id=%s"""


def leer_checkpoint():
    try:
        with open(CHECKPOINT) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def guardar_checkpoint(last_id):
    try:
        with open(CHECKPOINT, "w") as f:
            f.write(str(last_id))
    except Exception:
        pass


def main():
    log.info("=" * 60)
    log.info("REPOBLADO DE PROPIEDADES SOLIDWORKS (sw_*)")
    last_id = leer_checkpoint()
    log.info(f"Reanudando desde id > {last_id}")

    conn = psycopg2.connect(**PG_CONFIG); cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM buscador.archivos
                   WHERE extension IN ('.sldprt','.sldasm') AND id > %s""", (last_id,))
    total = cur.fetchone()[0]
    log.info(f"Archivos SW pendientes: {total}")

    cur.execute("""SELECT id, ruta_completa FROM buscador.archivos
                   WHERE extension IN ('.sldprt','.sldasm') AND id > %s
                   ORDER BY id""", (last_id,))
    filas = cur.fetchall()

    procesados = 0; con_props = 0; errores = 0; noexiste = 0; t0 = time.time()
    for fid, ruta in filas:
        procesados += 1
        try:
            if not os.path.exists(ruta):
                noexiste += 1
            else:
                props = rd.extraer_sw_props(ruta)
                vals = valores_sw(props) if props else (None,) * 14
                if any(v is not None for v in vals):
                    con_props += 1
                cur.execute(UPDATE_SQL, vals + (fid,))
        except Exception as e:
            errores += 1
            log.debug(f"Error en id={fid} {ruta}: {e}")

        if procesados % 100 == 0:
            conn.commit(); guardar_checkpoint(fid)
        if procesados % 500 == 0:
            vel = procesados / max(1, time.time() - t0)
            eta = (total - procesados) / max(0.1, vel) / 60
            log.info(f"  {procesados}/{total} ({100*procesados//max(1,total)}%) · con props: {con_props} · "
                     f"no existe: {noexiste} · errores: {errores} · {vel:.1f}/s · ETA {eta:.0f} min")

    conn.commit()
    if filas:
        guardar_checkpoint(filas[-1][0])
    conn.close()
    dur = (time.time() - t0) / 60
    log.info(f"COMPLETADO: {procesados} archivos en {dur:.1f} min · con props: {con_props} · "
             f"no existe: {noexiste} · errores: {errores}")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
