import sqlite3
import os
import logging
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
DB_PATH = CONFIG_DIR / "index.db"
LOG_PATH = CONFIG_DIR / "app.log"

# Configuración de Logging
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

class IndexManager:
    """
    Gestor de la base de datos SQLite para el buscador de piezas.
    Independiente de la interfaz gráfica.
    """
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(str(DB_PATH))

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Tabla de archivos
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archivos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_archivo TEXT NOT NULL,
                    compañero TEXT,
                    año INTEGER,
                    cliente TEXT,
                    proyecto TEXT,
                    tipo_carpeta TEXT,
                    ruta_completa TEXT UNIQUE NOT NULL,
                    extension TEXT,
                    ultima_modificacion INTEGER,
                    tamaño_bytes INTEGER,
                    codigo_proyecto TEXT,
                    nombre_proyecto TEXT,
                    codigo_orden TEXT,
                    nombre_orden TEXT
                )
            ''')
            
            # Migración: Añadir columnas si no existen (V1.2.1+)
            cols_to_add = [
                ("extension", "TEXT"),
                ("ultima_modificacion", "INTEGER"),
                ("tamaño_bytes", "INTEGER"),
                # V1.3.0 - Estructura Jerárquica
                ("codigo_proyecto", "TEXT"),
                ("nombre_proyecto", "TEXT"),
                ("codigo_orden", "TEXT"),
                ("nombre_orden", "TEXT")
            ]
            for col_name, col_type in cols_to_add:
                try:
                    cursor.execute(f"ALTER TABLE archivos ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    # La columna ya existe
                    pass

            # Tabla de preferencias
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS preferencias (
                    clave TEXT PRIMARY KEY,
                    valor TEXT
                )
            ''')
            # Tabla de estado de indexación
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS estado_indexacion (
                    compañero TEXT PRIMARY KEY,
                    ruta_base TEXT,
                    ultima_indexacion INTEGER,
                    archivos_indexados INTEGER
                )
            ''')
            # Índices simples
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_nombre ON archivos(nombre_archivo)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_compañero ON archivos(compañero)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_año ON archivos(año)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tipo ON archivos(tipo_carpeta)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_extension ON archivos(extension)')
            # Índices compuestos (@performance-optimization, @database-optimization)
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_comp_año ON archivos(compañero, año)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_nombre_comp ON archivos(nombre_archivo, compañero)')
            # V1.3.4.2 - Índices de Jerarquía (@performance-optimization)
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cliente ON archivos(cliente)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cod_proy ON archivos(codigo_proyecto)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cod_ord ON archivos(codigo_orden)')
            
            # Limpieza de temporales huérfanos (V1.2.6)
            cursor.execute("DELETE FROM archivos WHERE nombre_archivo LIKE '~$%'")
            conn.commit()

    def guardar_preferencia(self, clave, valor):
        with self.get_connection() as conn:
            conn.execute('INSERT OR REPLACE INTO preferencias (clave, valor) VALUES (?, ?)', (clave, str(valor)))
            conn.commit()

    def obtener_preferencia(self, clave, default=None):
        with self.get_connection() as conn:
            res = conn.execute('SELECT valor FROM preferencias WHERE clave = ?', (clave,)).fetchone()
            return res[0] if res else default

    def buscar(self, termino, compañeros=None, años=None, extensiones=None, carpetas=None, clientes=None, proyectos=None, ordenes=None, incluir_siddex=False, incluir_estandar=False):
        """
        Búsqueda multi-keyword con scoring y filtros múltiples (V1.3.0).
        V1.3.6 - Soporte para búsqueda híbrida (Contexto OR Biblioteca).
        """
        logger.info(f"Buscando: '{termino}' | Siddex: {incluir_siddex}, Estandar: {incluir_estandar}")
        
        if ',' in termino:
            keywords = [k.strip() for k in termino.split(',') if k.strip()]
        else:
            keywords = [termino] if termino.strip() else []

        params = []
        base_cols = "nombre_archivo, compañero, año, cliente, proyecto, tipo_carpeta, codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden, ruta_completa"

        # 1. Construcción de Scores y WHERE base (Keywords)
        if not keywords:
            query_select = f"SELECT {base_cols}, 0 as score FROM archivos"
            base_where = "1=1"
        else:
            score_cases = []
            for i, kw in enumerate(keywords):
                peso_posicion = len(keywords) - i
                score_cases.append(f"CASE WHEN nombre_archivo LIKE ? THEN {peso_posicion * 100} ELSE 0 END")
                params.append(f"%{kw}%")

            score_sql = " + ".join(score_cases)
            where_clause = " OR ".join(["nombre_archivo LIKE ?" for _ in keywords])
            params.extend([f"%{k}%" for k in keywords])
            
            query_select = f"SELECT {base_cols}, ({score_sql}) as score FROM archivos"
            base_where = f"({where_clause})"

        # Filtro Global contra Temporales
        base_where += " AND SUBSTR(nombre_archivo, 1, 1) != '~'"

        # 2. Construcción de Filtros de Contexto (Standard)
        context_clauses = []
        context_params = []

        # Filtro Compañeros
        if compañeros and len(compañeros) > 0:
            placeholders = ','.join(['?' for _ in compañeros])
            context_clauses.append(f"compañero IN ({placeholders})")
            context_params.extend(compañeros)

        # Filtro Años
        if años and len(años) > 0:
            placeholders = ','.join(['?' for _ in años])
            context_clauses.append(f"año IN ({placeholders})")
            context_params.extend([int(a) for a in años])

        # Filtro Extensiones (Siempre aplica, incluso a biblioteca)
        if extensiones and len(extensiones) > 0:
            placeholders = ','.join(['?' for _ in extensiones])
            base_where += f" AND extension IN ({placeholders})"
            params.extend(extensiones)

        # Filtro Carpeta (V1.3.14 - Movido a contexto para no bloquear comerciales)
        if carpetas and len(carpetas) > 0 and "TODOS" not in carpetas:
            placeholders = ','.join(['?' for _ in carpetas])
            context_clauses.append(f"tipo_carpeta IN ({placeholders})")
            context_params.extend(carpetas)
            
        # Filtros Jerárquicos (Contexto)
        if clientes and len(clientes) > 0:
            placeholders = ','.join(['?' for _ in clientes])
            context_clauses.append(f"cliente IN ({placeholders})")
            context_params.extend(clientes)

        if proyectos and len(proyectos) > 0:
            placeholders = ','.join(['?' for _ in proyectos])
            context_clauses.append(f"codigo_proyecto IN ({placeholders})")
            context_params.extend(proyectos)

        # 3. Lógica Híbrida (V1.3.15)
        query = f"{query_select} WHERE {base_where}"
        
        lib_comps = []
        if incluir_siddex: lib_comps.append('BIBLIOTECA')
        if incluir_estandar: lib_comps.append('ESTANDAR')

        if lib_comps:
            # Cláusula para Biblioteca/Estándar
            placeholders = ','.join(['?' for _ in lib_comps])
            lib_clause = f"compañero IN ({placeholders})"
            
            if context_clauses:
                # Si hay filtros de contexto: (Contexto Por Compañero) OR (Biblioteca Sin Filtros)
                context_sql = " AND ".join(context_clauses)
                query += f" AND ( ({context_sql}) OR ({lib_clause}) )"
                params.extend(context_params)
                params.extend(lib_comps)
            else:
                # Si NO hay filtros de contexto: Solo buscar en las seleccionadas (Biblioteca y/o Estándar)
                query += f" AND ({lib_clause})"
                params.extend(lib_comps)
        
        elif context_clauses:
             # Lógica Standard: Solo Contexto
             context_sql = " AND ".join(context_clauses)
             query += f" AND ({context_sql})"
             params.extend(context_params)

        query += " ORDER BY score DESC, ultima_modificacion DESC LIMIT 2000"
        
        try:
            with self.get_connection() as conn:
                results = conn.execute(query, params).fetchall()
                return [r[:-1] for r in results]
        except Exception as e:
            logger.error(f"Error en consulta: {e}")
            raise

    def obtener_clientes(self, compañeros=None, años=None):
        with self.get_connection() as conn:
            params = []
            query = "SELECT DISTINCT cliente FROM archivos WHERE cliente != 'DESCONOCIDO' "
            
            if compañeros and len(compañeros) > 0:
                placeholders = ','.join(['?' for _ in compañeros])
                query += f" AND compañero IN ({placeholders})"
                params.extend(compañeros)
            
            if años and len(años) > 0:
                placeholders = ','.join(['?' for _ in años])
                query += f" AND año IN ({placeholders})"
                params.extend([int(a) for a in años])

            query += " ORDER BY cliente"
            return [r[0] for r in conn.execute(query, params).fetchall()]

    def obtener_proyectos(self, clientes=None, compañeros=None, años=None):
        with self.get_connection() as conn:
            params = []
            query = "SELECT DISTINCT codigo_proyecto, nombre_proyecto FROM archivos WHERE codigo_proyecto != '' "
            
            if clientes and len(clientes) > 0:
                placeholders = ','.join(['?' for _ in clientes])
                query += f" AND cliente IN ({placeholders})"
                params.extend(clientes)
            
            if compañeros and len(compañeros) > 0:
                placeholders = ','.join(['?' for _ in compañeros])
                query += f" AND compañero IN ({placeholders})"
                params.extend(compañeros)
                
            if años and len(años) > 0:
                placeholders = ','.join(['?' for _ in años])
                query += f" AND año IN ({placeholders})"
                params.extend([int(a) for a in años])
                
            query += " ORDER BY codigo_proyecto DESC"
            return conn.execute(query, params).fetchall()

    def obtener_ordenes(self, clientes=None, proyectos=None, compañeros=None, años=None):
        with self.get_connection() as conn:
            params = []
            query = "SELECT DISTINCT codigo_orden, nombre_orden FROM archivos WHERE codigo_orden != '' "
            
            if clientes and len(clientes) > 0:
                placeholders = ','.join(['?' for _ in clientes])
                query += f" AND cliente IN ({placeholders})"
                params.extend(clientes)
                
            if proyectos and len(proyectos) > 0:
                placeholders = ','.join(['?' for _ in proyectos])
                query += f" AND codigo_proyecto IN ({placeholders})"
                params.extend(proyectos)
            
            if compañeros and len(compañeros) > 0:
                placeholders = ','.join(['?' for _ in compañeros])
                query += f" AND compañero IN ({placeholders})"
                params.extend(compañeros)
                
            if años and len(años) > 0:
                placeholders = ','.join(['?' for _ in años])
                query += f" AND año IN ({placeholders})"
                params.extend([int(a) for a in años])
                
            query += " ORDER BY codigo_orden DESC"
            return conn.execute(query, params).fetchall()
