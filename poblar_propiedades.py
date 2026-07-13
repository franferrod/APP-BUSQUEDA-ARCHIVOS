# -*- coding: utf-8 -*-
"""
Pase dirigido nocturno: re-extrae propiedades SolidWorks (MATERIAL, LÁSER,
MONTAJE, SOLDADURA...) Y la miniatura embebida (caché en BD para equipos sin
SolidWorks) de todo el histórico. Una sola apertura por archivo (Document
Manager) para ambas cosas.

- FASE 1: .sldprt + .sldasm (propiedades sw_* + miniatura).
- FASE 2: .slddrw (miniatura; las propiedades del plano también se guardan).
- Resumible: checkpoint por fase. Si no termina en la noche, sigue la próxima.
- GUARDA-JORNADA: en horario laboral (L-V 07:00-15:30) se detiene solo para
  no cargar el NAS mientras se trabaja (se relanza con la tarea de las 15:35).
- Cuando ya no queda nada pendiente, termina en segundos (barato dejarlo
  programado a diario como red de seguridad).

Uso:  python poblar_propiedades.py
"""
import os, sys, ntpath, logging, time, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from models import PG_CONFIG
import psycopg2
import reindexar_diario as rd

LOG_DIR = os.path.expanduser("~/.alsi_busqueda")
os.makedirs(LOG_DIR, exist_ok=True)

# Configurar un logger PROPIO con sus handlers (no usar basicConfig: al importar
# reindexar_diario/models el logger raíz ya puede tener handlers y basicConfig
# sería un no-op, mandando los logs a otro fichero).
log = logging.getLogger("poblar_props")
log.setLevel(logging.INFO)
log.propagate = False
if not log.handlers:
    _fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    _fh = logging.FileHandler(os.path.join(LOG_DIR, "poblar_propiedades.log"), encoding='utf-8')
    _fh.setFormatter(_fmt); log.addHandler(_fh)
    _ch = logging.StreamHandler(); _ch.setFormatter(_fmt); log.addHandler(_ch)


def en_horario_laboral():
    """True si es L-V entre 07:00 y 15:30 (no debemos cargar el NAS)."""
    ahora = datetime.datetime.now()
    if ahora.weekday() >= 5:  # sábado/domingo
        return False
    hhmm = ahora.hour * 60 + ahora.minute
    return (7 * 60) <= hhmm < (15 * 60 + 30)


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


def leer_checkpoint(nombre):
    try:
        with open(os.path.join(LOG_DIR, nombre)) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def guardar_checkpoint(nombre, last_id):
    try:
        with open(os.path.join(LOG_DIR, nombre), "w") as f:
            f.write(str(last_id))
    except Exception:
        pass


def procesar_fase(conn, cur, nombre_fase, extensiones, checkpoint_file, con_props=True):
    """Recorre los archivos pendientes de la fase extrayendo propiedades +
    miniatura. Devuelve True si terminó, False si paró por horario."""
    last_id = leer_checkpoint(checkpoint_file)
    cur.execute(f"""SELECT count(*) FROM buscador.archivos
                    WHERE extension IN %s AND id > %s""", (extensiones, last_id))
    total = cur.fetchone()[0]
    log.info(f"[{nombre_fase}] pendientes: {total} (desde id > {last_id})")
    if not total:
        return True

    cur.execute(f"""SELECT id, ruta_completa, ultima_modificacion
                    FROM buscador.archivos
                    WHERE extension IN %s AND id > %s
                    ORDER BY id""", (extensiones, last_id))
    filas = cur.fetchall()

    procesados = 0; props_ok = 0; minis_ok = 0; errores = 0; t0 = time.time()
    for fid, ruta, mtime in filas:
        if procesados % 50 == 0 and en_horario_laboral():
            conn.commit()
            log.info(f"[{nombre_fase}] PAUSA por horario laboral en {procesados}/{total} "
                     f"(minis: {minis_ok}) — continuará esta tarde")
            return False
        procesados += 1
        try:
            if os.path.exists(ruta):
                props = rd.extraer_sw_props(ruta, preview=True)
                if props:
                    if con_props:
                        vals = valores_sw(props)
                        if any(v is not None for v in vals):
                            props_ok += 1
                        cur.execute(UPDATE_SQL, vals + (fid,))
                    if rd.guardar_miniatura_bd(cur, ruta, props, mtime):
                        minis_ok += 1
        except Exception as e:
            errores += 1
            log.debug(f"Error en id={fid} {ruta}: {e}")

        if procesados % 100 == 0:
            conn.commit(); guardar_checkpoint(checkpoint_file, fid)
        if procesados % 1000 == 0:
            vel = procesados / max(1, time.time() - t0)
            eta = (total - procesados) / max(0.1, vel) / 60
            log.info(f"[{nombre_fase}] {procesados}/{total} ({100*procesados//max(1,total)}%) · "
                     f"props: {props_ok} · minis: {minis_ok} · err: {errores} · "
                     f"{vel:.1f}/s · ETA {eta:.0f} min")

    conn.commit()
    if filas:
        guardar_checkpoint(checkpoint_file, filas[-1][0])
    dur = (time.time() - t0) / 60
    log.info(f"[{nombre_fase}] COMPLETADA: {procesados} en {dur:.1f} min · "
             f"props: {props_ok} · minis: {minis_ok} · err: {errores}")
    return True


