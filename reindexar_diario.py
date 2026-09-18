# -*- coding: utf-8 -*-
"""
Reindexación automática diaria para el Buscador de Piezas ALSI.
V1.0.7 - Script headless (sin GUI) para ejecutar via Programador de Tareas.

Comportamiento:
  - Reindexa BIBLIOTECA_3D y ALSI_ESTANDAR (completos).
  - Reindexa PROYECTOS: solo archivos modificados en los últimos 7 días
    (compara st_mtime con la fecha de última indexación guardada en PG).
  - 2026-09-18: RECUPERA lo que esté en el NAS y falte en el índice de
    PROYECTOS, sea de la fecha que sea (ver recuperar_faltantes), y lee las
    rutas de 260 caracteres o más (ver ruta_larga).
  - Registra logs en ~/.alsi_busqueda/reindexacion.log

Uso:
  python reindexar_diario.py                           el pase de las 15:45
  python reindexar_diario.py --recuperar [--minutos N]  solo la recuperación
"""
import os
import re
import sys
import time
import logging
import datetime
import psycopg2
from pathlib import Path

from models import PG_CONFIG

RUTAS_NAS = {
    'PROYECTOS':     r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS',
    'BIBLIOTECA_3D': r'\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D',
    'ALSI_ESTANDAR': r'\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR',
}

# V2.0.3: hosts del NAS a probar (IP y nombre) y reintentos, para que un hipo
# puntual de SMB no deje la reindexación en 0 (como pasó el 13-jul, con el pase
# nocturno saturando el NAS a la misma hora). Igual que el fallback de la app.
NAS_HOSTS = ["192.168.1.10", "NASCENTRAL"]


def resolver_ruta_nas(ruta, reintentos=3, espera=5):
    """Devuelve una variante accesible de la ruta (probando IP y NASCENTRAL,
    con reintentos ante fallos transitorios), o None si de verdad no se llega."""
    candidatas = [ruta]
    for host in NAS_HOSTS:
        alt = re.sub(r'\\\\[^\\]+\\', rf'\\\\{host}\\', ruta, count=1)
        if alt not in candidatas:
            candidatas.append(alt)
    for intento in range(reintentos):
        for cand in candidatas:
            try:
                if os.path.exists(cand):
                    if intento > 0 or cand != ruta:
                        logger.info(f"  NAS accesible como: {cand} (intento {intento+1})")
                    return cand
            except Exception:
                pass
        if intento < reintentos - 1:
            logger.warning(f"  NAS no responde para {ruta} — reintento en {espera}s "
                           f"({intento+1}/{reintentos})")
            time.sleep(espera)
    return None

CARPETAS_EXCLUIDAS = {
    'ARCHIVOS REPETIDOS', 'REVISION MIGRACION', '__pycache__',
    'BACKUPS', 'build', 'dist', '.git',
}

EXTENSIONES_VALIDAS = ('.sldprt', '.sldasm', '.slddrw', '.dwg', '.pdf', '.step', '.stp', '.iges', '.igs')

# Días hacia atrás para considerar "reciente" en PROYECTOS
DIAS_RECIENTES = 7

# 2026-09-18: la tarea programada MATA el pase a las 2 horas (ExecutionTimeLimit
# PT2H). La recuperación trabaja solo mientras el pase lleve menos de esto, y lo
# que no quepa lo recoge la noche siguiente.
MINUTOS_MAX_PASE = 100

EXT_SOLIDWORKS = ('.sldprt', '.sldasm', '.slddrw')

# ----- Logging -----
LOG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "reindexacion.log"

# OJO: aquí NO sirve logging.basicConfig. models.py, importado arriba, ya lo
# ha llamado hacia app.log, y un segundo basicConfig no hace nada: hasta el
# 18/09/2026 el pase escribía en el log de la APP (que rota a los 3 MB) y
# reindexacion.log se quedó parado en julio. El fichero propio lo añade main()
# con _log_propio(), para no colgárselo a quien importa este módulo
# (poblar_propiedades, poblar_masa).
# También imprimir en consola
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

logger = logging.getLogger(__name__)


