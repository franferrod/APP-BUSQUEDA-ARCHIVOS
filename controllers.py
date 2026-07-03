import os
import re
import datetime
import threading
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal
from models import IndexManager, logger
from sw_properties import extractor
import xml.etree.ElementTree as ET

# Cache para materiales
_MATERIALES_VALIDOS_CACHE = None

# v1.0.7 - Carpetas a excluir durante indexación
CARPETAS_EXCLUIDAS = {
    'ARCHIVOS REPETIDOS', 'REVISION MIGRACION', '__pycache__',
    'BACKUPS', 'build', 'dist', '.git', 'D:\\MIGRACION_NAS_BACKUPS',
}

class IndexadorThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(int, float)
    error = pyqtSignal(str)
    status = pyqtSignal(str)
    comp_finished = pyqtSignal(str, int)  # compañero, archivos indexados

    def __init__(self, db, rutas_dict, compañeros_sel=None, años_sel=None):
        super().__init__()
        self.db = db
        self.rutas = rutas_dict
        self.compañeros_sel = compañeros_sel  # None = todos
        self.años_sel = [int(a) for a in años_sel] if años_sel else None # None = todos
        self._cancelar = False

    def cancelar(self):
        """Activa el flag de cancelación (thread-safe)"""
        self._cancelar = True

    def run(self):
        try:
            logger.info("Iniciando proceso de indexación...")
            start_time = datetime.datetime.now()
            total_indexados = 0
            
            rutas_a_indexar = {k: v for k, v in self.rutas.items() 
                              if self.compañeros_sel is None or k in self.compañeros_sel}
            
            wrapper = self.db.get_connection()
            try:
                conn = wrapper._conn
                cursor = conn.cursor()
                
                for comp, ruta_val in rutas_a_indexar.items():
                    if self._cancelar:
                        self.status.emit("⏹ Indexación cancelada")
                        break
                    
                    # Normalizar ruta_val a lista (soporte para múltiples rutas V1.0.0)
                    rutas_lista = ruta_val if isinstance(ruta_val, list) else [ruta_val]
                    
                    # Limpiar datos previos antes de empezar con todas las rutas de este origen
                    if self.años_sel:
                        placeholders = ','.join(['%s' for _ in self.años_sel])
                        query_del = f"DELETE FROM buscador.archivos WHERE origen = %s AND anio IN ({placeholders})"
                        cursor.execute(query_del, [comp] + self.años_sel)
                    else:
                        cursor.execute("DELETE FROM buscador.archivos WHERE origen = %s", (comp,))
                    conn.commit()
                    
                    count_comp = 0
                    is_commercial = comp in ('BIBLIOTECA_3D', 'ALSI_ESTANDAR')

                    for ruta_base in rutas_lista:
                        if self._cancelar: break
                        
                        if not os.path.exists(ruta_base):
                            logger.warning(f"Ruta no disponible para {comp}: {ruta_base}")
                            self.status.emit(f"⚠️ Ruta no disponible: {comp}")
                            continue
                        
                        logger.info(f"Escaneando {comp} en {ruta_base}")
                        self.status.emit(f"Escaneando {comp}...")
                        
                        # Traversal optimizado (V1.0.0)
                        for root, dirs, files in os.walk(ruta_base):
                            if self._cancelar: break
                            
                            # v1.0.7 - Excluir carpetas de migración y temporales
                            dirs[:] = [d for d in dirs if d.upper() not in {x.upper() for x in CARPETAS_EXCLUIDAS} and not d.startswith('~')]

                            for file in files:
                                # 1. Ignorar temporales y extensiones no deseadas
                                if file.startswith("~$") or file == 'Thumbs.db' or not file.lower().endswith(('.sldprt', '.sldasm', '.slddrw', '.dwg', '.pdf', '.step', '.stp', '.iges', '.igs')):
                                    continue
                                    
                                full_path = os.path.join(root, file)
                                
                                if is_commercial:
                                    # Metadatos simplificados para comerciales
                                    tipo_map = {'BIBLIOTECA_3D': 'BIBLIOTECA', 'ALSI_ESTANDAR': 'ESTANDAR'}
                                    metadata = {
                                        'año': 0,
                                        'cliente': 'ALSI',
                                        'proyecto': comp,
                                        'tipo': tipo_map.get(comp, 'OTRO'),
                                        'codigo_proyecto': '',
                                        'nombre_proyecto': comp,
                                        'codigo_orden': '',
                                        'nombre_orden': ''
                                    }
                                else:
                                    metadata = self.extraer_metadata(file, root, origen=comp, ruta_base=ruta_base)
                                    # Doble check de año si estamos en modo selectivo
                                    if self.años_sel and metadata['año'] not in self.años_sel:
                                        continue

                                try:
                                    stats = os.stat(full_path)
                                    
                                    # V1.0.6 - Extraer propiedades SolidWorks si es .sldprt o .sldasm
                                    sw_props = None
                                    is_sw_file = file.lower().endswith(('.sldprt', '.sldasm'))
                                    if is_sw_file:
                                        try:
                                            self.status.emit(f"Extrayendo propiedades SW: {file[:20]}...")
                                            sw_props = extractor.extract_properties(full_path)
                                        except Exception as ex:
                                            logger.debug(f"SolidWorks DM falló para {file}: {ex}")
                                            sw_props = {}
                                    if not sw_props:
                                        sw_props = {}

                                    cursor.execute('''
                                        INSERT INTO buscador.archivos 
                                        (nombre_archivo, origen, anio, cliente, proyecto, tipo_carpeta, 
                                         ruta_completa, extension, ultima_modificacion, tamano_bytes,
                                         codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden,
                                         sw_material, sw_tratamiento, sw_espesor, sw_laser, sw_torno, sw_fresa,
                                         sw_soldadura, sw_pintura, sw_montaje, sw_tipo_cierre, sw_filo_guiado,
                                         sw_onda, sw_cangilon, sw_runer)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        ON CONFLICT (ruta_completa) DO UPDATE SET
                                            nombre_archivo = EXCLUDED.nombre_archivo,
                                            origen = EXCLUDED.origen,
                                            anio = EXCLUDED.anio,
                                            cliente = EXCLUDED.cliente,
                                            proyecto = EXCLUDED.proyecto,
                                            tipo_carpeta = EXCLUDED.tipo_carpeta,
                                            extension = EXCLUDED.extension,
                                            ultima_modificacion = EXCLUDED.ultima_modificacion,
                                            tamano_bytes = EXCLUDED.tamano_bytes,
                                            codigo_proyecto = EXCLUDED.codigo_proyecto,
                                            nombre_proyecto = EXCLUDED.nombre_proyecto,
                                            codigo_orden = EXCLUDED.codigo_orden,
                                            nombre_orden = EXCLUDED.nombre_orden,
                                            sw_material = EXCLUDED.sw_material,
                                            sw_tratamiento = EXCLUDED.sw_tratamiento,
                                            sw_espesor = EXCLUDED.sw_espesor,
                                            sw_laser = EXCLUDED.sw_laser,
                                            sw_torno = EXCLUDED.sw_torno,
                                            sw_fresa = EXCLUDED.sw_fresa,
                                            sw_soldadura = EXCLUDED.sw_soldadura,
                                            sw_pintura = EXCLUDED.sw_pintura,
                                            sw_montaje = EXCLUDED.sw_montaje,
                                            sw_tipo_cierre = EXCLUDED.sw_tipo_cierre,
                                            sw_filo_guiado = EXCLUDED.sw_filo_guiado,
                                            sw_onda = EXCLUDED.sw_onda,
                                            sw_cangilon = EXCLUDED.sw_cangilon,
                                            sw_runer = EXCLUDED.sw_runer,
                                            indexado_en = NOW()
                                    ''', (
                                        file, comp, metadata['año'], metadata['cliente'], metadata['proyecto'], 
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
                                    count_comp += 1
                                    total_indexados += 1
                                    
                                    if total_indexados % 500 == 0:
                                        self.progress.emit(total_indexados)
                                        self.status.emit(f"Escaneando {comp}... {count_comp} archivos")
                                    
                                    if total_indexados % 2000 == 0:
                                        conn.commit()
                                except Exception as ex:
                                    logger.debug(f"Error accediendo a archivo {full_path}: {ex}")
                                    continue
                                
                    cursor.execute('''
                        INSERT INTO buscador.estado_indexacion 
                        (origen, ruta_base, ultima_indexacion, archivos_indexados)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (origen) DO UPDATE SET
                            ruta_base = EXCLUDED.ruta_base,
                            ultima_indexacion = EXCLUDED.ultima_indexacion,
                            archivos_indexados = EXCLUDED.archivos_indexados
                    ''', (comp, ruta_base, int(datetime.datetime.now().timestamp()), count_comp))
                    conn.commit()
                    self.comp_finished.emit(comp, count_comp)
            finally:
                wrapper.close()
            
            duration = (datetime.datetime.now() - start_time).total_seconds()
            logger.info(f"Indexación completada: {total_indexados} archivos en {duration:.2f}s")
            self.finished.emit(total_indexados, duration)
            
        except Exception as e:
            logger.exception("Error crítico durante la indexación")
            self.error.emit(str(e))

    def extraer_metadata(self, nombre_archivo, ruta_carpeta, origen=None, ruta_base=None):
        """
        Extrae información jerárquica de la ruta del archivo.
        v1.0.7 - Nuevo parsing sin carpeta AÑO: CLIENTE > PROYECTO > ORDEN > TIPO_CARPETA
        El año se infiere del código de proyecto (primeros 2 dígitos → 20XX).
        """
        metadata = {
            'año': 0,
            'cliente': 'DESCONOCIDO',
            'proyecto': 'DESCONOCIDO',
            'codigo_proyecto': '',
            'nombre_proyecto': '',
            'codigo_orden': '',
            'nombre_orden': '',
            'tipo': 'OTRO'
        }
        
        ruta_upper = ruta_carpeta.upper()

        # --- Origen: PROYECTOS (estructura NAS principal) ---
        if origen == 'PROYECTOS' and ruta_base:
            try:
                ruta_relativa = os.path.relpath(ruta_carpeta, ruta_base)
                parts = Path(ruta_relativa).parts
                
                # parts[0] = CLIENTE
                if len(parts) >= 1:
                    metadata['cliente'] = parts[0]
                
                # parts[1] = PROYECTO (formato: "26046 LINEA PALETIZADO")
                if len(parts) >= 2:
                    raw_proj = parts[1]
                    match_proj = re.match(r'^(\d+)\s+(.*)', raw_proj)
                    if match_proj:
                        metadata['codigo_proyecto'] = match_proj.group(1)
                        metadata['nombre_proyecto'] = match_proj.group(2)
                        metadata['proyecto'] = raw_proj
                        
                        # Inferir año del código de proyecto (primeros 2 dígitos → 20XX)
                        codigo = match_proj.group(1)
                        if len(codigo) >= 2 and codigo[:2].isdigit():
                            metadata['año'] = int('20' + codigo[:2])
                    else:
                        metadata['nombre_proyecto'] = raw_proj
                        metadata['proyecto'] = raw_proj
                
                # parts[2] = ORDEN (formato: "133 LINEA PALETIZADO")
                if len(parts) >= 3:
                    raw_orden = parts[2]
                    match_orden = re.match(r'^(\d+)\s+(.*)', raw_orden)
                    if match_orden:
                        metadata['codigo_orden'] = match_orden.group(1)
                        metadata['nombre_orden'] = match_orden.group(2)
                    else:
                        metadata['nombre_orden'] = raw_orden
                
                # parts[3+] = Buscar tipo_carpeta
                if len(parts) >= 4:
                    for part in parts[3:]:
                        part_upper = part.upper()
                        if 'MECANIC' in part_upper:
                            metadata['tipo'] = 'MECANICA'
                            break
                        elif 'LAYOUT' in part_upper:
                            metadata['tipo'] = 'LAYOUT'
                            break
                        elif 'LISTADO' in part_upper:
                            metadata['tipo'] = 'LISTADOS'
                            break
                        elif 'OFERTA' in part_upper or 'PEDIDO' in part_upper:
                            metadata['tipo'] = 'OFERTAS Y PEDIDOS'
                            break
                        elif 'PLIEGO' in part_upper:
                            metadata['tipo'] = 'PLIEGO DE CONDICIONES'
                            break
                else:
                    # Fallback: clasificar tipo desde ruta completa
                    if 'MECANIC' in ruta_upper: metadata['tipo'] = 'MECANICA'
                    elif 'LAYOUT' in ruta_upper: metadata['tipo'] = 'LAYOUT'
                    elif 'LISTADO' in ruta_upper: metadata['tipo'] = 'LISTADOS'
                    elif 'OFERTA' in ruta_upper or 'PEDIDO' in ruta_upper: metadata['tipo'] = 'OFERTAS Y PEDIDOS'
                    elif 'PLIEGO' in ruta_upper: metadata['tipo'] = 'PLIEGO DE CONDICIONES'
                    
            except Exception as ex:
                logger.debug(f"Error parseando ruta relativa para PROYECTOS: {ex}")
            
            return metadata

        # --- Origen: BIBLIOTECA_3D / ALSI_ESTANDAR ---
        if origen in ('BIBLIOTECA_3D', 'ALSI_ESTANDAR'):
            tipo = 'BIBLIOTECA' if origen == 'BIBLIOTECA_3D' else 'ESTANDAR'
            metadata['año'] = 0
            metadata['cliente'] = 'ALSI'
            metadata['proyecto'] = origen
            metadata['tipo'] = tipo
            return metadata

        # --- Fallback: origen no reconocido o None ---
        # Intentar lógica antigua: buscar anclaje "AÑO XXXX"
        path_obj = Path(ruta_carpeta)
        parts = path_obj.parts
        
        idx_ano = -1
        for i, part in enumerate(parts):
            if part.upper().replace("Ñ", "N").startswith("ANO 20"):
                match = re.search(r'20\d{2}', part)
                if match:
                    metadata['año'] = int(match.group(0))
                    idx_ano = i
                    break
        
        if idx_ano != -1 and idx_ano + 3 < len(parts):
            metadata['cliente'] = parts[idx_ano + 1]
            
            raw_proj = parts[idx_ano + 2]
            match_proj = re.match(r'^(\d+)\s+(.+)$', raw_proj)
            if match_proj:
                metadata['codigo_proyecto'] = match_proj.group(1)
                metadata['nombre_proyecto'] = match_proj.group(2)
                metadata['proyecto'] = raw_proj
            else:
                metadata['nombre_proyecto'] = raw_proj
                metadata['proyecto'] = raw_proj

            raw_orden = parts[idx_ano + 3]
            match_orden = re.match(r'^(\d+)\s+(.+)$', raw_orden)
            if match_orden:
                metadata['codigo_orden'] = match_orden.group(1)
                metadata['nombre_orden'] = match_orden.group(2)
            else:
                metadata['nombre_orden'] = raw_orden

        # Fallback amplio: buscar año en la ruta como patrón suelto
        if metadata['año'] == 0:
            match_año_loose = re.search(r'[\\/](20\d{2})[\\/]', ruta_carpeta)
            if match_año_loose:
                metadata['año'] = int(match_año_loose.group(1))
        
        # Si aún no hay año, intentar inferir desde código de proyecto
        if metadata['año'] == 0 and metadata['codigo_proyecto']:
            codigo = metadata['codigo_proyecto']
            if len(codigo) >= 2 and codigo[:2].isdigit():
                metadata['año'] = int('20' + codigo[:2])

        # Clasificar tipo desde ruta completa
        if 'MECANIC' in ruta_upper: metadata['tipo'] = 'MECANICA'
        elif 'LAYOUT' in ruta_upper: metadata['tipo'] = 'LAYOUT'
        elif 'LISTADO' in ruta_upper: metadata['tipo'] = 'LISTADOS'
        elif 'OFERTA' in ruta_upper or 'PEDIDO' in ruta_upper: metadata['tipo'] = 'OFERTAS Y PEDIDOS'
        elif 'PLIEGO' in ruta_upper: metadata['tipo'] = 'PLIEGO DE CONDICIONES'
            
        return metadata


class SearchController:
    """Orquestador entre la Vista y el Modelo"""
    def __init__(self, db):
        self.db = db

    def perform_search(self, term, companions, years, extensiones=None, folder_type="TODOS",
                      clientes=None, proyectos=None, ordenes=None, props_fabricacion=None, props_bandas=None, material=None, tratamiento=None, espesor=None):
        return self.db.buscar(term, companions, years, extensiones, folder_type, clientes, proyectos, ordenes, props_fabricacion, props_bandas, material, tratamiento, espesor)

    def save_preference(self, key, value):
        self.db.guardar_preferencia(key, value)

    def load_preference(self, key, default=None):
        return self.db.obtener_preferencia(key, default)

    def get_all_clients(self, companions=None, years=None):
        # V1.0.0: Excluir clientes que empiezan por número (ej: "0. ALSI", "01 ENVIADOS")
        todos = self.db.obtener_clientes(companions, years)
        return [c for c in todos if c and not c[0].isdigit()]

    def get_all_projects(self, clientes=None, companions=None, years=None):
        return self.db.obtener_proyectos(clientes, companions, years)
        
    def get_all_materiales(self):
        global _MATERIALES_VALIDOS_CACHE
        raw_materiales = self.db.obtener_materiales()
        
        # Cargar lista oficial de materiales desde el NAS si no está en caché
        if _MATERIALES_VALIDOS_CACHE is None:
            _MATERIALES_VALIDOS_CACHE = set()
            ruta_sldmat = r"\\192.168.1.10\Oficina Tecnica\ALSI UTILIDADES OT\SOLIDWORKS MATERIALES PERSONALIZADOS\MATERIALES ALSI.sldmat"
            try:
                if os.path.exists(ruta_sldmat):
                    tree = ET.parse(ruta_sldmat)
                    root = tree.getroot()
                    for elem in root.iter():
                        if 'material' in elem.tag.lower():
                            name = elem.get('name')
                            if name:
                                _MATERIALES_VALIDOS_CACHE.add(name.strip().lower())
            except Exception as e:
                logger.error(f"Error parseando sldmat: {e}")
        
        if not _MATERIALES_VALIDOS_CACHE:
            return raw_materiales
            
        # Filtrar
        materiales_filtrados = []
        for mat in raw_materiales:
            if mat and mat.strip().lower() in _MATERIALES_VALIDOS_CACHE:
                materiales_filtrados.append(mat)
                
        return sorted(materiales_filtrados)
        
    def get_all_tratamientos(self):
        return self.db.obtener_tratamientos()

    def get_all_espesores(self):
        return self.db.obtener_espesores()