def _mini_jpeg_pil(im, lado=256):
    """PIL.Image -> bytes JPEG ~256px fondo blanco."""
    import io
    from PIL import Image
    if im.mode in ('RGBA', 'P', 'LA'):
        im = im.convert('RGBA')
        fondo = Image.new('RGB', im.size, (255, 255, 255))
        fondo.paste(im, mask=im.split()[-1])
        im = fondo
    else:
        im = im.convert('RGB')
    im.thumbnail((lado, lado), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=85)
    return buf.getvalue()


def jpeg_de_pdf(ruta):
    """Primera página del PDF -> JPEG 256px, o None."""
    try:
        import fitz, io
        from PIL import Image
        doc = fitz.open(ruta)
        if doc.page_count == 0:
            doc.close(); return None
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        doc.close()
        return _mini_jpeg_pil(im)
    except Exception:
        return None


def jpeg_de_dwg(ruta):
    """Miniatura BMP/PNG embebida en la cabecera del DWG -> JPEG, o None.
    (Solo lee la cabecera: rapidísimo incluso por red)."""
    import struct, io
    try:
        from PIL import Image
        with open(ruta, 'rb') as f:
            head = f.read(0x11)
            if len(head) < 0x11 or head[:2] != b'AC':
                return None
            pos = struct.unpack('<I', head[0x0D:0x11])[0]
            if pos <= 0:
                return None
            f.seek(pos + 16)
            f.read(4)
            n = f.read(1)[0]
            entradas = []
            for _ in range(n):
                code = f.read(1)[0]
                start, size_img = struct.unpack('<II', f.read(8))
                entradas.append((code, start, size_img))
            for code, start, size_img in entradas:
                if code in (2, 6) and size_img > 0:
                    f.seek(start)
                    data = f.read(size_img)
                    if code == 6 or data[:8] == b'\x89PNG\r\n\x1a\n':
                        return _mini_jpeg_pil(Image.open(io.BytesIO(data)))
                    dib = struct.unpack('<I', data[0:4])[0]
                    bpp = struct.unpack('<H', data[14:16])[0]
                    paleta = 0
                    if bpp <= 8:
                        ncol = struct.unpack('<I', data[32:36])[0] or (1 << bpp)
                        paleta = ncol * 4
                    fh = b'BM' + struct.pack('<IHHI', 14 + len(data), 0, 0, 14 + dib + paleta)
                    return _mini_jpeg_pil(Image.open(io.BytesIO(fh + data)))
    except Exception:
        return None
    return None