def _log_propio(ruta):
    """Añade reindexacion.log (rota a los 5 MB, guarda 5) al registro del pase.
    Se sigue escribiendo también en app.log, como hasta ahora."""
    from logging.handlers import RotatingFileHandler
    ruta = os.path.abspath(str(ruta))
    raiz = logging.getLogger()
    for h in raiz.handlers:
        if getattr(h, 'baseFilename', None) == ruta:
            return h
    fh = RotatingFileHandler(ruta, maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    raiz.addHandler(fh)
    if raiz.getEffectiveLevel() > logging.INFO:
        raiz.setLevel(logging.INFO)
    return fh


def _avisar_ilegibles(origen, ilegibles, muestra=5):
    """Los archivos que el recorrido ve pero no puede leer. Hasta el 18/09/2026
    iban a nivel DEBUG, es decir, a ningún sitio: 7.605 rutas largas fallaban
    cada noche sin que constara en ningún log."""
    if not ilegibles:
        return
    logger.warning(f"  {origen}: {len(ilegibles):,} archivos no se han podido leer "
                   f"(los {min(muestra, len(ilegibles))} primeros):")
    for ruta, ex in ilegibles[:muestra]:
        logger.warning(f"     {ruta} · {type(ex).__name__}: {ex}")
    for ruta, ex in ilegibles[muestra:]:
        logger.debug(f"Error en {ruta}: {ex}")


# ----- Rutas largas (2026-09-18) -----
# Windows no abre rutas de 260 caracteres o más (MAX_PATH): os.stat dice que no
# encuentra la ruta, y os.walk ni siquiera entra en las carpetas más hondas, sin
# avisar. En el NAS había 7.605 archivos así y ninguno estaba en el índice. Con
# el prefijo \\?\UNC\ Windows se salta ese límite.
# El prefijo es SOLO para hablar con el disco: en la BD se guarda siempre la
# ruta normal, la de siempre. Si se colara, todas las rutas serían "nuevas" y
# el índice se duplicaría entero.
_PREFIJO_LARGO = '\\\\?\\'
_PREFIJO_LARGO_UNC = '\\\\?\\UNC\\'


def ruta_larga(ruta):
    """La ruta con el prefijo que se salta el límite de 260 caracteres."""
    if ruta.startswith(_PREFIJO_LARGO):
        return ruta
    if ruta.startswith('\\\\'):
        return _PREFIJO_LARGO_UNC + ruta[2:]
    if os.path.isabs(ruta):
        return _PREFIJO_LARGO + ruta
    return ruta


def ruta_normal(ruta):
    """La inversa de ruta_larga: la ruta tal como se guarda en la BD."""
    if ruta.startswith(_PREFIJO_LARGO_UNC):
        return '\\\\' + ruta[len(_PREFIJO_LARGO_UNC):]
    if ruta.startswith(_PREFIJO_LARGO):
        return ruta[len(_PREFIJO_LARGO):]
    return ruta


def recorrer_nas(ruta_base, errores=None):
    """EL recorrido del NAS: el mismo para indexar, recuperar y purgar. Si cada
    pase viera un NAS distinto, lo que uno mete lo borraría el otro.

    Devuelve (carpeta, nombre, ruta) de cada archivo con extensión válida,
    fuera de carpetas excluidas y temporales, siempre con la ruta NORMAL.
    En `errores` (si se pasa una lista) apunta las carpetas que no se han
    podido listar, que os.walk se salta sin decir nada."""
    excluir_upper = {x.upper() for x in CARPETAS_EXCLUIDAS}

    def _al_fallar(ex):
        if errores is not None:
            errores.append(ruta_normal(getattr(ex, 'filename', None) or ''))

    for root_largo, dirs, files in os.walk(ruta_larga(ruta_base), onerror=_al_fallar):
        dirs[:] = [d for d in dirs if d.upper() not in excluir_upper and not d.startswith('~')]
        root = ruta_normal(root_largo)
        for file in files:
            if file.startswith("~$") or file == 'Thumbs.db':
                continue
            if not file.lower().endswith(EXTENSIONES_VALIDAS):
                continue
            yield root, file, os.path.join(root, file)


def misma_base(ruta_leida, origen):
    """Comparar el NAS con el índice solo vale si el NAS se ha leído por la misma
    ruta con la que se guardó. Si hoy solo responde \\\\NASCENTRAL\\..., TODAS las
    rutas guardadas (\\\\192.168.1.10\\...) parecerían desaparecidas: la purga
    vaciaría el origen y la recuperación lo duplicaría."""
    return ruta_leida == RUTAS_NAS.get(origen, ruta_leida)


# ----- Parser de metadata (importado de controllers.py) -----
def extraer_metadata_proyecto(ruta_carpeta, ruta_base):
    """Extrae metadata para archivos bajo PROYECTOS."""
    metadata = {
        'año': 0, 'cliente': 'DESCONOCIDO', 'proyecto': 'DESCONOCIDO',
        'codigo_proyecto': '', 'nombre_proyecto': '',
        'codigo_orden': '', 'nombre_orden': '', 'tipo': 'OTRO'
    }
    try:
        ruta_relativa = os.path.relpath(ruta_carpeta, ruta_base)
        parts = Path(ruta_relativa).parts

        if len(parts) >= 1:
            metadata['cliente'] = parts[0]

        if len(parts) >= 2:
            raw_proj = parts[1]
            match_proj = re.match(r'^(\d+)\s+(.*)', raw_proj)
            if match_proj:
                metadata['codigo_proyecto'] = match_proj.group(1)
                metadata['nombre_proyecto'] = match_proj.group(2)
                metadata['proyecto'] = raw_proj
                codigo = match_proj.group(1)
                if len(codigo) >= 2 and codigo[:2].isdigit():
                    metadata['año'] = int('20' + codigo[:2])
            else:
                metadata['nombre_proyecto'] = raw_proj
                metadata['proyecto'] = raw_proj

        if len(parts) >= 3:
            raw_orden = parts[2]
            match_orden = re.match(r'^(\d+)\s+(.*)', raw_orden)
            if match_orden:
                metadata['codigo_orden'] = match_orden.group(1)
                metadata['nombre_orden'] = match_orden.group(2)
            else:
                metadata['nombre_orden'] = raw_orden

        ruta_upper = ruta_carpeta.upper()
        if len(parts) >= 4:
            for part in parts[3:]:
                pu = part.upper()
                if 'MECANIC' in pu: metadata['tipo'] = 'MECANICA'; break
                elif 'LAYOUT' in pu: metadata['tipo'] = 'LAYOUT'; break
                elif 'LISTADO' in pu: metadata['tipo'] = 'LISTADOS'; break
                elif 'OFERTA' in pu or 'PEDIDO' in pu: metadata['tipo'] = 'OFERTAS Y PEDIDOS'; break
                elif 'PLIEGO' in pu: metadata['tipo'] = 'PLIEGO DE CONDICIONES'; break
        else:
            if 'MECANIC' in ruta_upper: metadata['tipo'] = 'MECANICA'
            elif 'LAYOUT' in ruta_upper: metadata['tipo'] = 'LAYOUT'
            elif 'LISTADO' in ruta_upper: metadata['tipo'] = 'LISTADOS'
            elif 'OFERTA' in ruta_upper or 'PEDIDO' in ruta_upper: metadata['tipo'] = 'OFERTAS Y PEDIDOS'
            elif 'PLIEGO' in ruta_upper: metadata['tipo'] = 'PLIEGO DE CONDICIONES'
    except Exception:
        pass
    return metadata


def extraer_sw_props(filepath, preview=False, masa=True):
    """Intenta extraer propiedades SW via SwPropExtractor.exe.
    Con preview=True añade '__PREVIEW_PNG__' (base64) para la caché de
    miniaturas en BD (V2.0.3, equipos sin SolidWorks)."""
    try:
        # Intentar usar el extractor si está disponible
        script_dir = os.path.dirname(os.path.abspath(__file__))
        exe_path = os.path.join(script_dir, 'SwPropExtractor.exe')
        
        if not os.path.exists(exe_path):
            return {}
        
        import configparser
        import subprocess
        import json
        
        config_path = os.path.expanduser('~/.alsi_busqueda/config.ini')
        if not os.path.exists(config_path):
            return {}
        
        config = configparser.ConfigParser()
        config.read(config_path)
        if 'SolidWorks' not in config or 'DocumentManagerKey' not in config['SolidWorks']:
            return {}
        
        license_key = config['SolidWorks']['DocumentManagerKey'].strip()
        if not license_key:
            return {}
        
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # OJO: capturar BYTES, no text=True. El extractor emite en la página de
        # códigos OEM de la consola (cp850 en Windows ES): contiene bytes como
        # 0xb5='Á', 0xd6='Í', 0xe0='Ó' (valores "LÁSER":"SÍ", "CANGILÓN"...).
        # Decodificar como utf-8 REVIENTA con esos bytes (UnicodeDecodeError) y,
        # al tragarse el error, dejaba TODAS las propiedades a NULL. cp850 mapea
        # los 256 bytes, así que nunca falla y reconstruye los acentos bien.
        cmd = [exe_path, license_key, filepath]
        if preview:
            cmd.append('--preview')
        # V2.0.8: masa/volumen/superficie. Medido sobre 65 archivos reales:
        # +0,2 s de mediana por archivo, así que se pide siempre para piezas y
        # ensamblajes (en planos no aplica y el extractor lo omite solo).
        if masa:
            cmd.append('--masa')
        result = subprocess.run(
            cmd,
            capture_output=True,
            startupinfo=startupinfo, timeout=20  # V2.0.0: 20s (antes 5)
        )

        if result.stdout:
            raw = result.stdout
            text_out = None
            for enc in ('cp850', 'utf-8', 'cp1252'):
                try:
                    text_out = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if text_out is None:
                text_out = raw.decode('latin-1', errors='replace')
            data = json.loads(text_out)
            if "error" not in data:
                return data
    except Exception as e:
        logger.warning(f"extraer_sw_props falló en {os.path.basename(filepath)}: {e}")
    return {}


def miniatura_jpeg(png_b64, lado=256):
    """Convierte el preview PNG (base64) a JPEG ~256px sobre fondo blanco.
    Devuelve bytes o None (V2.0.3)."""
    try:
        import base64, io
        from PIL import Image
        png = base64.b64decode(png_b64)
        im = Image.open(io.BytesIO(png))
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
    except Exception:
        return None


def guardar_miniatura_bd(cursor, full_path, sw_props, mtime=None):
    """Si el extractor trajo '__PREVIEW_PNG__', guarda la miniatura en BD (V2.0.3)."""
    png_b64 = sw_props.get('__PREVIEW_PNG__')
    if not png_b64:
        return False
    jpeg = miniatura_jpeg(png_b64)
    if not jpeg:
        return False
    try:
        import psycopg2
        cursor.execute('''
            INSERT INTO buscador.miniaturas (ruta_completa, imagen, mtime, actualizado)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (ruta_completa) DO UPDATE SET
                imagen = EXCLUDED.imagen, mtime = EXCLUDED.mtime, actualizado = NOW()
        ''', (full_path, psycopg2.Binary(jpeg), mtime))
        return True
    except Exception as ex:
        logger.debug(f"Error guardando miniatura de {full_path}: {ex}")
        return False


def fisicas_de_props(sw_props):
    """(masa_kg, volumen_m3, area_m2) de la salida del extractor, ya filtradas
    por densidad creíble (V2.0.8). Devuelve (None, None, None) si no hay dato
    o si no es plausible."""
    try:
        from models import fisicas_creibles
        return fisicas_creibles(sw_props.get('__MASA_KG__'),
                                sw_props.get('__VOLUMEN_M3__'),
                                sw_props.get('__AREA_M2__'))
    except Exception:
        return (None, None, None)


def upsert_archivo(cursor, file, origen, metadata, full_path, stats, sw_props,
                   solo_si_nuevo=False):
    """Inserta o actualiza un archivo en buscador.archivos.

    Con solo_si_nuevo=True (la recuperación, 2026-09-18) una ruta que ya esté en
    el índice NO se toca: ni sus datos ni sus componentes. Devuelve True si ha
    escrito la fila."""
    insertar = '''
        INSERT INTO buscador.archivos
        (nombre_archivo, origen, anio, cliente, proyecto, tipo_carpeta,
         ruta_completa, extension, ultima_modificacion, tamano_bytes,
         codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden,
         sw_material, sw_tratamiento, sw_espesor, sw_laser, sw_torno, sw_fresa,
         sw_soldadura, sw_pintura, sw_montaje, sw_tipo_cierre, sw_filo_guiado,
         sw_onda, sw_cangilon, sw_runer,
         sw_masa_kg, sw_volumen_m3, sw_area_m2)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'''
    if solo_si_nuevo:
        si_ya_esta = '''
        ON CONFLICT (ruta_completa) DO NOTHING'''
    else:
        si_ya_esta = '''
        ON CONFLICT (ruta_completa) DO UPDATE SET
            nombre_archivo=EXCLUDED.nombre_archivo, origen=EXCLUDED.origen,
            anio=EXCLUDED.anio, cliente=EXCLUDED.cliente, proyecto=EXCLUDED.proyecto,
            tipo_carpeta=EXCLUDED.tipo_carpeta, extension=EXCLUDED.extension,
            ultima_modificacion=EXCLUDED.ultima_modificacion, tamano_bytes=EXCLUDED.tamano_bytes,
            codigo_proyecto=EXCLUDED.codigo_proyecto, nombre_proyecto=EXCLUDED.nombre_proyecto,
            codigo_orden=EXCLUDED.codigo_orden, nombre_orden=EXCLUDED.nombre_orden,
            sw_material=EXCLUDED.sw_material, sw_tratamiento=EXCLUDED.sw_tratamiento,
            sw_espesor=EXCLUDED.sw_espesor, sw_laser=EXCLUDED.sw_laser,
            sw_torno=EXCLUDED.sw_torno, sw_fresa=EXCLUDED.sw_fresa,
            sw_soldadura=EXCLUDED.sw_soldadura, sw_pintura=EXCLUDED.sw_pintura,
            sw_montaje=EXCLUDED.sw_montaje, sw_tipo_cierre=EXCLUDED.sw_tipo_cierre,
            sw_filo_guiado=EXCLUDED.sw_filo_guiado, sw_onda=EXCLUDED.sw_onda,
            sw_cangilon=EXCLUDED.sw_cangilon, sw_runer=EXCLUDED.sw_runer,
            -- V2.0.8: COALESCE para no borrar la masa ya calculada cuando
            -- el reindexado nocturno pasa sin extraer propiedades físicas
            sw_masa_kg=COALESCE(EXCLUDED.sw_masa_kg, buscador.archivos.sw_masa_kg),
            sw_volumen_m3=COALESCE(EXCLUDED.sw_volumen_m3, buscador.archivos.sw_volumen_m3),
            sw_area_m2=COALESCE(EXCLUDED.sw_area_m2, buscador.archivos.sw_area_m2),
            indexado_en=NOW()
    '''
    cursor.execute(insertar + si_ya_esta, (
        file, origen, metadata['año'], metadata['cliente'], metadata['proyecto'],
        metadata['tipo'], full_path, Path(file).suffix.lower(),
        int(stats.st_mtime), stats.st_size,
        metadata['codigo_proyecto'], metadata['nombre_proyecto'],
        metadata['codigo_orden'], metadata['nombre_orden'],
        sw_props.get('MATERIAL') or sw_props.get('material') or None,
        sw_props.get('TRATAMIENTO') or None,
        sw_props.get('ESPESOR') or None,
        sw_props.get('LÁSER') or sw_props.get('LASER') or None,
        sw_props.get('TORNO') or None,
        sw_props.get('FRESA') or None,
        sw_props.get('SOLDADURA') or None,
        sw_props.get('PINTURA') or None,
        sw_props.get('MONTAJE') or None,
        sw_props.get('TIPO DE CIERRE') or None,
        sw_props.get('FILO GUIADO') or None,
        sw_props.get('ONDA') or None,
        sw_props.get('CANGILÓN') or sw_props.get('CANGILON') or None,
        sw_props.get('RUNER') or None,
        # V2.0.8: propiedades físicas, pasadas por el filtro de densidad
        *fisicas_de_props(sw_props),
    ))
    if solo_si_nuevo and cursor.rowcount != 1:
        return False
    # V2.0.2: componentes del ensamblaje (para "¿en qué ensamblajes se usa?")
    # Se guarda el NOMBRE de archivo en mayúsculas (cruce robusto por nombre).
    comps = sw_props.get('__COMPONENTES__')
    if comps:
        try:
            import ntpath
            cursor.execute("DELETE FROM buscador.componentes WHERE ensamblaje_ruta = %s", (full_path,))
            nombres = sorted({ntpath.basename(str(c)).upper() for c in comps if c})
            cursor.executemany(
                "INSERT INTO buscador.componentes (ensamblaje_ruta, componente_nombre) VALUES (%s, %s)",
                [(full_path, n) for n in nombres])
        except Exception as ex_c:
            logger.debug(f"Error guardando componentes de {file}: {ex_c}")
    return True


def indexar_completo(conn, cursor, origen, ruta_base):
    """Indexación completa del origen (V2.0.3: SEGURA ANTE INTERRUPCIONES).

    Antes borraba el origen ANTES de reindexar: si el proceso moría a mitad
    (apagón, cierre del PC, kill), la BD se quedaba con un origen a medias y
    los archivos no reindexados DESAPARECÍAN de las búsquedas. Ocurrió el
    2026-08-06: BIBLIOTECA_3D quedó en 4000 de 7927 archivos.

    Ahora es 'mark & sweep': se upsertan todos los archivos vistos (marcando
    indexado_en) y SOLO al terminar el recorrido se borran los que ya no
    existen. Si el proceso se corta, no se pierde nada: la BD conserva los
    datos anteriores (a lo sumo algo desactualizados)."""
    logger.info(f"  Indexación COMPLETA de {origen}...")
    # V2.0.3-fix2: NADA de relojes. Se acumulan las rutas realmente vistas y al
    # final se borran solo las que faltan. (La versión con marca de tiempo
    # comparaba la hora LOCAL de Windows con indexado_en, que PostgreSQL
    # escribe en UTC: al ir la BD 2h "por detrás", el barrido consideraba
    # obsoleto TODO lo recién indexado y vació el origen. 2026-08-12.)
    vistos = set()

    tipo_map = {'BIBLIOTECA_3D': 'BIBLIOTECA', 'ALSI_ESTANDAR': 'ESTANDAR'}
    count = 0
    ilegibles = []

    # 2026-09-18: el mismo recorrido que el resto (entra en rutas de 260+)
    for root, file, full_path in recorrer_nas(ruta_base):
        metadata = {
            'año': 0, 'cliente': 'ALSI', 'proyecto': origen,
            'tipo': tipo_map.get(origen, 'OTRO'),
            'codigo_proyecto': '', 'nombre_proyecto': origen,
            'codigo_orden': '', 'nombre_orden': ''
        }

        try:
            stats = os.stat(ruta_larga(full_path))
            sw_props = {}
            # V2.0.3: .slddrw incluido para la caché de miniaturas
            if file.lower().endswith(EXT_SOLIDWORKS):
                sw_props = extraer_sw_props(full_path, preview=True)
            upsert_archivo(cursor, file, origen, metadata, full_path, stats, sw_props)
            guardar_miniatura_bd(cursor, full_path, sw_props, int(stats.st_mtime))
            vistos.add(full_path)
            count += 1
            if count % 2000 == 0:
                conn.commit()
                logger.info(f"    {origen}: {count} archivos...")
        except Exception as ex:
            ilegibles.append((full_path, ex))
            continue

    conn.commit()
    _avisar_ilegibles(origen, ilegibles)

    # SWEEP por CONJUNTO DE RUTAS (sin relojes ni zonas horarias): solo tras
    # recorrer TODO el origen se borran las rutas que ya no existen en el NAS.
    # Triple salvaguarda: nada visto -> no se toca; recorrido < 50% de lo que
    # hay en BD -> no se toca; y solo se borra lo que NO está en 'vistos'.
    try:
        cursor.execute("SELECT ruta_completa FROM buscador.archivos WHERE origen = %s",
                       (origen,))
        en_bd = {r[0] for r in cursor.fetchall()}
        if not vistos:
            logger.warning(f"  {origen}: 0 archivos vistos — NO se purga nada.")
        elif en_bd and len(vistos) < len(en_bd) * 0.5:
            logger.warning(f"  {origen}: recorrido incompleto ({len(vistos)} vistos frente "
                           f"a {len(en_bd)} en BD) — NO se purga para no perder datos.")
        else:
            huerfanas = list(en_bd - vistos)
            LOTE = 500
            for i in range(0, len(huerfanas), LOTE):
                cursor.execute("DELETE FROM buscador.archivos WHERE ruta_completa = ANY(%s)",
                               (huerfanas[i:i + LOTE],))
                conn.commit()
            if huerfanas:
                logger.info(f"  {origen}: {len(huerfanas)} rutas obsoletas eliminadas.")
    except Exception as ex:
        logger.warning(f"  {origen}: fallo en la purga final: {ex}")
        conn.rollback()

    logger.info(f"  {origen}: {count} archivos indexados.")
    return count


def indexar_proyectos_recientes(conn, cursor, ruta_base, dias=DIAS_RECIENTES,
                                origen='PROYECTOS', faltan=None):
    """Indexa solo archivos de PROYECTOS modificados en los últimos N días.

    2026-09-18: si se pasa una lista en `faltan`, apunta ahí (carpeta, nombre,
    ruta, stat) de los archivos que NO están en el índice y no son recientes,
    para que recuperar_faltantes los meta después. Es el mismo recorrido: no
    cuesta ni una lectura más del NAS."""
    logger.info(f"  Indexación INCREMENTAL de {origen} (últimos {dias} días)...")

    umbral_ts = int((datetime.datetime.now() - datetime.timedelta(days=dias)).timestamp())
    count = 0
    ilegibles = []
    en_bd = set()
    if faltan is not None:
        cursor.execute("SELECT ruta_completa FROM buscador.archivos WHERE origen = %s", (origen,))
        en_bd = {r[0] for r in cursor.fetchall()}

    for root, file, full_path in recorrer_nas(ruta_base):
        try:
            stats = os.stat(ruta_larga(full_path))
            # Solo procesar si fue modificado recientemente
            if int(stats.st_mtime) < umbral_ts:
                if faltan is not None and full_path not in en_bd:
                    faltan.append((root, file, full_path, stats))
                continue

            metadata = extraer_metadata_proyecto(root, ruta_base)
            sw_props = {}
            # V2.0.3: .slddrw incluido para la caché de miniaturas
            if file.lower().endswith(EXT_SOLIDWORKS):
                sw_props = extraer_sw_props(full_path, preview=True)
            upsert_archivo(cursor, file, origen, metadata, full_path, stats, sw_props)
            guardar_miniatura_bd(cursor, full_path, sw_props, int(stats.st_mtime))
            count += 1
            if count % 2000 == 0:
                conn.commit()
                logger.info(f"    {origen} (recientes): {count} archivos...")
        except Exception as ex:
            ilegibles.append((full_path, ex))
            continue

    conn.commit()
    _avisar_ilegibles(origen, ilegibles)
    logger.info(f"  {origen} (recientes): {count} archivos actualizados.")
    return count


def _orden_recuperacion(item, ruta_base):
    """Primero lo barato (PDF, DWG, STEP: no hay que abrir nada), después los
    SolidWorks del proyecto más reciente al más antiguo, y los "sin año" al
    final. Si una noche no da para todo, lo que se queda es lo menos buscado."""
    root, file, full_path, _stats = item
    es_sw = file.lower().endswith(EXT_SOLIDWORKS)
    anio = extraer_metadata_proyecto(root, ruta_base)['año']
    return (es_sw, anio == 0, -anio, full_path)


def recuperar_faltantes(conn, cursor, origen, ruta_base, faltan, hasta=None,
                        reloj=time.monotonic):
    """Mete en el índice lo que está en el NAS y falta en la BD (2026-09-18).

    PROYECTOS solo miraba los últimos 7 días, así que lo que se perdía un día se
    perdía para siempre: del 17 al 23 de julio el pase no llegó al NAS, y en
    septiembre faltaban 70.909 archivos (el PDF de 26003.P270, entre ellos).
    Con esto el índice se cura solo: lo que falte hoy entra esta noche.

    - SOLO AÑADE. Una ruta que ya está en el índice no se toca (ON CONFLICT
      DO NOTHING), y aquí no se borra nada, nunca.
    - Cada archivo va en su SAVEPOINT: uno que falle no se lleva a los demás.
    - Tope de tiempo: `hasta`, en la escala de `reloj`. Lo que no quepa sigue
      faltando y lo recoge la noche siguiente.

    Devuelve (recuperados, pendientes)."""
    if not faltan:
        logger.info(f"  RECUPERACIÓN {origen}: no falta nada en el índice.")
        return 0, 0
    orden = sorted(faltan, key=lambda it: _orden_recuperacion(it, ruta_base))
    n_sw = sum(1 for it in orden if it[1].lower().endswith(EXT_SOLIDWORKS))
    n_largas = sum(1 for it in orden if len(it[2]) >= 260)
    logger.info(f"  RECUPERACIÓN {origen}: faltan {len(orden):,} archivos en el índice "
                f"({n_sw:,} de SolidWorks, {n_largas:,} con ruta de 260 caracteres o más).")

    t0 = time.monotonic()
    prefijo_base = ruta_base.rstrip('\\') + '\\'
    recuperados = 0
    intentados = 0
    fallidos = []
    for root, file, full_path, stats in orden:
        if hasta is not None and reloj() >= hasta:
            break
        intentados += 1
        # Nunca con otra forma de ruta que la de siempre: ni con el prefijo
        # largo ni por otro nombre del NAS. Eso duplicaría el índice.
        if not full_path.startswith(prefijo_base) or full_path.startswith(_PREFIJO_LARGO):
            fallidos.append((full_path, ValueError("ruta con otra forma que la base")))
            continue
        try:
            cursor.execute("SAVEPOINT recuperar")
            # Se vuelve a mirar: entre el recorrido y aquí ha podido cambiar
            stats = os.stat(ruta_larga(full_path))
            metadata = extraer_metadata_proyecto(root, ruta_base)
            sw_props = {}
            if file.lower().endswith(EXT_SOLIDWORKS):
                sw_props = extraer_sw_props(full_path, preview=True)
            nuevo = upsert_archivo(cursor, file, origen, metadata, full_path, stats, sw_props,
                                   solo_si_nuevo=True)
            if nuevo:
                guardar_miniatura_bd(cursor, full_path, sw_props, int(stats.st_mtime))
            # Si algo de lo anterior dejó la transacción abortada (miniatura,
            # componentes), el RELEASE falla y el archivo entero se deshace.
            cursor.execute("RELEASE SAVEPOINT recuperar")
            if nuevo:
                recuperados += 1
        except Exception as ex:
            try:
                cursor.execute("ROLLBACK TO SAVEPOINT recuperar")
            except Exception:
                conn.rollback()
            fallidos.append((full_path, ex))
        if intentados % 500 == 0:
            conn.commit()
        if intentados % 5000 == 0:
            logger.info(f"    RECUPERACIÓN {origen}: {intentados:,}/{len(orden):,} "
                        f"({recuperados:,} dentro) · {(time.monotonic() - t0) / 60:.0f} min")
    conn.commit()

    pendientes = len(orden) - intentados
    logger.info(f"  RECUPERACIÓN {origen}: {recuperados:,} archivos recuperados en "
                f"{(time.monotonic() - t0) / 60:.1f} min · "
                + (f"quedan {pendientes:,} para la próxima noche." if pendientes
                   else "no queda ninguno pendiente."))
    _avisar_ilegibles(f"RECUPERACIÓN {origen}", fallidos)
    return recuperados, pendientes


def purgar_rutas_huerfanas(conn, cursor, origen, ruta_base):
    """Barrido semanal (V2.0.3): recorre el NAS listando las rutas que EXISTEN
    y borra de la BD las que ya no están (archivos borrados/renombrados/movidos
    que el indexado incremental de PROYECTOS nunca purga y quedan como
    fantasmas con 'Problema de red').

    Solo lista rutas (os.walk): NO re-extrae propiedades, así el barrido
    completo cuesta minutos y no días. Limpia también miniaturas y componentes."""
    # 2026-09-18: si el NAS se ha leído por otro nombre (\\NASCENTRAL en vez de
    # la IP), todas las rutas guardadas parecerían huérfanas y se borraría el
    # origen entero. Ese día no se purga.
    if not misma_base(ruta_base, origen):
        logger.warning(f"  PURGA {origen} OMITIDA: el NAS se ha leído como {ruta_base} "
                       f"y el índice guarda {RUTAS_NAS.get(origen)}.")
        return 0
    logger.info(f"  PURGA semanal de {origen}: recorriendo el NAS...")
    t0 = datetime.datetime.now()
    # 2026-09-18: el MISMO recorrido que el indexado y la recuperación. Con el
    # os.walk de antes no entraba en las carpetas de 260+ caracteres: lo que la
    # recuperación mete de ahí, la purga lo daría por borrado cada viernes.
    en_disco = set()
    for _root, _file, full_path in recorrer_nas(ruta_base):
        en_disco.add(full_path)

    cursor.execute("SELECT ruta_completa FROM buscador.archivos WHERE origen = %s", (origen,))
    en_bd = {r[0] for r in cursor.fetchall()}

    # SEGURIDAD: si el recorrido devuelve muchísimo menos de lo que hay en BD,
    # lo más probable es que el NAS fallara a mitad (red, permisos...) — en ese
    # caso NO purgamos nada para no vaciar el índice por un fallo puntual.
    if en_bd and len(en_disco) < len(en_bd) * 0.5:
        logger.warning(f"  PURGA ABORTADA: el NAS devuelve {len(en_disco)} rutas "
                       f"frente a {len(en_bd)} en BD (menos del 50 por ciento). ¿Recorrido incompleto?")
        return 0

    huerfanas = list(en_bd - en_disco)
    if not huerfanas:
        logger.info(f"  PURGA {origen}: sin huérfanas ({len(en_disco)} rutas vivas).")
        return 0

    LOTE = 500
    for i in range(0, len(huerfanas), LOTE):
        lote = huerfanas[i:i + LOTE]
        cursor.execute("DELETE FROM buscador.archivos WHERE ruta_completa = ANY(%s)", (lote,))
        cursor.execute("DELETE FROM buscador.miniaturas WHERE ruta_completa = ANY(%s)", (lote,))
        cursor.execute("DELETE FROM buscador.componentes WHERE ensamblaje_ruta = ANY(%s)", (lote,))
        conn.commit()

    dur = (datetime.datetime.now() - t0).total_seconds() / 60
    logger.info(f"  PURGA {origen}: {len(huerfanas)} rutas huérfanas eliminadas "
                f"(quedan {len(en_disco)}) en {dur:.1f} min.")
    return len(huerfanas)


def actualizar_placas_ce(conn, cursor):
    """V2.0.3: refresco DIARIO de placas CE desde los Excel de NÚMEROS DE SERIE
    (todos los años 2005-hoy; el escáner recorre las subcarpetas, así que los
    documentos de años nuevos se recogen solos y los ilegibles se saltan con
    aviso sin romper nada). SALVAGUARDA: si se leen 0 filas (NAS caído, carpeta
    movida...) NO se borra lo existente."""
    try:
        from controllers import escanear_placas_ce, RUTA_NUMEROS_SERIE
        base = resolver_ruta_nas(RUTA_NUMEROS_SERIE)
        if not base:
            logger.warning("Placas CE: carpeta NÚMEROS DE SERIE no accesible — se omite hoy.")
            return 0
        filas = escanear_placas_ce(base)
        if not filas:
            logger.warning("Placas CE: 0 filas leídas — se conserva lo existente.")
            return 0
        cursor.execute("DELETE FROM buscador.placas_ce")
        cursor.executemany('''
            INSERT INTO buscador.placas_ce
                (num_placa, codigo_tipo, descripcion, cliente, anio, proyecto, orden, num_plano, archivo_origen)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (num_placa) DO UPDATE SET
                codigo_tipo = EXCLUDED.codigo_tipo, descripcion = EXCLUDED.descripcion,
                cliente = EXCLUDED.cliente, anio = EXCLUDED.anio, proyecto = EXCLUDED.proyecto,
                orden = EXCLUDED.orden, num_plano = EXCLUDED.num_plano,
                archivo_origen = EXCLUDED.archivo_origen, indexado_en = NOW()
        ''', filas)
        conn.commit()
        logger.info(f"Placas CE actualizadas: {len(filas)} placas (2005-hoy).")
        return len(filas)
    except Exception as e:
        logger.warning(f"Placas CE: fallo en la actualización diaria: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


def main():
    _log_propio(LOG_FILE)
    logger.info("=" * 60)
    logger.info("INICIO REINDEXACIÓN AUTOMÁTICA DIARIA")
    logger.info("=" * 60)
    start = datetime.datetime.now()
    t_inicio = time.monotonic()  # para el tope de la recuperación (no es un reloj de pared)

    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cursor = conn.cursor()
        logger.info("Conexión a PostgreSQL OK")
        # V2.0.2: asegurar tabla de componentes (por si la app aún no la creó)
        # Migración: recrear si tiene el esquema antiguo (componente_ruta)
        cursor.execute("""SELECT column_name FROM information_schema.columns
                          WHERE table_schema='buscador' AND table_name='componentes'""")
        _cols = {r[0] for r in cursor.fetchall()}
        if _cols and 'componente_nombre' not in _cols:
            cursor.execute("DROP TABLE IF EXISTS buscador.componentes")
        cursor.execute('''CREATE TABLE IF NOT EXISTS buscador.componentes (
                              ensamblaje_ruta   TEXT NOT NULL,
                              componente_nombre TEXT NOT NULL)''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comp_nombre ON buscador.componentes(componente_nombre)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comp_ensamblaje ON buscador.componentes(ensamblaje_ruta)')
        # V2.0.3: caché de miniaturas para equipos sin SolidWorks
        cursor.execute('''CREATE TABLE IF NOT EXISTS buscador.miniaturas (
                              ruta_completa TEXT PRIMARY KEY,
                              imagen        BYTEA NOT NULL,
                              mtime         BIGINT,
                              actualizado   TIMESTAMP DEFAULT NOW())''')
        conn.commit()
    except Exception as e:
        logger.error(f"No se pudo conectar a PostgreSQL: {e}")
        sys.exit(1)

    total = 0
    ok_origenes = set()  # V2.0.3: solo estos actualizan el sello de "última indexación"
    faltan = []          # 2026-09-18: lo que el recorrido de PROYECTOS no ve en el índice
    recuperar = False
    ruta_proyectos = None
    recuperados = 0
    try:
        # 1. BIBLIOTECA_3D (completa)
        ruta = resolver_ruta_nas(RUTAS_NAS.get('BIBLIOTECA_3D'))
        if ruta:
            total += indexar_completo(conn, cursor, 'BIBLIOTECA_3D', ruta)
            ok_origenes.add('BIBLIOTECA_3D')
        else:
            logger.warning(f"Ruta BIBLIOTECA_3D no accesible: {RUTAS_NAS.get('BIBLIOTECA_3D')}")

        # 2. ALSI_ESTANDAR (completa)
        ruta = resolver_ruta_nas(RUTAS_NAS.get('ALSI_ESTANDAR'))
        if ruta:
            total += indexar_completo(conn, cursor, 'ALSI_ESTANDAR', ruta)
            ok_origenes.add('ALSI_ESTANDAR')
        else:
            logger.warning(f"Ruta ALSI_ESTANDAR no accesible: {RUTAS_NAS.get('ALSI_ESTANDAR')}")

        # 3. PROYECTOS (solo recientes)
        ruta = resolver_ruta_nas(RUTAS_NAS.get('PROYECTOS'))
        if ruta:
            # 2026-09-18: en el mismo recorrido se apunta lo que falta en el
            # índice, que se recupera al final (paso 6). Solo si el NAS se ha
            # leído por su ruta de siempre: por otro nombre, todo "faltaría".
            recuperar = misma_base(ruta, 'PROYECTOS')
            if not recuperar:
                logger.warning(f"  RECUPERACIÓN omitida hoy: el NAS se ha leído como {ruta} "
                               f"y el índice guarda {RUTAS_NAS['PROYECTOS']}.")
            ruta_proyectos = ruta
            total += indexar_proyectos_recientes(conn, cursor, ruta,
                                                 faltan=faltan if recuperar else None)
            ok_origenes.add('PROYECTOS')
            # V2.0.3: los VIERNES, barrido de purga — el incremental nunca borra,
            # así que sin esto los archivos eliminados del NAS quedan de fantasmas
            if datetime.datetime.now().weekday() == 4:
                purgar_rutas_huerfanas(conn, cursor, 'PROYECTOS', ruta)
                # Y limpieza global de tablas satélite: miniaturas/componentes de
                # rutas que ya no existen en archivos (p.ej. purgadas del origen
                # BIBLIOTECA/ESTANDAR, que se recrea a diario)
                try:
                    cursor.execute('''DELETE FROM buscador.miniaturas m
                                      WHERE NOT EXISTS (SELECT 1 FROM buscador.archivos a
                                                        WHERE a.ruta_completa = m.ruta_completa)''')
                    n_m = cursor.rowcount
                    cursor.execute('''DELETE FROM buscador.componentes c
                                      WHERE NOT EXISTS (SELECT 1 FROM buscador.archivos a
                                                        WHERE a.ruta_completa = c.ensamblaje_ruta)''')
                    n_c = cursor.rowcount
                    conn.commit()
                    logger.info(f"  Limpieza satélite: {n_m} miniaturas y {n_c} componentes huérfanos.")
                except Exception as ex:
                    logger.warning(f"  Limpieza satélite falló: {ex}")
        else:
            logger.warning(f"Ruta PROYECTOS no accesible: {RUTAS_NAS.get('PROYECTOS')}")

        # 4. Placas CE (diario, barato: ~20 Excels) — V2.0.3
        actualizar_placas_ce(conn, cursor)

        # 5. RED DE SEGURIDAD (V2.0.3-fix2): tras cada reindexado se comprueba
        # que ningún origen se haya quedado vacío o claramente descuadrado.
        # Si pasa, se AVISA en el log con [ALERTA] (nunca borra ni "arregla"
        # solo: el objetivo es enterarse el mismo día, no otra sorpresa).
        try:
            for org in ('BIBLIOTECA_3D', 'ALSI_ESTANDAR', 'PROYECTOS'):
                cursor.execute("SELECT count(*) FROM buscador.archivos WHERE origen=%s", (org,))
                n = cursor.fetchone()[0]
                if n == 0:
                    logger.error(f"[ALERTA] El origen {org} está VACÍO en la base de datos. "
                                 f"Revisar acceso al NAS y relanzar la indexación.")
                elif org in ok_origenes and n < 100:
                    logger.error(f"[ALERTA] El origen {org} solo tiene {n} archivos. "
                                 f"Parece incompleto.")
                else:
                    logger.info(f"  Verificación {org}: {n} archivos en BD.")
        except Exception as ex:
            logger.warning(f"Verificación final falló: {ex}")

        if not ok_origenes:
            # Ningún origen accesible: NO tocar el sello de "última indexación"
            # (si no, el footer se pondría verde engañosamente). Salir con error
            # para que la tarea programada figure como fallida y sea visible.
            logger.error("NINGÚN origen del NAS accesible — no se actualiza el estado. "
                         "Revisar red/SMB en el equipo indexador.")
            conn.commit()
            conn.close()
            sys.exit(2)

        # Actualizar estado SOLO de los orígenes realmente indexados
        for origen in ok_origenes:
            cursor.execute('''
                INSERT INTO buscador.estado_indexacion (origen, ruta_base, ultima_indexacion, archivos_indexados)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (origen) DO UPDATE SET
                    ultima_indexacion = EXCLUDED.ultima_indexacion,
                    archivos_indexados = EXCLUDED.archivos_indexados
            ''', (origen, RUTAS_NAS[origen], int(datetime.datetime.now().timestamp()), total))
        conn.commit()

        # 6. RECUPERACIÓN (2026-09-18): lo que falta en el índice, con el tiempo
        # que le quede al pase antes de que la tarea programada lo corte. Va lo
        # último: si algo se tuerce aquí, lo de todos los días ya está hecho.
        if recuperar:
            recuperados, _pendientes = recuperar_faltantes(
                conn, cursor, 'PROYECTOS', ruta_proyectos, faltan,
                hasta=t_inicio + MINUTOS_MAX_PASE * 60)

    except Exception as e:
        logger.exception(f"Error durante la reindexación: {e}")
    finally:
        conn.close()

    duration = (datetime.datetime.now() - start).total_seconds()
    logger.info(f"REINDEXACIÓN COMPLETADA: {total} archivos en {duration:.1f}s"
                + (f" · {recuperados:,} recuperados" if recuperados else ""))
    logger.info("=" * 60)


def main_recuperar(minutos=MINUTOS_MAX_PASE, origen='PROYECTOS', ruta=None):
    """Solo la recuperación, lanzada a mano y fuera de horario:

        python reindexar_diario.py --recuperar --minutos 90

    No toca el sello de "última indexación", ni las placas CE, ni purga nada.
    Devuelve el código de salida del proceso."""
    _log_propio(LOG_FILE)
    t_inicio = time.monotonic()
    logger.info("=" * 60)
    logger.info(f"RECUPERACIÓN A MANO de {origen} (tope: {minutos:g} min)")
    logger.info("=" * 60)
    ruta = resolver_ruta_nas(ruta or RUTAS_NAS[origen])
    if not ruta:
        logger.error(f"{origen}: el NAS no responde — no se recupera nada.")
        return 2
    if not misma_base(ruta, origen):
        logger.error(f"{origen}: el NAS se ha leído como {ruta} y el índice guarda "
                     f"{RUTAS_NAS.get(origen)} — no se recupera nada.")
        return 2
    try:
        conn = psycopg2.connect(**PG_CONFIG)
    except Exception as e:
        logger.error(f"No se pudo conectar a PostgreSQL: {e}")
        return 1
    try:
        cursor = conn.cursor()
        faltan = []
        # dias=0: nada cuenta como reciente, así que no se reindexa nada de lo
        # que ya está; el recorrido solo apunta lo que falta.
        logger.info("  Recorriendo el NAS para ver qué falta (lo que ya está no se toca)...")
        indexar_proyectos_recientes(conn, cursor, ruta, dias=0, origen=origen, faltan=faltan)
        recuperados, pendientes = recuperar_faltantes(conn, cursor, origen, ruta, faltan,
                                                      hasta=t_inicio + minutos * 60)
    finally:
        conn.close()
    logger.info(f"RECUPERACIÓN A MANO TERMINADA: {recuperados:,} recuperados, "
                f"{pendientes:,} pendientes, en {(time.monotonic() - t_inicio) / 60:.1f} min.")
    logger.info("=" * 60)
    return 0


def _leer_argumentos(argv):
    import argparse
    p = argparse.ArgumentParser(description="Reindexación diaria del Buscador de Piezas ALSI.")
    p.add_argument('--recuperar', action='store_true',
                   help="solo recuperar lo que falta en el índice de PROYECTOS")
    p.add_argument('--minutos', type=float, default=MINUTOS_MAX_PASE,
                   help=f"tope de tiempo de la recuperación (por defecto {MINUTOS_MAX_PASE})")
    return p.parse_args(argv)


if __name__ == '__main__':
    _args = _leer_argumentos(sys.argv[1:])
    if _args.recuperar:
        sys.exit(main_recuperar(_args.minutos))
    main()
