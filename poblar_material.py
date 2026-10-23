# -*- coding: utf-8 -*-
"""
Relleno del MATERIAL (y de las demás propiedades vacías) con la traducción de
nombres del 23/10/2026.

Las propiedades de SolidWorks se leían por su nombre exacto, y una pieza con la
propiedad escrita 'Material' (no 'MATERIAL') se indexaba sin material aunque lo
tuviera: 26046.P261 Soporte inductivo M18 es GALVANIZADO y salía vacía. Medido:
18 de cada 100 piezas con plantilla ALSI y sin material lo tenían así.

Este pase vuelve a leer las piezas y conjuntos SIN material y rellena lo que
ahora sí se encuentra.

  - SOLO RELLENA HUECOS. Una columna que ya tiene valor no se toca nunca (la
    condición va en el propio UPDATE, no solo en Python). La única excepción
    son las expresiones sin evaluar ("SW-Material@...") guardadas como valor:
    no son un valor, y se sustituyen por el bueno o se vacían.
  - Primero piezas, luego conjuntos; dentro, de lo más nuevo a lo más viejo.
  - REANUDABLE: punto de control por fase. En horario de oficina (L-V de 07:00
    a 15:30) se para solo y sigue en la siguiente ejecución.
  - Abre los archivos en SOLO LECTURA (Document Manager, allowReadOnly).

Uso:  python poblar_material.py
"""
import os
import sys
import time
import logging
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import psycopg2                                                      # noqa: E402
from models import PG_CONFIG, PROPIEDADES_SW, valores_sw, es_expresion_sw   # noqa: E402
import reindexar_diario as rd                                        # noqa: E402

LOG_DIR = os.path.expanduser("~/.alsi_busqueda")
os.makedirs(LOG_DIR, exist_ok=True)

log = logging.getLogger("poblar_material")
log.setLevel(logging.INFO)
log.propagate = False
if not log.handlers:
    _fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    _fh = logging.FileHandler(os.path.join(LOG_DIR, "poblar_material.log"), encoding='utf-8')
    _fh.setFormatter(_fmt)
    log.addHandler(_fh)
    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    log.addHandler(_ch)

COLUMNAS = [c for c, _ in PROPIEDADES_SW]
FASES = (("piezas", ".sldprt"), ("conjuntos", ".sldasm"))
LOTE = 200
COMMIT_CADA = 100
INFORME_CADA = 2000
TERMINADA = "TERMINADA"

# Una columna "vacía" para este pase: NULL o una expresión sin evaluar
_SQL_HUECO = "({c} IS NULL OR (strpos({c}, '@') > 0 AND strpos(upper({c}), 'SW-') > 0))"


def en_horario_laboral():
    """True si es L-V entre 07:00 y 15:30 (no se carga el NAS mientras se trabaja)."""
    ahora = datetime.datetime.now()
    if ahora.weekday() >= 5:
        return False
    hhmm = ahora.hour * 60 + ahora.minute
    return (7 * 60) <= hhmm < (15 * 60 + 30)


def _ruta_checkpoint(carpeta, fase):
    return os.path.join(carpeta, "poblar_material_%s.checkpoint" % fase)


def leer_checkpoint(carpeta, fase):
    try:
        with open(_ruta_checkpoint(carpeta, fase)) as f:
            return f.read().strip()
    except OSError:
        return ""


def guardar_checkpoint(carpeta, fase, valor):
    try:
        with open(_ruta_checkpoint(carpeta, fase), "w") as f:
            f.write(str(valor))
    except OSError:
        pass


def _hueco(valor):
    return valor is None or es_expresion_sw(valor)


def cambios_de(actuales, nuevos):
    """Qué columnas se rellenan: solo las que están vacías (o con una expresión)
    y para las que ahora hay valor; y las expresiones que se quedan sin valor,
    que se vacían. Nunca una columna con un valor de verdad."""
    cambios = {}
    for col, antes, nuevo in zip(COLUMNAS, actuales, nuevos):
        if not _hueco(antes):
            continue
        if nuevo is not None:
            cambios[col] = nuevo
        elif antes is not None:            # era una expresión y no hay valor
            cambios[col] = None
    return cambios