def procesar_minis(conn, cur, nombre_fase, extensiones, fn_render, cada_pausa=50):
    """Fase genérica de miniaturas: procesa los archivos de esas extensiones
    que aún NO tienen miniatura en BD (auto-resumible y recoge los nuevos).
    fn_render(ruta) -> bytes JPEG o None. True=terminó, False=pausa horario."""
    cur.execute("""SELECT a.id, a.ruta_completa, a.ultima_modificacion
                   FROM buscador.archivos a
                   WHERE a.extension IN %s
                     AND NOT EXISTS (SELECT 1 FROM buscador.miniaturas m
                                     WHERE m.ruta_completa = a.ruta_completa)
                   ORDER BY a.id""", (extensiones,))
    filas = cur.fetchall()
    total = len(filas)
    log.info(f"[{nombre_fase}] pendientes: {total}")
    if not total:
        return True

    procesados = 0; minis_ok = 0; errores = 0; t0 = time.time()
    for fid, ruta, mtime in filas:
        if procesados % cada_pausa == 0 and en_horario_laboral():
            conn.commit()
            log.info(f"[{nombre_fase}] PAUSA por horario en {procesados}/{total} (minis: {minis_ok})")
            return False
        procesados += 1
        try:
            if os.path.exists(ruta):
                jpeg = fn_render(ruta)
                if jpeg:
                    cur.execute('''
                        INSERT INTO buscador.miniaturas (ruta_completa, imagen, mtime, actualizado)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (ruta_completa) DO UPDATE SET
                            imagen = EXCLUDED.imagen, mtime = EXCLUDED.mtime, actualizado = NOW()
                    ''', (ruta, psycopg2.Binary(jpeg), mtime))
                    minis_ok += 1
                else:
                    errores += 1
        except Exception as e:
            errores += 1
            log.debug(f"Error en {ruta}: {e}")

        if procesados % 100 == 0:
            conn.commit()
        if procesados % 2000 == 0:
            vel = procesados / max(1, time.time() - t0)
            eta = (total - procesados) / max(0.1, vel) / 60
            log.info(f"[{nombre_fase}] {procesados}/{total} ({100*procesados//max(1,total)}%) · "
                     f"minis: {minis_ok} · sin/err: {errores} · {vel:.1f}/s · ETA {eta:.0f} min")

    conn.commit()
    dur = (time.time() - t0) / 60
    log.info(f"[{nombre_fase}] COMPLETADA: {procesados} en {dur:.1f} min · "
             f"minis: {minis_ok} · sin preview/errores: {errores}")
    return True


def procesar_step(conn, cur):
    """FASE 3: miniaturas de STEP/IGES vía render_step.py en subproceso aislado
    (un STEP corrupto puede reventar gmsh y no debe tumbar el pase). Procesa
    solo los que aún no tienen miniatura, así también recoge los nuevos.
    Devuelve True si terminó, False si paró por horario."""
    import subprocess, tempfile
    render = os.path.join(BASE, 'render_step.py')
    if not os.path.exists(render):
        log.warning("[FASE3 step] render_step.py no encontrado — fase omitida")
        return True
    try:
        import gmsh  # noqa: F401 — solo comprobar que está instalado
    except ImportError:
        log.warning("[FASE3 step] gmsh no instalado (pip install gmsh numpy) — fase omitida")
        return True

    cur.execute("""SELECT a.id, a.ruta_completa, a.ultima_modificacion
                   FROM buscador.archivos a
                   WHERE a.extension IN ('.step', '.stp', '.iges', '.igs')
                     AND NOT EXISTS (SELECT 1 FROM buscador.miniaturas m
                                     WHERE m.ruta_completa = a.ruta_completa)
                   ORDER BY a.id""")
    filas = cur.fetchall()
    total = len(filas)
    log.info(f"[FASE3 step] pendientes: {total}")
    if not total:
        return True

    si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    procesados = 0; minis_ok = 0; errores = 0; t0 = time.time()
    for fid, ruta, mtime in filas:
        if procesados % 20 == 0 and en_horario_laboral():
            conn.commit()
            log.info(f"[FASE3 step] PAUSA por horario en {procesados}/{total}")
            return False
        procesados += 1
        try:
            if not os.path.exists(ruta):
                continue
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                salida = tmp.name
            try:
                r = subprocess.run([sys.executable, render, ruta, salida, '256'],
                                   capture_output=True, startupinfo=si, timeout=90)
                if r.returncode == 0 and os.path.getsize(salida) > 0:
                    with open(salida, 'rb') as f:
                        jpeg = f.read()
                    cur.execute('''
                        INSERT INTO buscador.miniaturas (ruta_completa, imagen, mtime, actualizado)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (ruta_completa) DO UPDATE SET
                            imagen = EXCLUDED.imagen, mtime = EXCLUDED.mtime, actualizado = NOW()
                    ''', (ruta, psycopg2.Binary(jpeg), mtime))
                    minis_ok += 1
                else:
                    errores += 1
            finally:
                try:
                    os.unlink(salida)
                except OSError:
                    pass
        except Exception as e:
            errores += 1
            log.debug(f"Error STEP id={fid} {ruta}: {e}")

        if procesados % 50 == 0:
            conn.commit()
        if procesados % 200 == 0:
            vel = procesados / max(1, time.time() - t0)
            eta = (total - procesados) / max(0.1, vel) / 60
            log.info(f"[FASE3 step] {procesados}/{total} · minis: {minis_ok} · "
                     f"err: {errores} · {vel:.1f}/s · ETA {eta:.0f} min")

    conn.commit()
    dur = (time.time() - t0) / 60
    log.info(f"[FASE3 step] COMPLETADA: {procesados} en {dur:.1f} min · "
             f"minis: {minis_ok} · sin geometría/errores: {errores}")
    return True


