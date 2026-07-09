# -*- coding: utf-8 -*-
"""
Reindexación automática diaria para el Buscador de Piezas ALSI.
V1.0.7 - Script headless (sin GUI) para ejecutar via Programador de Tareas.

Comportamiento:
  - Reindexa BIBLIOTECA_3D y ALSI_ESTANDAR (completos).
  - Reindexa PROYECTOS: solo archivos modificados en los últimos 7 días
    (compara st_mtime con la fecha de última indexación guardada en PG).
  - Registra logs en ~/.alsi_busqueda/reindexacion.log

Uso:
  python reindexar_diario.py
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

CARPETAS_EXCLUIDAS = {
    'ARCHIVOS REPETIDOS', 'REVISION MIGRACION', '__pycache__',
    'BACKUPS', 'build', 'dist', '.git',
}

EXTENSIONES_VALIDAS = ('.sldprt', '.sldasm', '.slddrw', '.dwg', '.pdf', '.step', '.stp', '.iges', '.igs')

# Días hacia atrás para considerar "reciente" en PROYECTOS
DIAS_RECIENTES = 7

# ----- Logging -----
LOG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "reindexacion.log"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
# También imprimir en consola
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

logger = logging.getLogger(__name__)


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


def extraer_sw_props(filepath):
    """Intenta extraer propiedades SW via SwPropExtractor.exe"""
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
        
        result = subprocess.run(
            [exe_path, license_key, filepath],
            capture_output=True, text=True, encoding='utf-8',
            startupinfo=startupinfo, timeout=20  # V2.0.0: 20s (antes 5)
        )
        
        if result.stdout:
            data = json.loads(result.stdout)
            if "error" not in data:
                return data
    except Exception:
        pass
    return {}


def upsert_archivo(cursor, file, origen, metadata, full_path, stats, sw_props):
    """Inserta o actualiza un archivo en buscador.archivos"""
    cursor.execute('''
        INSERT INTO buscador.archivos 
        (nombre_archivo, origen, anio, cliente, proyecto, tipo_carpeta, 
         ruta_completa, extension, ultima_modificacion, tamano_bytes,
         codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden,
         sw_material, sw_tratamiento, sw_espesor, sw_laser, sw_torno, sw_fresa,
         sw_soldadura, sw_pintura, sw_montaje, sw_tipo_cierre, sw_filo_guiado,
         sw_onda, sw_cangilon, sw_runer)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            indexado_en=NOW()
    ''', (
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
    ))


def indexar_completo(conn, cursor, origen, ruta_base):
    """Indexación completa: borra todo el origen y reindexa."""
    logger.info(f"  Indexación COMPLETA de {origen}...")
    cursor.execute("DELETE FROM buscador.archivos WHERE origen = %s", (origen,))
    conn.commit()

    tipo_map = {'BIBLIOTECA_3D': 'BIBLIOTECA', 'ALSI_ESTANDAR': 'ESTANDAR'}
    count = 0
    excluir_upper = {x.upper() for x in CARPETAS_EXCLUIDAS}

    for root, dirs, files in os.walk(ruta_base):
        dirs[:] = [d for d in dirs if d.upper() not in excluir_upper and not d.startswith('~')]
        for file in files:
            if file.startswith("~$") or file == 'Thumbs.db':
                continue
            if not file.lower().endswith(EXTENSIONES_VALIDAS):
                continue

            full_path = os.path.join(root, file)
            metadata = {
                'año': 0, 'cliente': 'ALSI', 'proyecto': origen,
                'tipo': tipo_map.get(origen, 'OTRO'),
                'codigo_proyecto': '', 'nombre_proyecto': origen,
                'codigo_orden': '', 'nombre_orden': ''
            }

            try:
                stats = os.stat(full_path)
                sw_props = {}
                if file.lower().endswith(('.sldprt', '.sldasm')):
                    sw_props = extraer_sw_props(full_path)
                upsert_archivo(cursor, file, origen, metadata, full_path, stats, sw_props)
                count += 1
                if count % 2000 == 0:
                    conn.commit()
                    logger.info(f"    {origen}: {count} archivos...")
            except Exception as ex:
                logger.debug(f"Error en {full_path}: {ex}")
                continue

    conn.commit()
    logger.info(f"  {origen}: {count} archivos indexados.")
    return count


def indexar_proyectos_recientes(conn, cursor, ruta_base, dias=DIAS_RECIENTES):
    """Indexa solo archivos de PROYECTOS modificados en los últimos N días."""
    logger.info(f"  Indexación INCREMENTAL de PROYECTOS (últimos {dias} días)...")
    
    umbral_ts = int((datetime.datetime.now() - datetime.timedelta(days=dias)).timestamp())
    count = 0
    excluir_upper = {x.upper() for x in CARPETAS_EXCLUIDAS}

    for root, dirs, files in os.walk(ruta_base):
        dirs[:] = [d for d in dirs if d.upper() not in excluir_upper and not d.startswith('~')]
        for file in files:
            if file.startswith("~$") or file == 'Thumbs.db':
                continue
            if not file.lower().endswith(EXTENSIONES_VALIDAS):
                continue

            full_path = os.path.join(root, file)
            try:
                stats = os.stat(full_path)
                # Solo procesar si fue modificado recientemente
                if int(stats.st_mtime) < umbral_ts:
                    continue

                metadata = extraer_metadata_proyecto(root, ruta_base)
                sw_props = {}
                if file.lower().endswith(('.sldprt', '.sldasm')):
                    sw_props = extraer_sw_props(full_path)
                upsert_archivo(cursor, file, 'PROYECTOS', metadata, full_path, stats, sw_props)
                count += 1
                if count % 2000 == 0:
                    conn.commit()
                    logger.info(f"    PROYECTOS (recientes): {count} archivos...")
            except Exception as ex:
                logger.debug(f"Error en {full_path}: {ex}")
                continue

    conn.commit()
    logger.info(f"  PROYECTOS (recientes): {count} archivos actualizados.")
    return count


def main():
    logger.info("=" * 60)
    logger.info("INICIO REINDEXACIÓN AUTOMÁTICA DIARIA")
    logger.info("=" * 60)
    start = datetime.datetime.now()

    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cursor = conn.cursor()
        logger.info("Conexión a PostgreSQL OK")
    except Exception as e:
        logger.error(f"No se pudo conectar a PostgreSQL: {e}")
        sys.exit(1)

    total = 0
    try:
        # 1. BIBLIOTECA_3D (completa)
        ruta = RUTAS_NAS.get('BIBLIOTECA_3D')
        if ruta and os.path.exists(ruta):
            total += indexar_completo(conn, cursor, 'BIBLIOTECA_3D', ruta)
        else:
            logger.warning(f"Ruta BIBLIOTECA_3D no accesible: {ruta}")

        # 2. ALSI_ESTANDAR (completa)
        ruta = RUTAS_NAS.get('ALSI_ESTANDAR')
        if ruta and os.path.exists(ruta):
            total += indexar_completo(conn, cursor, 'ALSI_ESTANDAR', ruta)
        else:
            logger.warning(f"Ruta ALSI_ESTANDAR no accesible: {ruta}")

        # 3. PROYECTOS (solo recientes)
        ruta = RUTAS_NAS.get('PROYECTOS')
        if ruta and os.path.exists(ruta):
            total += indexar_proyectos_recientes(conn, cursor, ruta)
        else:
            logger.warning(f"Ruta PROYECTOS no accesible: {ruta}")

        # Actualizar estado
        for origen in RUTAS_NAS:
            cursor.execute('''
                INSERT INTO buscador.estado_indexacion (origen, ruta_base, ultima_indexacion, archivos_indexados)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (origen) DO UPDATE SET
                    ultima_indexacion = EXCLUDED.ultima_indexacion,
                    archivos_indexados = EXCLUDED.archivos_indexados
            ''', (origen, RUTAS_NAS[origen], int(datetime.datetime.now().timestamp()), total))
        conn.commit()

    except Exception as e:
        logger.exception(f"Error durante la reindexación: {e}")
    finally:
        conn.close()

    duration = (datetime.datetime.now() - start).total_seconds()
    logger.info(f"REINDEXACIÓN COMPLETADA: {total} archivos en {duration:.1f}s")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
