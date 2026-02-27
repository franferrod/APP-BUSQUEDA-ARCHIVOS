import os
import re
import datetime
import threading
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

from pathlib import Path

class SearchController:
    """Orquestador entre la Vista y el Modelo"""
    def __init__(self, db):
        self.db = db

    def perform_search(self, term, companions, years, extensiones=None, folder_type="TODOS", 
                      clientes=None, proyectos=None, ordenes=None, incluir_siddex=False, incluir_estandar=False, incluir_darkweb_ja=False):
        return self.db.buscar(term, companions, years, extensiones, folder_type, clientes, proyectos, ordenes, incluir_siddex, incluir_estandar, incluir_darkweb_ja)

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