def main():
    log.info("=" * 60)
    log.info("PASE NOCTURNO: propiedades SW + caché de miniaturas")
    if en_horario_laboral():
        log.info("Horario laboral: no se ejecuta ahora (saldrá a las 15:35).")
        return

    conn = psycopg2.connect(**PG_CONFIG); cur = conn.cursor()
    # Asegurar tabla de miniaturas
    cur.execute('''CREATE TABLE IF NOT EXISTS buscador.miniaturas (
                       ruta_completa TEXT PRIMARY KEY,
                       imagen        BYTEA NOT NULL,
                       mtime         BIGINT,
                       actualizado   TIMESTAMP DEFAULT NOW())''')
    conn.commit()

    # FASE 1: piezas y ensamblajes (propiedades + miniaturas) — prioridad
    ok1 = procesar_fase(conn, cur, "FASE1 prt/asm", ('.sldprt', '.sldasm'),
                        "poblar_fase1.checkpoint", con_props=True)
    # FASE 2: planos SolidWorks (props + miniaturas) — si la fase 1 terminó
    ok2 = False
    if ok1:
        ok2 = procesar_fase(conn, cur, "FASE2 slddrw", ('.slddrw',),
                            "poblar_fase2.checkpoint", con_props=True)

    # FASE 3: DWG (miniatura embebida en cabecera; muy rápido)
    ok3 = False
    if ok1 and ok2:
        ok3 = procesar_minis(conn, cur, "FASE3 dwg", ('.dwg',), jpeg_de_dwg, cada_pausa=200)

    # FASE 4: PDF (primera página con PyMuPDF)
    ok4 = False
    if ok1 and ok2 and ok3:
        ok4 = procesar_minis(conn, cur, "FASE4 pdf", ('.pdf',), jpeg_de_pdf)

    # STEP/IGES: APARCADO (decisión 2026-07-13) — el render con gmsh queda
    # implementado en procesar_step()/render_step.py; activar cuando se decida.
    EJECUTAR_STEP = False
    ok5 = True
    if EJECUTAR_STEP and ok1 and ok2 and ok3 and ok4:
        ok5 = procesar_step(conn, cur)

    cur.execute("SELECT count(*) FROM buscador.miniaturas")
    total_minis = cur.fetchone()[0]
    conn.close()
    log.info(f"ESTADO GLOBAL: fase1(prt/asm) {'OK' if ok1 else 'parcial'} · "
             f"fase2(drw) {'OK' if ok2 else 'pendiente'} · "
             f"fase3(dwg) {'OK' if ok3 else 'pendiente'} · "
             f"fase4(pdf) {'OK' if ok4 else 'pendiente'} · "
             f"miniaturas en BD: {total_minis}")
    if ok1 and ok2 and ok3 and ok4:
        log.info("TODO COMPLETADO — las próximas ejecuciones recogen solo archivos nuevos.")
    log.info("=" * 60)


if __name__ == '__main__':
    main()
