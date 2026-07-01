import os
import logging
import unicodedata
import psycopg2
import psycopg2.pool
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
LOG_PATH = CONFIG_DIR / "app.log"

# V1.0.7 - PostgreSQL compartido (sustituye SQLite local y NAS)
PG_CONFIG = {
    'host': '192.168.1.10',
    'port': 5433,
    'dbname': 'ALSI',
    'user': 'ALSI',
    'password': 'alsi_super_password_2026',
}

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

    def buscar(self, termino, compañeros=None, años=None, extensiones=None, carpetas=None, clientes=None, proyectos=None, ordenes=None, props_fabricacion=None, props_bandas=None):
        """
        Búsqueda multi-keyword con scoring y filtros múltiples.
        V1.0.7 - Adaptado a PostgreSQL con unaccent.
        """
        logger.info(f"Buscando: '{termino}' | Orígenes: {compañeros}, Años: {años}")

        if ',' in termino:
            keywords = [k.strip() for k in termino.split(',') if k.strip()]
        else:
            keywords = [termino] if termino.strip() else []

        params = []
        base_cols = """nombre_archivo, origen, anio, cliente, proyecto, tipo_carpeta,
                       codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden,
                       ruta_completa, sw_material, sw_tratamiento, sw_espesor,
                       sw_laser, sw_torno, sw_fresa, sw_soldadura, sw_pintura, sw_montaje"""

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

            score_sql = " + ".join(score_cases)
            where_clause = " OR ".join(
                ["UPPER(unaccent(nombre_archivo)) LIKE %s" for _ in keywords]
            )
            params.extend([f"%{self.normalizar_texto(k)}%" for k in keywords])

            query_select = f"SELECT {base_cols}, ({score_sql}) as score FROM buscador.archivos"
            base_where = f"({where_clause})"

        # Filtro Global contra Temporales
        base_where += " AND SUBSTRING(nombre_archivo, 1, 1) != '~'"

        # 2. Filtros de Contexto
        context_clauses = []
        context_params = []

        # Filtro Orígenes (antes "compañeros")
        if compañeros and len(compañeros) > 0:
            placeholders = ','.join(['%s' for _ in compañeros])
            context_clauses.append(f"origen IN ({placeholders})")
            context_params.extend(compañeros)

        # Filtro Años
        if años and len(años) > 0:
            placeholders = ','.join(['%s' for _ in años])
            context_clauses.append(f"anio IN ({placeholders})")
            context_params.extend([int(a) for a in años])

        # Filtro Extensiones
        if extensiones and len(extensiones) > 0:
            placeholders = ','.join(['%s' for _ in extensiones])
            base_where += f" AND extension IN ({placeholders})"
            params.extend(extensiones)

        # Filtro Carpeta
        if carpetas and len(carpetas) > 0 and "TODOS" not in carpetas:
            placeholders = ','.join(['%s' for _ in carpetas])
            context_clauses.append(f"tipo_carpeta IN ({placeholders})")
            context_params.extend(carpetas)

        # Filtros Jerárquicos
        if clientes and len(clientes) > 0:
            placeholders = ','.join(['%s' for _ in clientes])
            context_clauses.append(f"cliente IN ({placeholders})")
            context_params.extend(clientes)

        if proyectos and len(proyectos) > 0:
            placeholders = ','.join(['%s' for _ in proyectos])
            context_clauses.append(f"codigo_proyecto IN ({placeholders})")
            context_params.extend(proyectos)

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
