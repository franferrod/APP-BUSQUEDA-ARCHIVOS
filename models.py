import os
import logging
import unicodedata
import psycopg2
import psycopg2.pool
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
LOG_PATH = CONFIG_DIR / "app.log"

import sys
import configparser

def load_pg_config():
    config = configparser.ConfigParser()
    config_path = "config.ini"
    
    # Soporte para ejecutable PyInstaller
    if getattr(sys, 'frozen', False):
        config_path = os.path.join(os.path.dirname(sys.executable), "config.ini")
        if not os.path.exists(config_path):
            config_path = "config.ini" # Fallback
            
    if not os.path.exists(config_path):
        msg = f"Falta archivo de configuración: config.ini\nBuscado en: {config_path}\nPor favor, reinstala usando INSTALAR_LOCAL.bat"
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "Error fatal", 0x10)
        except:
            pass
        sys.exit(1)
        
    config.read(config_path)
    return {
        'host': config['database']['host'],
        'port': int(config['database']['port']),
        'dbname': config['database']['dbname'],
        'user': config['database']['user'],
        'password': config['database']['password'],
    }

# V1.0.8 - PostgreSQL compartido (credenciales en config.ini)
PG_CONFIG = load_pg_config()

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
    Gestor de la base de datos PostgreSQL para el buscador de piezas.
    V1.0.7 - Migrado de SQLite a PostgreSQL compartido.
    """
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._pool = None
        self._init_pool()
        self.init_db()

    def _init_pool(self):
        """Inicializa el pool de conexiones PostgreSQL."""
        try:
            self._pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=5,
                **PG_CONFIG
            )
            logger.info("Pool de conexiones PostgreSQL inicializado correctamente")
        except psycopg2.Error as e:
            logger.error(f"Error inicializando pool PostgreSQL: {e}")
            raise

    def get_connection(self):
        """Obtiene una conexión del pool. Devuelve un PGConnectionWrapper."""
        if self._pool is None or self._pool.closed:
            self._init_pool()
        conn = self._pool.getconn()
        return PGConnectionWrapper(conn, self._pool)

    @staticmethod
    def normalizar_texto(texto):
        """Convierte a mayúsculas y quita acentos/tildes"""
        if texto is None:
            return ""
        texto = unicodedata.normalize('NFKD', str(texto))
        texto = "".join([c for c in texto if not unicodedata.combining(c)])
        return texto.upper()

    def init_db(self):
        """Crea schema, tablas e índices si no existen."""
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            conn.autocommit = True
            cursor = conn.cursor()

            cursor.execute('CREATE SCHEMA IF NOT EXISTS buscador')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS buscador.archivos (
                    id              SERIAL PRIMARY KEY,
                    nombre_archivo  TEXT NOT NULL,
                    origen          TEXT,
                    anio            INTEGER,
                    cliente         TEXT,
                    proyecto        TEXT,
                    tipo_carpeta    TEXT,
                    ruta_completa   TEXT UNIQUE NOT NULL,
                    extension       TEXT,
                    ultima_modificacion BIGINT,
                    tamano_bytes    BIGINT,
                    codigo_proyecto TEXT,
                    nombre_proyecto TEXT,
                    codigo_orden    TEXT,
                    nombre_orden    TEXT,
                    sw_material     TEXT,
                    sw_tratamiento  TEXT,
                    sw_espesor      TEXT,
                    sw_laser        TEXT,
                    sw_torno        TEXT,
                    sw_fresa        TEXT,
                    sw_soldadura    TEXT,
                    sw_pintura      TEXT,
                    sw_montaje      TEXT,
                    sw_tipo_cierre  TEXT,
                    sw_filo_guiado  TEXT,
                    sw_onda         TEXT,
                    sw_cangilon     TEXT,
                    sw_runer        TEXT,
                    indexado_en     TIMESTAMP DEFAULT NOW()
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS buscador.estado_indexacion (
                    origen              TEXT PRIMARY KEY,
                    ruta_base           TEXT,
                    ultima_indexacion    BIGINT,
                    archivos_indexados   INTEGER
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS buscador.preferencias (
                    clave TEXT PRIMARY KEY,
                    valor TEXT
                )
            ''')

            # V2.1.0 - Placas CE: relación nº de placa <-> código de plano/ensamblaje
            # alimentada desde los Excel de \\NAS\Oficina Tecnica\NÚMEROS DE SERIE
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS buscador.placas_ce (
                    num_placa      TEXT PRIMARY KEY,
                    codigo_tipo    TEXT,
                    descripcion    TEXT,
                    cliente        TEXT,
                    anio           INTEGER,
                    proyecto       TEXT,
                    orden          TEXT,
                    num_plano      TEXT,
                    archivo_origen TEXT,
                    indexado_en    TIMESTAMP DEFAULT NOW()
                )
            ''')

            # Índices
            indices = [
                'CREATE INDEX IF NOT EXISTS idx_ba_nombre ON buscador.archivos(nombre_archivo)',
                'CREATE INDEX IF NOT EXISTS idx_ba_origen ON buscador.archivos(origen)',
                'CREATE INDEX IF NOT EXISTS idx_ba_anio ON buscador.archivos(anio)',
                'CREATE INDEX IF NOT EXISTS idx_ba_cliente ON buscador.archivos(cliente)',
                'CREATE INDEX IF NOT EXISTS idx_ba_tipo ON buscador.archivos(tipo_carpeta)',
                'CREATE INDEX IF NOT EXISTS idx_ba_extension ON buscador.archivos(extension)',
                'CREATE INDEX IF NOT EXISTS idx_ba_cod_proy ON buscador.archivos(codigo_proyecto)',
                'CREATE INDEX IF NOT EXISTS idx_ba_cod_ord ON buscador.archivos(codigo_orden)',
                'CREATE INDEX IF NOT EXISTS idx_ba_origen_anio ON buscador.archivos(origen, anio)',
                'CREATE INDEX IF NOT EXISTS idx_placas_plano ON buscador.placas_ce(num_plano)',
            ]
            for idx_sql in indices:
                cursor.execute(idx_sql)

            # Extensión unaccent para búsquedas sin acentos
            try:
                cursor.execute('CREATE EXTENSION IF NOT EXISTS unaccent')
            except Exception:
                logger.warning("Extensión unaccent no disponible, se usará normalización Python")

            # Limpieza de temporales huérfanos
            cursor.execute("DELETE FROM buscador.archivos WHERE nombre_archivo LIKE '~$%%'")

            conn.autocommit = False
            logger.info("Base de datos PostgreSQL inicializada correctamente")
        except Exception as e:
            logger.error(f"Error inicializando BD PostgreSQL: {e}")
            raise
        finally:
            wrapper.close()

    def guardar_preferencia(self, clave, valor):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO buscador.preferencias (clave, valor) VALUES (%s, %s)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
            ''', (clave, str(valor)))
            conn.commit()
        finally:
            wrapper.close()

    def obtener_preferencia(self, clave, default=None):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            cursor.execute('SELECT valor FROM buscador.preferencias WHERE clave = %s', (clave,))
            res = cursor.fetchone()
            return res[0] if res else default
        finally:
            wrapper.close()

    # ═══════════════════════════════════════════════════════════════════
    # PLACAS CE (V2.1.0)
    # ═══════════════════════════════════════════════════════════════════
    def guardar_placas_ce(self, filas):
        """Reemplaza el contenido de buscador.placas_ce con las filas escaneadas
        de los Excel de NÚMEROS DE SERIE. filas = lista de tuplas:
        (num_placa, codigo_tipo, descripcion, cliente, anio, proyecto, orden, num_plano, archivo_origen)"""
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
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
            logger.info(f"Placas CE indexadas: {len(filas)}")
            return len(filas)
        finally:
            wrapper.close()

    def contar_placas_ce(self):
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM buscador.placas_ce")
            return cursor.fetchone()[0]
        except Exception:
            return 0
        finally:
            wrapper.close()

    def buscar_planos_por_placa(self, termino):
        """Si el término coincide con un nº de placa CE (ej. '26-0006'),
        devuelve los num_plano asociados para expandir la búsqueda."""
        kw = (termino or "").strip().upper()
        if not kw or len(kw) < 3:
            return []
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute(
                "SELECT DISTINCT num_plano FROM buscador.placas_ce "
                "WHERE UPPER(num_placa) = %s AND num_plano IS NOT NULL AND num_plano != ''",
                (kw,))
            return [r[0] for r in cursor.fetchall()]
        except Exception as e:
            logger.debug(f"Error buscando placa '{kw}': {e}")
            return []
        finally:
            wrapper.close()

    def buscar(self, termino, compañeros=None, años=None, extensiones=None, carpetas=None, clientes=None, proyectos=None, ordenes=None, props_fabricacion=None, props_bandas=None, material=None, tratamiento=None, espesor=None, solo_placa_ce=False):
        """
        Búsqueda multi-keyword con scoring y filtros múltiples.
        V1.0.7 - Adaptado a PostgreSQL con unaccent.
        V2.1.0 - solo_placa_ce: restringe a archivos cuyo código de plano tiene
                 placa CE registrada; y si un keyword es un nº de placa, expande
                 la búsqueda a su ensamblaje.
        """
        logger.info(f"Buscando: '{termino}' | Orígenes: {compañeros}, Años: {años}")

        is_and_search = False
        if ';' in termino:
            keywords = [k.strip() for k in termino.split(';') if k.strip()]
            is_and_search = True
        elif ',' in termino:
            keywords = [k.strip() for k in termino.split(',') if k.strip()]
        else:
            keywords = [termino] if termino.strip() else []

        params = []
        base_cols = """nombre_archivo, origen, anio, cliente, proyecto, tipo_carpeta,
                       codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden,
                       ruta_completa, sw_material, sw_tratamiento, sw_espesor,
                       sw_laser, sw_torno, sw_fresa, sw_soldadura, sw_pintura, sw_montaje"""

        # V2.1.0: expansión por nº de placa CE — si algún keyword es una placa
        # registrada (ej. "26-0006"), buscamos también por su código de plano
        planos_de_placas = []
        for kw in keywords:
            planos_de_placas.extend(self.buscar_planos_por_placa(kw))

        # 1. Construcción de Scores y WHERE base (Keywords)
        if not keywords:
            query_select = f"SELECT {base_cols}, 0 as score FROM buscador.archivos"
            base_where = "1=1"
        else:
            score_cases = []
            for i, kw in enumerate(keywords):
                peso_posicion = len(keywords) - i
                kw_norm = self.normalizar_texto(kw)
                score_cases.append(
                    f"CASE WHEN UPPER(unaccent(nombre_archivo)) LIKE %s THEN {peso_posicion * 100} ELSE 0 END"
                )
                params.append(f"%{kw_norm}%")

            # Los planos que vienen de un nº de placa puntúan por encima de todo
            for plano in planos_de_placas:
                score_cases.append("CASE WHEN UPPER(nombre_archivo) LIKE %s THEN 10000 ELSE 0 END")
                params.append(f"{plano.upper()}%")

            score_sql = " + ".join(score_cases)
            logic_op = " AND " if is_and_search else " OR "
            where_clause = logic_op.join(
                ["UPPER(unaccent(nombre_archivo)) LIKE %s" for _ in keywords]
            )
            params.extend([f"%{self.normalizar_texto(k)}%" for k in keywords])

            # La coincidencia por placa siempre entra en OR (aunque la búsqueda sea AND)
            if planos_de_placas:
                placa_clause = " OR ".join(["UPPER(nombre_archivo) LIKE %s" for _ in planos_de_placas])
                where_clause = f"({where_clause}) OR ({placa_clause})"
                params.extend([f"{p.upper()}%" for p in planos_de_placas])

            query_select = f"SELECT {base_cols}, ({score_sql}) as score FROM buscador.archivos"
            base_where = f"({where_clause})"

        # V2.1.0 - Filtro "Solo máquinas con placa CE": el prefijo del nombre de
        # archivo (ej. "26047.E107") debe existir como num_plano en placas_ce
        if solo_placa_ce:
            base_where += (
                " AND UPPER(SUBSTRING(nombre_archivo FROM '^[0-9]{4,6}\\.E[0-9]+'))"
                " IN (SELECT UPPER(num_plano) FROM buscador.placas_ce"
                "     WHERE num_plano IS NOT NULL AND num_plano != '')"
            )

        # Filtro Global contra Temporales
        base_where += " AND SUBSTRING(nombre_archivo, 1, 1) != '~'"

        # 2. Filtros de Contexto
        context_clauses = []
        context_params = []

        # Recopilar filtros jerárquicos
        jerarquicos_clauses = []
        jerarquicos_params = []

        if años and len(años) > 0:
            placeholders = ','.join(['%s' for _ in años])
            jerarquicos_clauses.append(f"anio IN ({placeholders})")
            jerarquicos_params.extend([int(a) for a in años])

        if carpetas and len(carpetas) > 0 and "TODOS" not in carpetas:
            placeholders = ','.join(['%s' for _ in carpetas])
            jerarquicos_clauses.append(f"tipo_carpeta IN ({placeholders})")
            jerarquicos_params.extend(carpetas)

        if clientes and len(clientes) > 0:
            placeholders = ','.join(['%s' for _ in clientes])
            jerarquicos_clauses.append(f"cliente IN ({placeholders})")
            jerarquicos_params.extend(clientes)

        if proyectos and len(proyectos) > 0:
            placeholders = ','.join(['%s' for _ in proyectos])
            jerarquicos_clauses.append(f"codigo_proyecto IN ({placeholders})")
            jerarquicos_params.extend(proyectos)
            
        if ordenes:
            placeholders = ','.join(['%s'] * len(ordenes))
            jerarquicos_clauses.append(f"nombre_orden IN ({placeholders})")
            jerarquicos_params.extend(ordenes)

        # Filtro Orígenes combinado con filtros jerárquicos
        if compañeros and len(compañeros) > 0:
            origen_conditions = []
            
            # Orígenes normales (PROYECTOS) que SÍ se ven afectados por filtros jerárquicos
            normales = [c for c in compañeros if c not in ("BIBLIOTECA_3D", "ALSI_ESTANDAR")]
            if normales:
                placeholders = ','.join(['%s' for _ in normales])
                cond = f"origen IN ({placeholders})"
                if jerarquicos_clauses:
                    j_sql = " AND ".join(jerarquicos_clauses)
                    cond = f"({cond} AND {j_sql})"
                    origen_conditions.append(cond)
                    context_params.extend(normales + jerarquicos_params)
                else:
                    origen_conditions.append(cond)
                    context_params.extend(normales)
            
            # Bibliotecas (ignoran filtros jerárquicos, solo obedecen término y propiedades)
            bibliotecas = [c for c in compañeros if c in ("BIBLIOTECA_3D", "ALSI_ESTANDAR")]
            if bibliotecas:
                placeholders = ','.join(['%s' for _ in bibliotecas])
                origen_conditions.append(f"origen IN ({placeholders})")
                context_params.extend(bibliotecas)
                
            if origen_conditions:
                origen_sql = " OR ".join(origen_conditions)
                context_clauses.append(f"({origen_sql})")
            else:
                context_clauses.append("1=0")

        # Filtro Extensiones (Aplica a todos)
        if extensiones and len(extensiones) > 0:
            placeholders = ','.join(['%s' for _ in extensiones])
            base_where += f" AND extension IN ({placeholders})"
            params.extend(extensiones)
            
        # Filtros de Material, Tratamiento y Espesor (listas multi-selección)
        if material and len(material) > 0:
            placeholders = ','.join(['%s' for _ in material])
            context_clauses.append(f"sw_material IN ({placeholders})")
            context_params.extend(material)
        
        if tratamiento and len(tratamiento) > 0:
            placeholders = ','.join(['%s' for _ in tratamiento])
            context_clauses.append(f"sw_tratamiento IN ({placeholders})")
            context_params.extend(tratamiento)
        
        if espesor and len(espesor) > 0:
            # Espesor UI values are "1mm", "2mm"... extract the number
            espesor_conditions = []
            for esp in espesor:
                num = esp.replace("mm", "")
                # Match exact number at start of field (e.g. "3" matches "3", "3.0", "3.00")
                espesor_conditions.append("(sw_espesor = %s OR sw_espesor LIKE %s)")
                context_params.extend([num, num + ".%"])
            context_clauses.append(f"({' OR '.join(espesor_conditions)})")

        # Filtros de Fabricación (Booleanos)
        if props_fabricacion:
            for key, col in [('laser', 'sw_laser'), ('torno', 'sw_torno'), ('fresa', 'sw_fresa'),
                             ('soldadura', 'sw_soldadura'), ('pintura', 'sw_pintura'), ('montaje', 'sw_montaje')]:
                if props_fabricacion.get(key):
                    context_clauses.append(f"({col} ILIKE %s OR {col} ILIKE %s)")
                    context_params.extend(['%SÍ%', '%SI%'])

        # Filtros de Bandas
        if props_bandas:
            cierres = props_bandas.get('cierres')
            if cierres and len(cierres) > 0:
                cierre_conditions = []
                for c in cierres:
                    cierre_conditions.append("sw_tipo_cierre ILIKE %s")
                    context_params.append(f"%{c}%")
                context_clauses.append(f"({' OR '.join(cierre_conditions)})")
                
            for key, col in [('filo_guiado', 'sw_filo_guiado'), ('onda', 'sw_onda'), 
                             ('cangilon', 'sw_cangilon'), ('runer', 'sw_runer')]:
                if props_bandas.get(key):
                    context_clauses.append(f"({col} ILIKE %s OR {col} ILIKE %s)")
                    context_params.extend(['%SÍ%', '%SI%'])

        # 3. Construcción final
        query = f"{query_select} WHERE {base_where}"

        if context_clauses:
            context_sql = " AND ".join(context_clauses)
            query += f" AND ({context_sql})"
            params.extend(context_params)

        query += " ORDER BY score DESC, ultima_modificacion DESC NULLS LAST LIMIT 5000"

        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()
            # Devolver sin la columna score (última)
            return [r[:-1] for r in results]
        except Exception as e:
            logger.error(f"Error en consulta: {e}")
            raise
        finally:
            wrapper.close()

    def obtener_clientes(self, compañeros=None, años=None):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            params = []
            query = "SELECT DISTINCT cliente FROM buscador.archivos WHERE cliente != 'DESCONOCIDO' "

            if compañeros and len(compañeros) > 0:
                placeholders = ','.join(['%s' for _ in compañeros])
                query += f" AND origen IN ({placeholders})"
                params.extend(compañeros)

            if años and len(años) > 0:
                placeholders = ','.join(['%s' for _ in años])
                query += f" AND anio IN ({placeholders})"
                params.extend([int(a) for a in años])

            query += " ORDER BY cliente"
            cursor.execute(query, params)
            return [r[0] for r in cursor.fetchall()]
        finally:
            wrapper.close()

    def obtener_proyectos(self, clientes=None, compañeros=None, años=None):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            params = []
            query = "SELECT DISTINCT codigo_proyecto, nombre_proyecto FROM buscador.archivos WHERE codigo_proyecto != '' "

            if clientes and len(clientes) > 0:
                placeholders = ','.join(['%s' for _ in clientes])
                query += f" AND cliente IN ({placeholders})"
                params.extend(clientes)

            if compañeros and len(compañeros) > 0:
                placeholders = ','.join(['%s' for _ in compañeros])
                query += f" AND origen IN ({placeholders})"
                params.extend(compañeros)

            if años and len(años) > 0:
                placeholders = ','.join(['%s' for _ in años])
                query += f" AND anio IN ({placeholders})"
                params.extend([int(a) for a in años])

            query += " ORDER BY codigo_proyecto DESC"
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            wrapper.close()

    def obtener_materiales(self):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT sw_material FROM buscador.archivos WHERE sw_material IS NOT NULL AND sw_material != '' ORDER BY sw_material ASC")
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error obteniendo materiales: {e}")
            return []
        finally:
            wrapper.close()

    def obtener_tratamientos(self):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT sw_tratamiento FROM buscador.archivos WHERE sw_tratamiento IS NOT NULL AND sw_tratamiento != '' ORDER BY sw_tratamiento ASC")
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error obteniendo tratamientos: {e}")
            return []
        finally:
            wrapper.close()

    def obtener_espesores(self):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT sw_espesor FROM buscador.archivos WHERE sw_espesor IS NOT NULL AND sw_espesor != '' ORDER BY sw_espesor ASC")
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error obteniendo espesores: {e}")
            return []
        finally:
            wrapper.close()

    def obtener_ordenes(self, clientes=None, proyectos=None, compañeros=None, años=None):
        wrapper = self.get_connection()
        try:
            conn = wrapper._conn
            cursor = conn.cursor()
            params = []
            query = "SELECT DISTINCT codigo_orden, nombre_orden FROM buscador.archivos WHERE codigo_orden != '' "

            if clientes and len(clientes) > 0:
                placeholders = ','.join(['%s' for _ in clientes])
                query += f" AND cliente IN ({placeholders})"
                params.extend(clientes)

            if proyectos and len(proyectos) > 0:
                placeholders = ','.join(['%s' for _ in proyectos])
                query += f" AND codigo_proyecto IN ({placeholders})"
                params.extend(proyectos)

            if compañeros and len(compañeros) > 0:
                placeholders = ','.join(['%s' for _ in compañeros])
                query += f" AND origen IN ({placeholders})"
                params.extend(compañeros)

            if años and len(años) > 0:
                placeholders = ','.join(['%s' for _ in años])
                query += f" AND anio IN ({placeholders})"
                params.extend([int(a) for a in años])

            query += " ORDER BY codigo_orden DESC"
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            wrapper.close()


class PGConnectionWrapper:
    """
    Wrapper para conexiones PostgreSQL que imita el context manager de SQLite.
    Al cerrar, devuelve la conexión al pool en lugar de cerrarla.
    """
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def execute(self, query, params=None):
        """Ejecuta una query directamente (compatibilidad con código antiguo)."""
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return cursor

    def commit(self):
        self._conn.commit()

    def close(self):
        if self._conn and self._pool:
            try:
                self._pool.putconn(self._conn)
            except Exception:
                pass
