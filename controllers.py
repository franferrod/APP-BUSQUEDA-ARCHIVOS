import os
import re
import datetime
import threading
import time
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal
from models import IndexManager, logger

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
            
            with self.db.get_connection() as conn:
                for comp, ruta_val in rutas_a_indexar.items():
                    if self._cancelar:
                        self.status.emit("⏹ Indexación cancelada")
                        break
                    
                    # Normalizar ruta_val a lista (soporte para múltiples rutas V1.0.0)
                    rutas_lista = ruta_val if isinstance(ruta_val, list) else [ruta_val]
                    
                    # Limpiar datos previos antes de empezar con todas las rutas de este compañero
                    if self.años_sel:
                        placeholders = ','.join(['?' for _ in self.años_sel])
                        query_del = f"DELETE FROM archivos WHERE compañero = ? AND año IN ({placeholders})"
                        conn.execute(query_del, [comp] + self.años_sel)
                    else:
                        conn.execute("DELETE FROM archivos WHERE compañero = ?", (comp,))
                    
                    count_comp = 0
                    is_commercial = comp in ['BIBLIOTECA', 'ESTANDAR', 'DARKWEB_JA']

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
                            
                            # Pruning de directorios: Si estamos en la raíz o nivel superior,
                            # solo entramos en carpetas "ANO 20XX" si están en años_sel
                            # NOTA: No filtramos por año en BIBLIOTECA/ESTANDAR (V1.0.0)
                            if self.años_sel and not is_commercial:
                                # Verificamos si estamos en un nivel donde el nombre del directorio
                                # indica el año (Formato: ANO 20XX)
                                dirname = os.path.basename(root).upper().replace("Ñ", "N")
                                if dirname.startswith("ANO 20"):
                                    match = re.search(r'20\d{2}', dirname)
                                    if match:
                                        dir_year = int(match.group(0))
                                        if dir_year not in self.años_sel:
                                            dirs[:] = [] # No descender en este directorio
                                            continue
                                
                                # También filtramos la lista de subdirectorios en la raíz
                                # para evitar entrar en años no deseados
                                new_dirs = []
                                for d in dirs:
                                    d_upper = d.upper().replace("Ñ", "N")
                                    if d_upper.startswith("ANO 20"):
                                        match = re.search(r'20\d{2}', d_upper)
                                        if match:
                                            year_candidate = int(match.group(0))
                                            if year_candidate in self.años_sel:
                                                new_dirs.append(d)
                                        else:
                                            new_dirs.append(d) # No es carpeta de año, entramos por si acaso
                                    else:
                                        new_dirs.append(d) # No es carpeta de año standard
                                dirs[:] = new_dirs

                            for file in files:
                                # 1. Ignorar temporales y extensiones no deseadas
                                if file.startswith("~$") or not file.lower().endswith(('.sldprt', '.sldasm', '.slddrw', '.dwg', '.pdf', '.step', '.stp', '.iges', '.igs')):
                                    continue
                                    
                                full_path = os.path.join(root, file)
                                
                                if is_commercial:
                                    # Metadatos simplificados para comerciales
                                    metadata = {
                                        'año': 0,
                                        'cliente': 'ALSI',
                                        'proyecto': comp, # 'BIBLIOTECA' o 'ESTANDAR'
                                        'tipo': 'COMERCIAL',
                                        'codigo_proyecto': '',
                                        'nombre_proyecto': comp,
                                        'codigo_orden': '',
                                        'nombre_orden': ''
                                    }
                                else:
                                    metadata = self.extraer_metadata(file, root)
                                    # Doble check de año si estamos en modo selectivo
                                    if self.años_sel and metadata['año'] not in self.años_sel:
                                        continue

                                try:
                                    stats = os.stat(full_path)
                                    
                                    # V1.0.4: Propiedades SW se extraen en segundo plano (no durante indexación)
                                    conn.execute('''
                                        INSERT OR REPLACE INTO archivos 
                                        (nombre_archivo, compañero, año, cliente, proyecto, tipo_carpeta, 
                                         ruta_completa, extension, ultima_modificacion, tamaño_bytes,
                                         codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (
                                        file, comp, metadata['año'], metadata['cliente'], metadata['proyecto'], 
                                        metadata['tipo'], full_path, Path(file).suffix.lower(),
                                        int(stats.st_mtime), stats.st_size,
                                        metadata['codigo_proyecto'], metadata['nombre_proyecto'],
                                        metadata['codigo_orden'], metadata['nombre_orden']
                                    ))
                                    count_comp += 1
                                    total_indexados += 1
                                    
                                    if total_indexados % 500 == 0:
                                        self.progress.emit(total_indexados)
                                        self.status.emit(f"Escaneando {comp}... {count_comp} archivos")
                                except Exception as ex:
                                    logger.debug(f"Error accediendo a archivo {full_path}: {ex}")
                                    continue
                                
                    conn.execute('''
                        INSERT OR REPLACE INTO estado_indexacion 
                        (compañero, ruta_base, ultima_indexacion, archivos_indexados)
                        VALUES (?, ?, ?, ?)
                    ''', (comp, ruta_base, int(datetime.datetime.now().timestamp()), count_comp))
                    conn.commit()
                    self.comp_finished.emit(comp, count_comp)
            
            duration = (datetime.datetime.now() - start_time).total_seconds()
            logger.info(f"Indexación completada: {total_indexados} archivos en {duration:.2f}s")
            self.finished.emit(total_indexados, duration)
            
        except Exception as e:
            logger.exception("Error crítico durante la indexación")
            self.error.emit(str(e))

    def extraer_metadata(self, nombre_archivo, ruta_carpeta):
        """
        Extrae información jerárquica: AÑO > CLIENTE > PROYECTO > ORDEN
        # V1.0.0 - Parsing posicional robusto.
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
        
        path_obj = Path(ruta_carpeta)
        parts = path_obj.parts
        ruta_upper = ruta_carpeta.upper()

        # 1. Buscar el anclaje "AÑO XXXX"
        idx_ano = -1
        for i, part in enumerate(parts):
            if part.upper().replace("Ñ", "N").startswith("ANO 20"): # Normalizar AÑO/ANO
                match = re.search(r'20\d{2}', part)
                if match:
                    metadata['año'] = int(match.group(0))
                    idx_ano = i
                    break
        
        # 2. Navegación jerárquica relativa
        if idx_ano != -1 and idx_ano + 3 < len(parts):
            # CLIENTE (Directamente bajo AÑO)
            metadata['cliente'] = parts[idx_ano + 1]
            
            # PROYECTO (Bajo Cliente) - Formato: "12345 NOMBRE..."
            raw_proj = parts[idx_ano + 2]
            match_proj = re.match(r'^(\d+)\s+(.+)$', raw_proj)
            if match_proj:
                metadata['codigo_proyecto'] = match_proj.group(1)
                metadata['nombre_proyecto'] = match_proj.group(2)
                metadata['proyecto'] = raw_proj # Legacy para compatibilidad
            else:
                metadata['nombre_proyecto'] = raw_proj
                metadata['proyecto'] = raw_proj

            # ORDEN (Bajo Proyecto) - Formato: "123 NOMBRE..."
            raw_orden = parts[idx_ano + 3]
            match_orden = re.match(r'^(\d+)\s+(.+)$', raw_orden)
            if match_orden:
                metadata['codigo_orden'] = match_orden.group(1)
                metadata['nombre_orden'] = match_orden.group(2)
            else:
                metadata['nombre_orden'] = raw_orden

        # 3. Fallback: Si no hay estructura, intentar lógica antigua para Año
        if metadata['año'] == 0:
            match_año_loose = re.search(r'[\\/](20\d{2})[\\/]', ruta_carpeta)
            if match_año_loose:
                metadata['año'] = int(match_año_loose.group(1))

        # 4. Clasificar tipo (Mantiene lógica anterior)
        if 'MECANIC' in ruta_upper: metadata['tipo'] = 'MECANICA'
        elif 'LAYOUT' in ruta_upper: metadata['tipo'] = 'LAYOUT'
        elif 'LISTADO' in ruta_upper: metadata['tipo'] = 'LISTADOS'
        elif 'OFERTA' in ruta_upper or 'PEDIDO' in ruta_upper: metadata['tipo'] = 'OFERTAS Y PEDIDOS'
        elif 'PLIEGO' in ruta_upper: metadata['tipo'] = 'PLIEGO DE CONDICIONES'
            
        return metadata

# ============================================================================
# V1.0.4 - Extractor de Propiedades SolidWorks (COM API, segundo plano)
# ============================================================================

class SWPropertyExtractorThread(QThread):
    """
    Hilo que extrae propiedades personalizadas de archivos SolidWorks
    usando la API COM de SolidWorks en modo batch (segundo plano).
    Se ejecuta DESPUÉS de la indexación normal.
    """
    progress = pyqtSignal(int, int)  # procesados, total
    finished = pyqtSignal(int, float)  # total procesados, duración
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    file_extracted = pyqtSignal(str, dict)  # ruta, propiedades extraídas

    def __init__(self, db, batch_size=500):
        super().__init__()
        self.db = db
        self.batch_size = batch_size
        self._cancelar = False

    def cancelar(self):
        self._cancelar = True

    def run(self):
        import pythoncom
        pythoncom.CoInitialize()
        try:
            self._run_extraction()
        finally:
            pythoncom.CoUninitialize()

    def _run_extraction(self):
        import win32com.client
        import pythoncom
        
        # 1. Obtener archivos SW pendientes de extracción
        pending = self._get_pending_files()
        if not pending:
            self.status.emit("✅ Todas las propiedades SW ya están extraídas")
            self.finished.emit(0, 0.0)
            return

        total = len(pending)
        self.status.emit(f"🔧 Extrayendo propiedades de {total} archivos SW...")
        logger.info(f"SWExtractor: {total} archivos pendientes")

        # 2. Conectar a SolidWorks
        swApp = None
        try:
            try:
                swApp = win32com.client.Dispatch("SldWorks.Application")
                logger.info("SWExtractor: Conectado a SolidWorks")
            except Exception as e:
                self.error.emit(f"No se pudo conectar a SolidWorks: {e}\nAsegúrate de que SolidWorks esté abierto.")
                return

            swApp.Visible = False
            swApp.UserControl = False
            
            start_time = time.time()
            procesados = 0
            errores = 0

            for i, (ruta, ext) in enumerate(pending):
                if self._cancelar:
                    self.status.emit("⏹ Extracción cancelada")
                    break

                # Verificar que el archivo existe
                if not os.path.exists(ruta):
                    continue

                doc_type = 1 if ext == '.sldprt' else 2
                props = self._extract_single_file(swApp, ruta, doc_type, pythoncom)

                if props is not None:
                    self._save_props(ruta, props)
                    self.file_extracted.emit(ruta, props)
                    procesados += 1
                else:
                    # Marcar como procesado aunque falle (evitar reintentos infinitos)
                    self._save_props(ruta, {})
                    errores += 1

                if (i + 1) % 10 == 0:
                    elapsed = time.time() - start_time
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    remaining = (total - i - 1) / rate if rate > 0 else 0
                    self.progress.emit(i + 1, total)
                    self.status.emit(
                        f"🔧 Propiedades SW: {i+1}/{total} "
                        f"({remaining/60:.0f} min restantes)"
                    )

                # Commit cada batch_size archivos
                if (i + 1) % self.batch_size == 0:
                    logger.info(f"SWExtractor: Batch {i+1}/{total} completado")

            duration = time.time() - start_time
            logger.info(f"SWExtractor: {procesados} procesados, {errores} errores, {duration:.1f}s")
            self.finished.emit(procesados, duration)

        except Exception as e:
            logger.exception("SWExtractor: Error crítico")
            self.error.emit(str(e))

    def _get_pending_files(self):
        """Obtiene archivos .sldprt/.sldasm que aún no tienen propiedades extraídas."""
        try:
            with self.db.get_connection() as conn:
                # Archivos SW cuya columna 'sw_props_extracted' es NULL o 0
                cursor = conn.execute('''
                    SELECT ruta_completa, extension FROM archivos 
                    WHERE extension IN ('.sldprt', '.sldasm')
                    AND (sw_props_extracted IS NULL OR sw_props_extracted = 0)
                    ORDER BY ultima_modificacion DESC
                ''')
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"SWExtractor: Error obteniendo pendientes: {e}")
            return []

    def _extract_single_file(self, swApp, ruta, doc_type, pythoncom):
        """Extrae propiedades de un solo archivo vía COM API."""
        try:
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            
            # Abrir en modo solo-lectura + silencioso (3 = 1+2)
            model = swApp.OpenDoc6(ruta, doc_type, 3, "", errors, warnings)
            
            if model is None:
                return None

            props = {}
            try:
                ext_obj = model.Extension
                cpm = ext_obj.CustomPropertyManager("")
                
                names = cpm.GetNames
                if names is None:
                    try:
                        names = cpm.GetNames()
                    except:
                        names = None

                if names and isinstance(names, (list, tuple)):
                    for name in names:
                        try:
                            result = cpm.Get6(name, False, "", "", False)
                            if isinstance(result, (list, tuple)) and len(result) > 1:
                                props[name.upper()] = str(result[1]) if result[1] else ""
                            else:
                                props[name.upper()] = str(result) if result else ""
                        except:
                            try:
                                val = cpm.Get(name)
                                props[name.upper()] = str(val) if val else ""
                            except:
                                pass
            finally:
                try:
                    title = model.GetTitle if isinstance(model.GetTitle, str) else model.GetTitle()
                    swApp.CloseDoc(title)
                except:
                    pass

            return props

        except Exception as e:
            logger.debug(f"SWExtractor: Error en {ruta}: {e}")
            return None

    def _save_props(self, ruta, props):
        """Guarda las propiedades extraídas en la base de datos."""
        try:
            # Mapeo de nombres de propiedad SW a columnas de DB
            col_map = {
                'SOLDADURA': 'soldadura', 'PINTURA': 'pintura', 'MONTAJE': 'montaje',
                'L\u00c1SER': 'laser', 'LASER': 'laser',
                'TORNO': 'torno', 'FRESA': 'fresa',
                'TRATAMIENTO': 'tratamiento', 'MATERIAL': 'material'
            }
            
            db_vals = {'soldadura': '', 'pintura': '', 'montaje': '', 'laser': '',
                       'torno': '', 'fresa': '', 'tratamiento': '', 'material': ''}
            
            for prop_name, val in props.items():
                col = col_map.get(prop_name.upper())
                if col:
                    # Normalizar "Sí" / "SI" a "Sí"
                    val_upper = val.strip().upper()
                    if val_upper in ('S\u00cd', 'SI', 'S\u00ed'.upper()):
                        db_vals[col] = 'S\u00ed'
                    elif col in ('tratamiento', 'material'):
                        # Limpiar referencias SW como "SW-Material@..."
                        clean = val.strip()
                        if clean.startswith('"') and clean.endswith('"'):
                            clean = clean[1:-1]
                        if not clean.startswith('SW-') and clean:
                            db_vals[col] = clean
                    elif val.strip():
                        db_vals[col] = val.strip()
            
            with self.db.get_connection() as conn:
                conn.execute('''
                    UPDATE archivos SET 
                        soldadura=?, pintura=?, montaje=?, laser=?,
                        torno=?, fresa=?, tratamiento=?, material=?,
                        sw_props_extracted=1
                    WHERE ruta_completa=?
                ''', (
                    db_vals['soldadura'], db_vals['pintura'], db_vals['montaje'],
                    db_vals['laser'], db_vals['torno'], db_vals['fresa'],
                    db_vals['tratamiento'], db_vals['material'], ruta
                ))
        except Exception as e:
            logger.error(f"SWExtractor: Error guardando props de {ruta}: {e}")


def extraer_propiedades_ondemand(db, ruta):
    """
    Extrae propiedades de UN SOLO archivo SolidWorks bajo demanda.
    Se usa cuando el usuario selecciona un archivo que aún no tiene propiedades.
    Retorna dict con las propiedades o None si falla.
    """
    import pythoncom
    import win32com.client
    
    ext = Path(ruta).suffix.lower()
    if ext not in ('.sldprt', '.sldasm'):
        return None
    if not os.path.exists(ruta):
        return None

    pythoncom.CoInitialize()
    try:
        swApp = win32com.client.Dispatch("SldWorks.Application")
        doc_type = 1 if ext == '.sldprt' else 2
        
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        model = swApp.OpenDoc6(ruta, doc_type, 3, "", errors, warnings)
        
        if not model:
            return None

        props = {}
        try:
            cpm = model.Extension.CustomPropertyManager("")
            names = cpm.GetNames
            if names is None:
                try: names = cpm.GetNames()
                except: names = None
            
            if names and isinstance(names, (list, tuple)):
                for name in names:
                    try:
                        result = cpm.Get6(name, False, "", "", False)
                        if isinstance(result, (list, tuple)) and len(result) > 1:
                            props[name.upper()] = str(result[1]) if result[1] else ""
                        else:
                            props[name.upper()] = str(result) if result else ""
                    except:
                        pass
        finally:
            try:
                title = model.GetTitle if isinstance(model.GetTitle, str) else model.GetTitle()
                swApp.CloseDoc(title)
            except:
                pass

        # Guardar en DB
        col_map = {
            'SOLDADURA': 'soldadura', 'PINTURA': 'pintura', 'MONTAJE': 'montaje',
            'L\u00c1SER': 'laser', 'LASER': 'laser',
            'TORNO': 'torno', 'FRESA': 'fresa',
            'TRATAMIENTO': 'tratamiento', 'MATERIAL': 'material'
        }
        db_vals = {'soldadura': '', 'pintura': '', 'montaje': '', 'laser': '',
                   'torno': '', 'fresa': '', 'tratamiento': '', 'material': ''}
        
        for prop_name, val in props.items():
            col = col_map.get(prop_name.upper())
            if col:
                val_upper = val.strip().upper()
                if val_upper in ('S\u00cd', 'SI', 'S\u00ed'.upper()):
                    db_vals[col] = 'S\u00ed'
                elif col in ('tratamiento', 'material'):
                    clean = val.strip().strip('"')
                    if not clean.startswith('SW-') and clean:
                        db_vals[col] = clean
                elif val.strip():
                    db_vals[col] = val.strip()
        
        with db.get_connection() as conn:
            conn.execute('''
                UPDATE archivos SET 
                    soldadura=?, pintura=?, montaje=?, laser=?,
                    torno=?, fresa=?, tratamiento=?, material=?,
                    sw_props_extracted=1
                WHERE ruta_completa=?
            ''', (
                db_vals['soldadura'], db_vals['pintura'], db_vals['montaje'],
                db_vals['laser'], db_vals['torno'], db_vals['fresa'],
                db_vals['tratamiento'], db_vals['material'], ruta
            ))
        
        return db_vals

    except Exception as e:
        logger.debug(f"Extracción on-demand fallida para {ruta}: {e}")
        return None
    finally:
        pythoncom.CoUninitialize()

from pathlib import Path

class SearchController:
    """Orquestador entre la Vista y el Modelo"""
    def __init__(self, db):
        self.db = db

    def perform_search(self, term, companions, years, extensiones=None, folder_type="TODOS", 
                      clientes=None, proyectos=None, ordenes=None, incluir_siddex=False, incluir_estandar=False, incluir_darkweb_ja=False, procesos_filtro=None):
        return self.db.buscar(term, companions, years, extensiones, folder_type, clientes, proyectos, ordenes, incluir_siddex, incluir_estandar, incluir_darkweb_ja, procesos_filtro=procesos_filtro)

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