def procesar_fase(conn, cur, fase, extension, totales, origen=None,
                  extraer=None, en_horario=en_horario_laboral, carpeta=LOG_DIR):
    """Recorre la fase de lo más nuevo a lo más viejo. True si termina, False si
    se para por horario (el punto de control guarda por dónde iba)."""
    extraer = extraer or rd.extraer_sw_props
    ckpt = leer_checkpoint(carpeta, fase)
    if ckpt == TERMINADA:
        log.info(f"[{fase}] ya terminada en una ejecución anterior")
        return True
    filtro_origen = " AND origen = %s" if origen else ""
    extra = (origen,) if origen else ()
    if ckpt.isdigit():
        ultimo = int(ckpt)
    else:
        cur.execute("SELECT COALESCE(max(id), 0) + 1 FROM buscador.archivos")
        ultimo = cur.fetchone()[0]
    cur.execute(f"""SELECT count(*) FROM buscador.archivos
                    WHERE extension = %s AND id < %s AND {_SQL_HUECO.format(c='sw_material')}
                    {filtro_origen}""", (extension, ultimo) + extra)
    pendientes = cur.fetchone()[0]
    log.info(f"[{fase}] pendientes: {pendientes:,} (desde id < {ultimo})")
    t0 = time.time()
    hechos = 0
    while True:
        if en_horario():
            conn.commit()
            guardar_checkpoint(carpeta, fase, ultimo)
            log.info(f"[{fase}] PAUSA por horario de oficina en {hechos:,}/{pendientes:,} "
                     f"— seguirá en la próxima ejecución")
            return False
        cur.execute(f"""SELECT id, ruta_completa, {", ".join(COLUMNAS)}
                        FROM buscador.archivos
                        WHERE extension = %s AND id < %s
                          AND {_SQL_HUECO.format(c='sw_material')} {filtro_origen}
                        ORDER BY id DESC LIMIT %s""", (extension, ultimo) + extra + (LOTE,))
        filas = cur.fetchall()
        if not filas:
            break
        for fila in filas:
            fid, ruta, actuales = fila[0], fila[1], fila[2:]
            ultimo = fid
            hechos += 1
            totales["leidos"] += 1
            try:
                accesible = rd.resolver_ruta_nas(ruta, reintentos=1, espera=1)
                if not accesible or not os.path.exists(accesible):
                    totales["inaccesibles"] += 1
                    continue
                props = extraer(accesible, preview=False, masa=False)
                if not props:
                    totales["sin_propiedades"] += 1
                    continue
                cambios = cambios_de(actuales, valores_sw(props))
                if not cambios:
                    totales["sin_cambios"] += 1
                    continue
                # La condición de "hueco" va también en el UPDATE: si alguien
                # ha escrito la columna entre la lectura y aquí, no se pisa.
                sets = ", ".join(f"{c} = CASE WHEN {_SQL_HUECO.format(c=c)} THEN %s ELSE {c} END"
                                 for c in cambios)
                cur.execute(f"UPDATE buscador.archivos SET {sets} WHERE id = %s",
                            tuple(cambios.values()) + (fid,))
                material_antes = actuales[COLUMNAS.index('sw_material')]
                if 'sw_material' in cambios:
                    if cambios['sw_material'] is not None:
                        totales["material_ganado"] += 1
                    if material_antes is not None:
                        totales["expresiones_limpiadas"] += 1
                totales["otras_rellenadas"] += sum(1 for c in cambios if c != 'sw_material'
                                                   and cambios[c] is not None)
            except Exception as e:
                totales["errores"] += 1
                log.debug(f"  error en id={fid}: {str(e)[:120]}")
            if hechos % COMMIT_CADA == 0:
                conn.commit()
                guardar_checkpoint(carpeta, fase, ultimo)
            if hechos % INFORME_CADA == 0:
                vel = hechos / max(time.time() - t0, 1)
                queda = (pendientes - hechos) / max(vel, 0.01) / 3600
                log.info(f"[{fase}] {hechos:,}/{pendientes:,} · material ganado "
                         f"{totales['material_ganado']:,} · {vel:.1f}/s · queda ~{queda:.1f} h")
    conn.commit()
    guardar_checkpoint(carpeta, fase, TERMINADA)
    log.info(f"[{fase}] TERMINADA: {hechos:,} en {(time.time() - t0) / 60:.0f} min")
    return True


def main():
    log.info("=" * 62)
    log.info("RELLENO DE MATERIAL (nombres sin mirar mayúsculas ni tildes)")
    if en_horario_laboral():
        log.info("Horario de oficina: no se ejecuta ahora.")
        return 0
    conn = psycopg2.connect(**PG_CONFIG)
    cur = conn.cursor()
    totales = dict(leidos=0, material_ganado=0, expresiones_limpiadas=0, otras_rellenadas=0,
                   sin_cambios=0, sin_propiedades=0, inaccesibles=0, errores=0)
    try:
        cur.execute("SELECT count(*) FROM buscador.archivos WHERE sw_material IS NOT NULL")
        antes = cur.fetchone()[0]
        terminado = True
        for fase, extension in FASES:
            if not procesar_fase(conn, cur, fase, extension, totales):
                terminado = False
                break
        cur.execute("SELECT count(*) FROM buscador.archivos WHERE sw_material IS NOT NULL")
        despues = cur.fetchone()[0]
    finally:
        conn.close()
    log.info("-" * 62)
    for clave, valor in totales.items():
        log.info(f"  {clave:22s} {valor:>8,}")
    log.info(f"  archivos con material en la BD: {antes:,} -> {despues:,}")
    log.info("TERMINADO" if terminado else "PARADO por horario: seguirá en la próxima ejecución")
    log.info("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
