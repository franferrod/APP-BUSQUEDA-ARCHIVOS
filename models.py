import os
import time
import logging
import unicodedata
import re
import threading
import psycopg2
import psycopg2.pool
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
LOG_PATH = CONFIG_DIR / "app.log"

import sys
import configparser

# V2.0.9 - Localización robusta de config.ini.
#
# Antes se miraba en UN solo sitio (junto al .exe) con un plan B inútil (la
# carpeta actual del proceso, que casi nunca es la de la app), y si no aparecía
# se abría un MessageBox modal SIEMPRE. Eso tenía dos consecuencias malas:
#   - Abrir el ejecutable desde cualquier otra carpeta (un backup, dist/) daba
#     "Error fatal" aunque la configuración estuviera a un palmo.
#   - models.py lo importan también los procesos nocturnos (reindexar_diario,
#     poblar_propiedades, poblar_masa). Un MessageBox BLOQUEA el proceso hasta
#     que alguien pulse Aceptar: de noche, sin nadie delante, el reindexado se
#     quedaba colgado para siempre y sin rastro en el log del motivo.
CONFIG_ENV = "ALSI_CONFIG_INI"          # permite forzar la ruta desde fuera
RUTA_RED_APP = (r"\192.168.1.10\Oficina Tecnica\ALSI DOCUMENTOS OT"
                r"\APP BÚSQUEDA ARCHIVOS")

# V2.2.0 - Las credenciales pueden venir del entorno en vez del archivo.
# Motivo: config.ini lleva la contraseña de PostgreSQL en claro y el repo es
# público en GitHub. El archivo se sigue admitiendo (ningún equipo instalado
# se rompe), pero ahora hay una vía que no deja la contraseña en disco:
#   ALSI_PG_HOST / ALSI_PG_PORT / ALSI_PG_DBNAME / ALSI_PG_USER / ALSI_PG_PASSWORD
# Y el caso más útil de todos: dejar el config.ini SIN la línea password y
# poner solo ALSI_PG_PASSWORD en el entorno.
ENV_PG = {'host': 'ALSI_PG_HOST', 'port': 'ALSI_PG_PORT',
          'dbname': 'ALSI_PG_DBNAME', 'user': 'ALSI_PG_USER',
          'password': 'ALSI_PG_PASSWORD'}


def _candidatos_config():
    """Sitios donde buscar config.ini, en orden de preferencia."""
    vistos, salida = set(), []

    def add(ruta):
        if ruta and ruta not in vistos:
            vistos.add(ruta)
            salida.append(ruta)

    add(os.environ.get(CONFIG_ENV))                       # ruta forzada
    if getattr(sys, 'frozen', False):                     # junto al .exe
        add(os.path.join(os.path.dirname(sys.executable), "config.ini"))
    add(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"))
    local = os.environ.get("LOCALAPPDATA")
    if local:                                             # instalación estándar
        add(os.path.join(local, "ALSI_Buscador", "config.ini"))
    add(str(CONFIG_DIR / "config.ini"))                   # ajustes del usuario
    add(os.path.join(RUTA_RED_APP, "config.ini"))         # carpeta de red
    add(os.path.abspath("config.ini"))                    # último recurso
    return salida


def _entero(valor, por_defecto):
    try:
        n = int(str(valor).strip())
        return n if n > 0 else por_defecto
    except Exception:
        return por_defecto


def _ajustes_conexion(d, password):
    """Parte común del dict de conexión, venga del entorno o del archivo."""
    return {'host': d['host'], 'port': int(d['port']),
            'dbname': d['dbname'], 'user': d['user'],
            'password': password,
            # V2.1.0 - INCIDENCIA "la app no abre" (Pablo y Marcos):
            # sin connect_timeout, un equipo que no llega al servidor se
            # queda ~21 s bloqueado en el connect de Windows, y eso ocurría
            # ANTES de dibujar la ventana: el usuario veía un proceso en el
            # Administrador de tareas y nada más. Se puede ajustar desde
            # config.ini con  connect_timeout = N.
            'connect_timeout': _entero(d.get('connect_timeout'), 5),
            # Y con keepalives, una conexión que se queda a medias (Wi-Fi
            # o VPN que cae) se detecta en ~60 s en vez de dejar la consulta
            # colgada para siempre.
            'keepalives': 1, 'keepalives_idle': 30,
            'keepalives_interval': 10, 'keepalives_count': 3}


def _leer_entorno():
    """V2.2.0 - Conexión completa desde variables de entorno, o None.
    Es la vía preferente: no deja la contraseña escrita en ningún archivo."""
    try:
        d = {}
        for clave, var in ENV_PG.items():
            valor = (os.environ.get(var) or "").strip()
            if not valor:
                return None
            d[clave] = valor
        d['connect_timeout'] = os.environ.get("ALSI_PG_CONNECT_TIMEOUT")
        return _ajustes_conexion(d, d['password'])
    except Exception:
        return None


def _leer_config(ruta):
    """Devuelve el dict de conexión si el archivo es válido, o None.
    Un config.ini que existe pero está incompleto es tan inservible como no
    tenerlo: antes reventaba con KeyError y el usuario veía un cierre seco.
    V2.2.0: la contraseña puede faltar en el archivo si viene por entorno."""
    try:
        cfg = configparser.ConfigParser()
        cfg.read(ruta, encoding="utf-8")
        if 'database' not in cfg:
            return None
        d = cfg['database']
        if not all(k in d and d[k].strip() for k in
                   ('host', 'port', 'dbname', 'user')):
            return None
        # La contraseña del entorno manda sobre la del archivo: así un equipo
        # puede quedarse con un config.ini sin secretos.
        password = (os.environ.get(ENV_PG['password']) or "").strip()
        if not password:
            password = d.get('password', '')
            if not password.strip():
                return None
        datos = {'host': d['host'].strip(), 'port': d['port'].strip(),
                 'dbname': d['dbname'].strip(), 'user': d['user'].strip(),
                 'connect_timeout': d.get('connect_timeout')}
        return _ajustes_conexion(datos, password)
    except Exception:
        return None


def _hay_interfaz():
    """True solo para la app con ventana. Los scripts (pases nocturnos) NUNCA
    deben abrir diálogos: se quedarían bloqueados esperando un clic."""
    if not getattr(sys, 'frozen', False):
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleWindow() == 0
    except Exception:
        return True


def _avisar_fatal(msg):
    """Deja constancia SIEMPRE en el log, y además en pantalla si hay app."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n[CONFIG] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass
    try:
        sys.stderr.write(f"[CONFIG] {msg}\n")
    except Exception:
        pass
    if _hay_interfaz():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "Error de configuración", 0x10)
        except Exception:
            pass


def load_pg_config():
    # V2.2.0 - El entorno primero: si están las cinco variables ALSI_PG_*, no
    # hace falta ningún archivo y la contraseña no vive en disco.
    desde_entorno = _leer_entorno()
    if desde_entorno:
        return desde_entorno
    intentadas = ["(variables de entorno ALSI_PG_*)"]
    for ruta in _candidatos_config():
        intentadas.append(ruta)
        if os.path.exists(ruta):
            datos = _leer_config(ruta)
            if datos:
                return datos
            # existe pero no sirve: se dice y se sigue buscando
            try:
                sys.stderr.write(f"[CONFIG] ignorado (incompleto): {ruta}\n")
            except Exception:
                pass
    _avisar_fatal(
        "No se ha encontrado un config.ini válido.\n\nBuscado en:\n  " +
        "\n  ".join(intentadas) +
        "\n\nSolución: ejecuta INSTALAR_LOCAL.bat desde la carpeta de red, "
        "o define la variable de entorno " + CONFIG_ENV +
        " con la ruta del archivo, o define las cinco variables "
        "ALSI_PG_HOST / ALSI_PG_PORT / ALSI_PG_DBNAME / ALSI_PG_USER / "
        "ALSI_PG_PASSWORD.")
    sys.exit(2)


# V1.0.8 - PostgreSQL compartido (credenciales en config.ini)
PG_CONFIG = load_pg_config()

# V2.0.8 - Filtro de cordura para las propiedades físicas.
# Medido sobre 114 piezas reales: TODAS caen entre 1.000 y 8.000 kg/m3 (acero
# e inox ~7.800-8.000, plásticos ~1.000-1.300). Fuera de este rango el dato es
# basura — en la muestra apareció una "pieza" de 373 toneladas que era un
# modelo descargado de internet. Un solo dato absurdo en la rejilla destruye
# la confianza en los 590.000 buenos, así que se descarta al guardar.
DENSIDAD_MIN, DENSIDAD_MAX = 300.0, 22000.0    # kg/m3 (corcho ... wolframio)

# V2.0.8b: el rango de densidad NO basta. Si un modelo está mal escalado, masa
# y volumen crecen a la vez y la densidad sigue pareciendo correcta. Medido
# sobre los 73.377 archivos ya poblados:
#   - densidad 995-1100 = la del AGUA = "Material <sin especificar>", que es lo
#     que SolidWorks usa cuando la pieza no tiene material. Ahí la masa no
#     significa nada. Son 2.330 archivos (3,2%), y entre ellos TODOS los
#     disparates: naves, altillos y layouts (.L000/.L001, "IMPLANTACIÓN"),
#     que llegaban a 12.899 toneladas.
#   - los materiales de verdad quedan fuera de esa banda: acero e inox 7.800-8.000,
#     PE y PP 900-960, F15 1.300, PVC 1.400.
DENSIDAD_SIN_MATERIAL = (995.0, 1100.0)
MASA_MAX_KG = 50000.0    # nada de lo que se fabrica aquí pesa 50 toneladas


def fisicas_creibles(masa_kg, volumen_m3, area_m2):
    """Devuelve (masa, volumen, area) o (None, None, None) si no son creíbles.
    Se exige densidad plausible: es lo que delata los archivos mal escalados
    o sin material real."""
    try:
        m = float(masa_kg) if masa_kg else None
        v = float(volumen_m3) if volumen_m3 else None
        a = float(area_m2) if area_m2 else None
    except (TypeError, ValueError):
        return (None, None, None)
    if not m or not v or m <= 0 or v <= 0:
        return (None, None, None)
    dens = m / v
    if not (DENSIDAD_MIN < dens < DENSIDAD_MAX):
        return (None, None, None)
    # Sin material asignado la masa es la del agua: no es un dato, es un relleno
    if DENSIDAD_SIN_MATERIAL[0] <= dens <= DENSIDAD_SIN_MATERIAL[1]:
        return (None, None, None)
    if m > MASA_MAX_KG:
        return (None, None, None)
    if a is not None and a <= 0:
        a = None
    return (m, v, a)


# V2.0.7 - Expresión normalizada del nombre de archivo usada en la búsqueda.
# Tiene que coincidir LETRA POR LETRA con la del índice idx_ba_nombre_norm_trgm
# o PostgreSQL no lo usará y volveremos al escaneo completo de la tabla.
# (buscador.sin_tildes = unaccent declarado IMMUTABLE; ver crear_tablas)
NOMBRE_NORM = "UPPER(buscador.sin_tildes(nombre_archivo))"

# Configuración de Logging
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)


class SinConexionBD(psycopg2.OperationalError):
    """No se ha podido hablar con PostgreSQL (V2.1.0).

    Existe para que la interfaz pueda distinguir 'el servidor no responde' —que
    se le cuenta al usuario y se reintenta— de un fallo de programación, que es
    un error de verdad. Antes ambos casos acababan en el mismo except genérico."""


class IndexManager:
    """
    Gestor de la base de datos PostgreSQL para el buscador de piezas.
    V1.0.7 - Migrado de SQLite a PostgreSQL compartido.
    """
    def __init__(self, tolerante=False, diferido=False):
        """tolerante=True (la app con ventana): si el servidor no responde NO
        se revienta el arranque — se guarda el error, la ventana se abre igual
        y se reintenta en segundo plano. tolerante=False (procesos nocturnos):
        se propaga el error, que ahí sí debe cortar el pase."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._pool = None
        self.tolerante = tolerante
        self.ultimo_error = None
        # V2.1.0: si el hilo de reconexion esta intentando conectar (5 s), el
        # hilo de la interfaz NO debe encolar otro intento igual y quedarse
        # congelado esperando su turno.
        self._lock_pool = threading.RLock()
        if diferido:
            # V2.1.0: no se toca la red en el constructor. La app crea el
            # IndexManager mientras monta la ventana; conectar aqui significaba
            # que un servidor que no responde retrasaba la VENTANA, que es lo
            # que el usuario interpreta como "no me abre". La conexion la hace
            # despues, con la ventana ya en pantalla.
            return
        self._init_pool()
        if self._pool is not None:
            try:
                self.init_db()
            except Exception as e:
                self.ultimo_error = e
                logger.error(f"init_db falló: {e}")
                if not tolerante:
                    raise

    def _init_pool(self):
        """Inicializa el pool de conexiones PostgreSQL.

        V2.1.0: si otro hilo ya lo esta intentando, se vuelve enseguida en vez
        de bloquear. Mejor decir 'sin conexion' al instante que congelar la
        ventana cinco segundos por cada consulta."""
        if not self._lock_pool.acquire(blocking=False):
            return
        try:
            self.__init_pool_real()
        finally:
            self._lock_pool.release()

    def __init_pool_real(self):
        try:
            # V2.0.3: ThreadedConnectionPool (mismo API que SimpleConnectionPool
            # pero con locks) — las miniaturas ahora consultan la BD desde los
            # hilos de carga, además del hilo principal.
            # V2.0.3: 10 conexiones — con la búsqueda asíncrona conviven varios
            # consumidores (search worker, miniaturas por lotes, preview, galería,
            # consultas del panel). Con 5 se agotaba en picos.
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                **PG_CONFIG
            )
            self.ultimo_error = None
            logger.info("Pool de conexiones PostgreSQL inicializado correctamente")
        except Exception as e:
            self._pool = None
            self.ultimo_error = e
            logger.error(f"Error inicializando pool PostgreSQL: {e}")
            if not getattr(self, 'tolerante', False):
                raise

    def get_connection(self):
        """Obtiene una conexión del pool. Devuelve un PGConnectionWrapper.
        V2.0.3: si el pool está momentáneamente agotado (búsqueda + miniaturas
        + preview a la vez), ESPERA y reintenta hasta ~8s en vez de reventar
        con 'connection pool exhausted' al primer pico."""
        if self._pool is None or self._pool.closed:
            self._init_pool()
        if self._pool is None:
            raise SinConexionBD(str(self.ultimo_error or "sin conexión con el servidor"))
        ultimo_error = None
        for _ in range(32):
            try:
                conn = self._pool.getconn()
                return PGConnectionWrapper(conn, self._pool)
            except psycopg2.pool.PoolError as e:
                ultimo_error = e
                time.sleep(0.25)
        logger.error(f"Pool agotado tras 8s de espera: {ultimo_error}")
        raise ultimo_error

    def esta_disponible(self):
        """True si hay pool utilizable (V2.1.0)."""
        return self._pool is not None and not self._pool.closed

    def reconectar(self):
        """Reintenta la conexión. Devuelve (ok, mensaje_de_error)."""
        try:
            if self._pool is not None and not self._pool.closed:
                self._pool.closeall()
        except Exception:
            pass
        self._pool = None
        self._init_pool()
        if self._pool is None:
            return False, str(self.ultimo_error or "sin conexión")
        try:
            self.init_db()
        except Exception as e:
            self.ultimo_error = e
            return False, str(e)
        return True, ""

    @staticmethod
    def normalizar_texto(texto):
        """Convierte a mayúsculas y quita acentos/tildes"""
        if texto is None:
            return ""
        texto = unicodedata.normalize('NFKD', str(texto))
        texto = "".join([c for c in texto if not unicodedata.combining(c)])
        return texto.upper()

    # ══════════════════════════════════════════════════════════════
    # SINTAXIS DEL BUSCADOR  (V2.1.4)
    # ══════════════════════════════════════════════════════════════
    # Un guion que abre palabra EXCLUYE. Se exige que vaya pegado a la
    # palabra y precedido de espacio (o que abra el trozo) para no romper
    # los nombres que llevan guion de verdad: '26-0006', 'AC30-Q6A014'.
    _RE_EXCLUIDA = re.compile(r'(^|\s)-(\S+)')

    @classmethod
    def parsear_termino(cls, termino):
        """Descompone lo escrito en el buscador (V2.1.4).

        Devuelve (incluidas, excluidas, modo_and):
            incluidas  lo que SÍ debe aparecer en el nombre del archivo
            excluidas  lo que NO debe aparecer
            modo_and   True = tienen que estar todas · False = cualquiera

        Sintaxis:
            tuerca m16          frase exacta
            tuerca;m16          Y  — las dos
            tuerca,m16          O  — cualquiera
            cinta;450;-banda    y FUERA lo que lleve 'banda' en el nombre

        El guion solo excluye si abre el trozo ('-banda', '; - banda') o si
        va pegado a la palabra después de un espacio ('cinta -banda'). Un
        guion dentro de una palabra ('26-0006') o suelto entre espacios
        ('TAPA - IZQUIERDA') es texto normal y se busca tal cual.
        """
        texto = termino or ""
        if ';' in texto:
            trozos, modo_and = texto.split(';'), True
        elif ',' in texto:
            trozos, modo_and = texto.split(','), False
        else:
            trozos, modo_and = [texto], True

        incluidas, excluidas = [], []
        for trozo in trozos:
            t = trozo.strip()
            if not t:
                continue
            if t.startswith('-'):
                # el trozo entero es una exclusión: '-banda' y también '- banda'
                fuera = t.lstrip('-').strip()
                if fuera:
                    excluidas.append(fuera)
                continue
            for _sep, palabra in cls._RE_EXCLUIDA.findall(t):
                excluidas.append(palabra)
            t = cls._RE_EXCLUIDA.sub(lambda m: m.group(1), t).strip()
            if t:
                incluidas.append(t)
        return incluidas, excluidas, modo_and

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
                    -- V2.0.8: propiedades físicas leídas de SolidWorks
                    sw_masa_kg      DOUBLE PRECISION,
                    sw_volumen_m3   DOUBLE PRECISION,
                    sw_area_m2      DOUBLE PRECISION,
                    indexado_en     TIMESTAMP DEFAULT NOW()
                )
            ''')

            # V2.0.8: la tabla se crea con CREATE TABLE IF NOT EXISTS, así que
            # en las bases ya existentes las columnas nuevas hay que añadirlas
            # aparte (si no, todo lo de masa/superficie falla en silencio).
            for col, tipo in (('sw_masa_kg', 'DOUBLE PRECISION'),
                              ('sw_volumen_m3', 'DOUBLE PRECISION'),
                              ('sw_area_m2', 'DOUBLE PRECISION')):
                cursor.execute(
                    f'ALTER TABLE buscador.archivos ADD COLUMN IF NOT EXISTS {col} {tipo}')

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

            # V2.0.2 - Componentes: relación ensamblaje <-> pieza/subensamblaje que
            # contiene, para "¿en qué ensamblajes se usa esta pieza?".
            # Se cruza por NOMBRE de archivo en mayúsculas (robusto ante distintos
            # hosts/unidades mapeadas y correcto para piezas de biblioteca compartidas).
            # Migración: si existe con el esquema antiguo (componente_ruta), recrear.
            cursor.execute("""SELECT column_name FROM information_schema.columns
                              WHERE table_schema='buscador' AND table_name='componentes'""")
            _cols = {r[0] for r in cursor.fetchall()}
            if _cols and 'componente_nombre' not in _cols:
                cursor.execute("DROP TABLE IF EXISTS buscador.componentes")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS buscador.componentes (
                    ensamblaje_ruta   TEXT NOT NULL,
                    componente_nombre TEXT NOT NULL
                )
            ''')

            # V2.0.3 - Miniaturas: caché central de previews (JPEG ~256px) extraídas
            # con Document Manager en el reindexado. Permite ver miniaturas en
            # equipos SIN SolidWorks (la extensión shell no existe allí).
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS buscador.miniaturas (
                    ruta_completa TEXT PRIMARY KEY,
                    imagen        BYTEA NOT NULL,
                    mtime         BIGINT,
                    actualizado   TIMESTAMP DEFAULT NOW()
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
                # V2.0.3 - Sondeo del filtro Placa CE (EXISTS por código en mayúsculas)
                'CREATE INDEX IF NOT EXISTS idx_placas_plano_upper ON buscador.placas_ce(UPPER(num_plano))',
                'CREATE INDEX IF NOT EXISTS idx_comp_nombre ON buscador.componentes(componente_nombre)',
                'CREATE INDEX IF NOT EXISTS idx_comp_ensamblaje ON buscador.componentes(ensamblaje_ruta)',
                # V2.0.2 - Despiece: cruce componente_nombre -> archivos por nombre en mayúsculas
                'CREATE INDEX IF NOT EXISTS idx_ba_nombre_upper ON buscador.archivos(UPPER(nombre_archivo))',
                # V2.0.3 - Código de pieza (primer token del nombre): plano/PDF de una pieza
                "CREATE INDEX IF NOT EXISTS idx_ba_codigo ON buscador.archivos (UPPER(split_part(nombre_archivo, ' ', 1)))",
                # V2.0.3 - Filtro Placa CE: índice funcional de la expresión exacta
                "CREATE INDEX IF NOT EXISTS idx_ba_plano_e ON buscador.archivos "
                "(UPPER(SUBSTRING(nombre_archivo FROM '^[0-9]{4,6}\\.E[0-9]+')))",
                # V2.0.3 - Duplicados: mismo tamaño de archivo / misma miniatura (hash)
                'CREATE INDEX IF NOT EXISTS idx_ba_tamano ON buscador.archivos(tamano_bytes)',
                'CREATE INDEX IF NOT EXISTS idx_min_md5 ON buscador.miniaturas(md5(imagen))',
            ]
            for idx_sql in indices:
                cursor.execute(idx_sql)

            # Extensión unaccent para búsquedas sin acentos
            try:
                cursor.execute('CREATE EXTENSION IF NOT EXISTS unaccent')
            except Exception:
                logger.warning("Extensión unaccent no disponible, se usará normalización Python")

            # V2.0.7 - BÚSQUEDA INDEXADA (antes: escaneo completo de 589k filas)
            #
            # La búsqueda usaba UPPER(unaccent(nombre_archivo)) LIKE '%...%'. Es
            # correcta, pero unaccent(text) es STABLE y PostgreSQL NO permite
            # indexar expresiones no inmutables: cada búsqueda recorría la tabla
            # entera (~520 ms fijos, y mucho peor combinada con otros filtros).
            #
            # buscador.sin_tildes() es la MISMA operación declarada IMMUTABLE
            # (llama a unaccent con el diccionario explícito). Verificado sobre
            # las 589.459 filas: 0 diferencias respecto a unaccent(). Con el
            # índice GIN de trigramas encima, la misma búsqueda pasa a 3-145 ms
            # (de 4x a 172x más rápida) SIN cambiar ni un resultado.
            try:
                cursor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
                cursor.execute("""
                    CREATE OR REPLACE FUNCTION buscador.sin_tildes(text)
                    RETURNS text AS $$ SELECT public.unaccent('public.unaccent', $1) $$
                    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE""")
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ba_nombre_norm_trgm
                    ON buscador.archivos USING gin
                    (UPPER(buscador.sin_tildes(nombre_archivo)) gin_trgm_ops)""")
            except Exception as e:
                logger.warning(f"Índice de trigramas no disponible ({e}); "
                               "la búsqueda seguirá funcionando, más lenta")

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
        """V2.1.0: sin servidor no se guarda, pero tampoco se rompe nada."""
        if self._pool is None:
            logger.warning("Preferencia '%s' no guardada: sin conexion", clave)
            return
        try:
            wrapper = self.get_connection()
        except Exception as e:
            logger.warning("Preferencia '%s' no guardada: %s",
                           clave, str(e).splitlines()[0])
            return
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
        """V2.1.0: si no hay servidor devuelve el valor por defecto. Una
        preferencia es una comodidad, no una razon para no abrir la app.

        Y si la conexion aun no se ha hecho (arranque diferido) NO se provoca
        aqui: init_ui() lee una preferencia mientras monta la ventana, y con el
        servidor caido eso costaba 5 s de ventana en blanco. Las preferencias
        de verdad se aplican en cargar_preferencias(), ya conectados."""
        if self._pool is None:
            return default
        try:
            wrapper = self.get_connection()
        except Exception as e:
            logger.warning("Preferencia '%s' no leida (%s); se usa el valor por defecto",
                           clave, str(e).splitlines()[0])
            return default
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

    # ═══════════════════════════════════════════════════════════════════
    # COMPONENTES / DÓNDE SE USA (V2.0.2)
    # ═══════════════════════════════════════════════════════════════════
    @staticmethod
    def _nombre_de_ruta(ruta):
        """Basename en mayúsculas para el cruce robusto de componentes."""
        import ntpath
        return ntpath.basename(str(ruta)).upper()

    def guardar_componentes(self, cursor, ensamblaje_ruta, componentes):
        """Reemplaza los componentes de un ensamblaje. Usa el cursor de la
        indexación en curso (misma transacción). componentes = lista de rutas;
        se guarda el NOMBRE de archivo en mayúsculas (V2.0.2)."""
        cursor.execute("DELETE FROM buscador.componentes WHERE ensamblaje_ruta = %s",
                       (ensamblaje_ruta,))
        nombres = sorted({self._nombre_de_ruta(c) for c in componentes if c})
        if nombres:
            cursor.executemany(
                "INSERT INTO buscador.componentes (ensamblaje_ruta, componente_nombre) VALUES (%s, %s)",
                [(ensamblaje_ruta, n) for n in nombres])

    def buscar_ensamblajes_de(self, nombre_pieza):
        """Devuelve los ensamblajes que contienen la pieza/subensamblaje (por nombre).
        Cruza con archivos para traer los metadatos del ensamblaje (V2.0.2).
        Filas: (nombre, origen, anio, cliente, proyecto, ruta_ensamblaje)."""
        nombre = self._nombre_de_ruta(nombre_pieza)
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute('''
                SELECT DISTINCT a.nombre_archivo, a.origen, a.anio, a.cliente,
                       a.proyecto, c.ensamblaje_ruta
                FROM buscador.componentes c
                LEFT JOIN buscador.archivos a ON a.ruta_completa = c.ensamblaje_ruta
                WHERE c.componente_nombre = %s
                ORDER BY a.anio DESC NULLS LAST, a.nombre_archivo
            ''', (nombre,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error buscando ensamblajes de {nombre_pieza}: {e}")
            return []
        finally:
            wrapper.close()

    # ═══════════════════════════════════════════════════════════════════
    # MINIATURAS EN BD (V2.0.3) — para equipos sin SolidWorks
    # ═══════════════════════════════════════════════════════════════════
    def guardar_miniatura(self, cursor, ruta_completa, imagen_bytes, mtime=None):
        """Upsert de la miniatura (JPEG/PNG ya reescalada). Usa el cursor de la
        indexación en curso (misma transacción)."""
        cursor.execute('''
            INSERT INTO buscador.miniaturas (ruta_completa, imagen, mtime, actualizado)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (ruta_completa) DO UPDATE SET
                imagen = EXCLUDED.imagen, mtime = EXCLUDED.mtime, actualizado = NOW()
        ''', (ruta_completa, psycopg2.Binary(imagen_bytes), mtime))

    def obtener_miniaturas_lote(self, rutas):
        """Dict {ruta: bytes} de las miniaturas cacheadas para esa lista de
        rutas (una sola consulta). Para diálogos con muchos ítems (V2.0.3)."""
        if not rutas:
            return {}
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute("SELECT ruta_completa, imagen FROM buscador.miniaturas "
                           "WHERE ruta_completa = ANY(%s)", (list(rutas),))
            return {r[0]: bytes(r[1]) for r in cursor.fetchall() if r[1]}
        except Exception as e:
            logger.debug(f"Error leyendo miniaturas en lote: {e}")
            return {}
        finally:
            wrapper.close()


    def propiedades_fisicas(self, ruta_completa):
        """(masa_kg, volumen_m3, area_m2) de un archivo, o None (V2.0.8).
        Para el panel de vista previa: una fila por ruta, consulta indexada."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute("""SELECT sw_masa_kg, sw_volumen_m3, sw_area_m2
                              FROM buscador.archivos WHERE ruta_completa = %s""",
                           (ruta_completa,))
            fila = cursor.fetchone()
            return fila if fila and fila[0] else None
        except Exception as e:
            logger.debug(f"Error leyendo propiedades físicas: {e}")
            return None
        finally:
            wrapper.close()

    def obtener_miniatura(self, ruta_completa):
        """Bytes de la miniatura cacheada en BD, o None si no existe."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute("SELECT imagen FROM buscador.miniaturas WHERE ruta_completa = %s",
                           (ruta_completa,))
            fila = cursor.fetchone()
            return bytes(fila[0]) if fila and fila[0] else None
        except Exception as e:
            logger.debug(f"Error leyendo miniatura de {ruta_completa}: {e}")
            return None
        finally:
            wrapper.close()

    def obtener_componentes_de(self, ensamblaje_ruta):
        """Despiece (BOM): componentes de un ensamblaje, desde la tabla
        'componentes'. Para cada componente se elige el archivo indexado que
        mejor casa: primero los de la propia carpeta del ensamblaje (pieza del
        proyecto), después el más reciente (piezas de biblioteca compartidas).
        Filas: (componente_nombre, nombre_archivo, origen, anio, cliente,
                proyecto, ruta_completa, sw_masa_kg, sw_area_m2). nombre_archivo
        es NULL si el componente no está en el índice (referencia rota o carpeta
        excluida). V2.0.8: masa y superficie para poder sumar el peso total del
        conjunto y los m2 a pintar."""
        import ntpath
        carpeta = ntpath.dirname(ensamblaje_ruta)
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            # strpos en vez de LIKE: las rutas UNC llevan '\' que en LIKE es escape
            cursor.execute('''
                SELECT c.componente_nombre, a.nombre_archivo, a.origen, a.anio,
                       a.cliente, a.proyecto, a.ruta_completa,
                       a.sw_masa_kg, a.sw_area_m2
                FROM buscador.componentes c
                LEFT JOIN LATERAL (
                    SELECT nombre_archivo, origen, anio, cliente, proyecto, ruta_completa,
                           sw_masa_kg, sw_area_m2
                    FROM buscador.archivos
                    WHERE UPPER(nombre_archivo) = c.componente_nombre
                    ORDER BY (strpos(ruta_completa, %s) = 1) DESC,
                             anio DESC NULLS LAST
                    LIMIT 1
                ) a ON TRUE
                WHERE c.ensamblaje_ruta = %s
                ORDER BY c.componente_nombre
            ''', (carpeta, ensamblaje_ruta))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error obteniendo componentes de {ensamblaje_ruta}: {e}")
            return []
        finally:
            wrapper.close()

    # ═══════════════════════════════════════════════════════════════════
    # ANÁLISIS SOBRE DATOS YA INDEXADOS (V2.0.3)
    # ═══════════════════════════════════════════════════════════════════
    @staticmethod
    def _codigo_de_nombre(nombre_archivo):
        """Primer token del nombre si parece un código de pieza ALSI
        (contiene dígitos y puntos, ej. '23018.P166', 'CTS.E164'). None si no."""
        import re as _re
        token = (nombre_archivo or "").split(' ', 1)[0].strip()
        if _re.match(r'^[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$', token) and _re.search(r'\d', token):
            return token.upper()
        return None

    def buscar_documentacion_de(self, nombre_archivo):
        """Planos (.slddrw) y PDFs con el mismo código que la pieza.
        Filas: (extension, ruta_completa). Vacío si el nombre no lleva código."""
        codigo = self._codigo_de_nombre(nombre_archivo)
        if not codigo:
            return []
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute('''
                SELECT extension, ruta_completa FROM buscador.archivos
                WHERE UPPER(split_part(nombre_archivo, ' ', 1)) = %s
                  AND extension IN ('.slddrw', '.pdf')
                ORDER BY extension LIMIT 6
            ''', (codigo,))
            return cursor.fetchall()
        except Exception as e:
            logger.debug(f"Error buscando documentación de {nombre_archivo}: {e}")
            return []
        finally:
            wrapper.close()

    def resumen_componentes(self, ensamblaje_ruta):
        """(total_componentes, no_indexados) del ensamblaje — para avisar de
        referencias rotas en el preview sin abrir el despiece."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute('''
                SELECT count(*),
                       count(*) FILTER (WHERE NOT EXISTS (
                           SELECT 1 FROM buscador.archivos a
                           WHERE UPPER(a.nombre_archivo) = c.componente_nombre))
                FROM buscador.componentes c
                WHERE c.ensamblaje_ruta = %s
            ''', (ensamblaje_ruta,))
            fila = cursor.fetchone()
            return (fila[0], fila[1]) if fila else (0, 0)
        except Exception as e:
            logger.debug(f"Error en resumen_componentes de {ensamblaje_ruta}: {e}")
            return (0, 0)
        finally:
            wrapper.close()

    def piezas_mas_reutilizadas(self, limite=50):
        """Ranking de piezas usadas en más proyectos distintos y que NO están en
        biblioteca/estándar — candidatas a estandarizar. Filas:
        (componente_nombre, n_proyectos, n_ensamblajes, ruta_ejemplo)."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute('''
                SELECT c.componente_nombre,
                       COUNT(DISTINCT a.proyecto) AS n_proy,
                       COUNT(DISTINCT c.ensamblaje_ruta) AS n_ens,
                       (SELECT b.ruta_completa FROM buscador.archivos b
                        WHERE UPPER(b.nombre_archivo) = c.componente_nombre
                        ORDER BY b.anio DESC NULLS LAST LIMIT 1) AS ruta_ejemplo
                FROM buscador.componentes c
                JOIN buscador.archivos a ON a.ruta_completa = c.ensamblaje_ruta
                WHERE a.origen = 'PROYECTOS'
                  AND NOT EXISTS (SELECT 1 FROM buscador.archivos e
                                  WHERE UPPER(e.nombre_archivo) = c.componente_nombre
                                    AND e.origen IN ('ALSI_ESTANDAR', 'BIBLIOTECA_3D'))
                GROUP BY c.componente_nombre
                HAVING COUNT(DISTINCT a.proyecto) >= 2
                ORDER BY n_proy DESC, n_ens DESC
                LIMIT %s
            ''', (limite,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error en piezas_mas_reutilizadas: {e}")
            return []
        finally:
            wrapper.close()

    def ensamblajes_sin_vista_previa(self, limite=50, desde_anio=None):
        """V2.2.0 - Ensamblajes ordenados por cuántos de sus componentes no
        tienen vista previa de Windows. Sirven para abrirlos en SolidWorks,
        reconstruir (Ctrl+Q) y volver a guardar: se arreglan de golpe todas
        las piezas del conjunto.

        Un componente cuenta como "sin vista" cuando NINGÚN archivo del índice
        con ese nombre tiene miniatura guardada. La tabla `componentes` solo
        conserva el NOMBRE del componente, no su ruta, así que exigir que
        ninguna copia la tenga es el criterio conservador: los que salen están
        rotos seguro. Si se hiciera al revés (que falte en alguna copia) se
        llenaría de falsos positivos, porque una misma pieza aparece copiada
        en decenas de proyectos.

        Filas: (nombre, cliente, proyecto, anio, sin_vista, total, ruta)."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            # El filtro de año se acopla al SQL en vez de ir como
            # "(%s IS NULL OR e.anio >= %s)": con el OR, el planificador no
            # puede usar el índice de año y la consulta pasaba de 7 s a más de
            # dos minutos. Y se aplica ANTES de agrupar, para que el conteo
            # pesado solo se haga sobre los conjuntos que van a salir.
            filtro_anio = ""
            args = []
            if desde_anio is not None:
                filtro_anio = "WHERE anio >= %s"
                args.append(int(desde_anio))
            args.append(limite)
            cursor.execute('''
                WITH con_vista AS (
                    SELECT DISTINCT UPPER(a.nombre_archivo) AS nom
                    FROM buscador.miniaturas m
                    JOIN buscador.archivos a ON a.ruta_completa = m.ruta_completa
                    WHERE LOWER(a.extension) IN ('.sldprt', '.sldasm')
                ),
                conjuntos AS (
                    SELECT ruta_completa, nombre_archivo, cliente, proyecto, anio
                    FROM buscador.archivos
                    ''' + filtro_anio + '''
                ),
                conteo AS (
                    SELECT c.ensamblaje_ruta,
                           COUNT(DISTINCT c.componente_nombre)
                               FILTER (WHERE v.nom IS NULL) AS sin_vista,
                           COUNT(DISTINCT c.componente_nombre) AS total
                    FROM buscador.componentes c
                    JOIN conjuntos j ON j.ruta_completa = c.ensamblaje_ruta
                    LEFT JOIN con_vista v ON v.nom = UPPER(c.componente_nombre)
                    GROUP BY c.ensamblaje_ruta
                )
                SELECT e.nombre_archivo, e.cliente, e.proyecto, e.anio,
                       k.sin_vista, k.total, e.ruta_completa
                FROM conteo k
                JOIN conjuntos e ON e.ruta_completa = k.ensamblaje_ruta
                WHERE k.sin_vista > 0
                ORDER BY k.sin_vista DESC, e.nombre_archivo
                LIMIT %s
            ''', tuple(args))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error en ensamblajes_sin_vista_previa: {e}")
            return []
        finally:
            wrapper.close()

    def buscar_similares(self, ruta_completa, limite=60):
        """Piezas con el mismo material + espesor + patrón de procesos que la
        dada (excluyéndola). Filas: (nombre, anio, cliente, proyecto, ruta)."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute('''SELECT sw_material, sw_espesor, sw_laser, sw_torno,
                                     sw_fresa, sw_soldadura, sw_pintura
                              FROM buscador.archivos WHERE ruta_completa = %s''',
                           (ruta_completa,))
            fila = cursor.fetchone()
            if not fila or not fila[0]:
                return None  # sin material: no hay base para comparar
            material, espesor = fila[0], fila[1]
            procesos = fila[2:]
            condiciones = ["extension = '.sldprt'", "ruta_completa <> %s", "sw_material = %s"]
            params = [ruta_completa, material]
            if espesor:
                condiciones.append("sw_espesor = %s")
                params.append(espesor)
            for col, val in zip(('sw_laser', 'sw_torno', 'sw_fresa', 'sw_soldadura', 'sw_pintura'),
                                procesos):
                if val:
                    condiciones.append(f"{col} = %s")
                    params.append(val)
                else:
                    condiciones.append(f"({col} IS NULL OR {col} = '' OR {col} ILIKE 'NO')")
            params.append(limite)
            cursor.execute(f'''
                SELECT nombre_archivo, anio, cliente, proyecto, ruta_completa
                FROM buscador.archivos
                WHERE {' AND '.join(condiciones)}
                ORDER BY anio DESC NULLS LAST, nombre_archivo
                LIMIT %s
            ''', params)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error buscando similares de {ruta_completa}: {e}")
            return []
        finally:
            wrapper.close()

    def buscar_ensamblajes_que_contienen(self, termino, compañeros=None, años=None,
                                         carpetas=None, clientes=None, proyectos=None,
                                         solo_placa_ce=False, limite=5000,
                                         profundo=False):
        """Busca ENSAMBLAJES que contengan la pieza/subensamblaje indicado
        (V2.0.3). El término se busca en los nombres de los componentes
        (tabla 'componentes'), no en el nombre del ensamblaje.
        Misma sintaxis del buscador: espacio=frase, ';'=Y, ','=O y
        '-palabra'=fuera los que lleven ese componente (V2.1.4).
        Devuelve filas con el MISMO formato que buscar(), para que la vista
        las pinte igual."""
        if not (termino or "").strip():
            return []

        # V2.1.4: misma gramática que el buscador principal. Aquí un
        # '-palabra' quita los conjuntos que LLEVEN un componente así.
        keywords, excluidas, modo_and = self.parsear_termino(termino)
        if not keywords:
            return []

        base_cols = """a.nombre_archivo, a.origen, a.anio, a.cliente, a.proyecto, a.tipo_carpeta,
                       a.codigo_proyecto, a.nombre_proyecto, a.codigo_orden, a.nombre_orden,
                       a.ruta_completa, a.sw_material, a.sw_tratamiento, a.sw_espesor,
                       a.sw_laser, a.sw_torno, a.sw_fresa, a.sw_soldadura, a.sw_pintura,
                       a.sw_montaje"""

        params = []
        if profundo:
            # V2.0.3: cualquier nivel — se resuelve el conjunto de rutas con el
            # CTE recursivo (por keyword) y se filtra por pertenencia.
            wrapper_p = self.get_connection()
            try:
                cur_p = wrapper_p._conn.cursor()
                conjuntos = [self._rutas_que_contienen(cur_p, kw, True) for kw in keywords]
                fuera = set()
                for ex in excluidas:
                    fuera |= self._rutas_que_contienen(cur_p, ex, True)
            finally:
                wrapper_p.close()
            rutas_ok = conjuntos[0] if conjuntos else set()
            for c in conjuntos[1:]:
                rutas_ok = (rutas_ok & c) if modo_and else (rutas_ok | c)
            rutas_ok -= fuera          # V2.1.4: '-palabra' se resta al final
            if not rutas_ok:
                return []
            where = ["a.ruta_completa = ANY(%s)"]
            params.append(list(rutas_ok))
        else:
            # Un EXISTS por keyword: AND = todas las piezas, OR = cualquiera
            cond_kw = []
            for kw in keywords:
                cond_kw.append(
                    "EXISTS (SELECT 1 FROM buscador.componentes c"
                    "  WHERE c.ensamblaje_ruta = a.ruta_completa"
                    "    AND UPPER(unaccent(c.componente_nombre)) LIKE %s)")
                params.append(f"%{self.normalizar_texto(kw)}%")
            where = [f"({(' AND ' if modo_and else ' OR ').join(cond_kw)})"]
            # V2.1.4: y fuera los que lleven un componente excluido
            for ex in excluidas:
                where.append(
                    "NOT EXISTS (SELECT 1 FROM buscador.componentes c"
                    "  WHERE c.ensamblaje_ruta = a.ruta_completa"
                    "    AND UPPER(unaccent(c.componente_nombre)) LIKE %s)")
                params.append(f"%{self.normalizar_texto(ex)}%")

        if compañeros:
            where.append("a.origen IN (%s)" % ','.join(['%s'] * len(compañeros)))
            params.extend(compañeros)
        if años:
            where.append("a.anio IN (%s)" % ','.join(['%s'] * len(años)))
            params.extend([int(x) for x in años])
        if carpetas:
            where.append("a.tipo_carpeta IN (%s)" % ','.join(['%s'] * len(carpetas)))
            params.extend(carpetas)
        if clientes:
            where.append("a.cliente IN (%s)" % ','.join(['%s'] * len(clientes)))
            params.extend(clientes)
        if proyectos:
            where.append("a.codigo_proyecto IN (%s)" % ','.join(['%s'] * len(proyectos)))
            params.extend(proyectos)
        if solo_placa_ce:
            where.append(
                "EXISTS (SELECT 1 FROM buscador.placas_ce pce"
                "  WHERE pce.num_plano IS NOT NULL AND pce.num_plano != ''"
                "    AND UPPER(pce.num_plano) ="
                "        UPPER(SUBSTRING(a.nombre_archivo FROM '^[0-9]{4,6}\\.E[0-9]+')))")

        params.append(limite)
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute(f'''
                SELECT {base_cols}
                FROM buscador.archivos a
                WHERE a.extension = '.sldasm'
                  AND {' AND '.join(where)}
                ORDER BY a.anio DESC NULLS LAST, a.nombre_archivo
                LIMIT %s
            ''', params)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error en buscar_ensamblajes_que_contienen('{termino}'): {e}")
            return []
        finally:
            wrapper.close()

    # SQL recursivo compartido: ensamblajes que contienen el término a
    # CUALQUIER profundidad (pieza dentro de subconjunto dentro de conjunto).
    # UNION (no UNION ALL) deduplica y corta ciclos automáticamente.
    _SQL_CONTIENE_PROFUNDO = """
        WITH RECURSIVE hallados AS (
            SELECT DISTINCT c.ensamblaje_ruta AS ruta
            FROM buscador.componentes c
            WHERE UPPER(unaccent(c.componente_nombre)) LIKE %s
          UNION
            SELECT c2.ensamblaje_ruta
            FROM hallados h
            JOIN buscador.archivos a ON a.ruta_completa = h.ruta
            JOIN buscador.componentes c2
              ON UPPER(c2.componente_nombre) = UPPER(a.nombre_archivo)
        )
        SELECT ruta FROM hallados
    """

    def _rutas_que_contienen(self, cursor, keyword, profundo):
        """Conjunto de rutas de ensamblajes que contienen la keyword.
        profundo=False: componentes directos. True: cualquier nivel."""
        kw = f"%{self.normalizar_texto(keyword)}%"
        if profundo:
            cursor.execute(self._SQL_CONTIENE_PROFUNDO, (kw,))
        else:
            cursor.execute(
                "SELECT DISTINCT ensamblaje_ruta FROM buscador.componentes "
                "WHERE UPPER(unaccent(componente_nombre)) LIKE %s", (kw,))
        return {r[0] for r in cursor.fetchall()}

    def filtrar_por_componente(self, rutas, termino, profundo=False):
        """Refinado 'que contenga' (V2.0.3): de las rutas dadas (ensamblajes de
        los resultados actuales), devuelve el SET de las que contienen algún
        componente directo (pieza o subensamblaje) cuyo nombre casa con el
        término. Misma sintaxis que el buscador: espacio=frase, ';'=Y, ','=O."""
        if not rutas or not (termino or "").strip():
            return set()

        if ';' in termino:
            keywords = [k.strip() for k in termino.split(';') if k.strip()]
            modo_and = True
        elif ',' in termino:
            keywords = [k.strip() for k in termino.split(',') if k.strip()]
            modo_and = False
        else:
            keywords = [termino.strip()]
            modo_and = True

        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            pedidas = set(rutas)
            conjuntos = []
            for kw in keywords:
                if profundo:
                    # cualquier nivel: se calcula global y se intersecta
                    conjuntos.append(self._rutas_que_contienen(cursor, kw, True) & pedidas)
                else:
                    cursor.execute('''
                        SELECT DISTINCT ensamblaje_ruta FROM buscador.componentes
                        WHERE ensamblaje_ruta = ANY(%s)
                          AND UPPER(unaccent(componente_nombre)) LIKE %s
                    ''', (list(rutas), f'%{self.normalizar_texto(kw)}%'))
                    conjuntos.append({r[0] for r in cursor.fetchall()})
            if not conjuntos:
                return set()
            resultado = conjuntos[0]
            for c in conjuntos[1:]:
                resultado = (resultado & c) if modo_and else (resultado | c)
            return resultado
        except Exception as e:
            logger.error(f"Error en filtrar_por_componente: {e}")
            return set()
        finally:
            wrapper.close()

    def ensamblajes_similares(self, ensamblaje_ruta, limite=30):
        """Ensamblajes que comparten un alto porcentaje de piezas con el dado
        (V2.0.3). Ignora las piezas ultra-comunes (en >2000 ensamblajes:
        arandelas, tornillería...) para que no dominen la señal. Filas:
        (nombre, pct, comunes, n_suyo, n_mio, cliente, proyecto, anio, ruta)."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute('''
                WITH mis AS (
                    SELECT componente_nombre FROM buscador.componentes
                    WHERE ensamblaje_ruta = %s
                ),
                raros AS (
                    SELECT c.componente_nombre
                    FROM buscador.componentes c
                    WHERE c.componente_nombre IN (SELECT componente_nombre FROM mis)
                    GROUP BY c.componente_nombre
                    HAVING count(*) <= 2000
                ),
                cand AS (
                    SELECT c2.ensamblaje_ruta, count(*) AS comunes
                    FROM buscador.componentes c2
                    JOIN raros r ON r.componente_nombre = c2.componente_nombre
                    WHERE c2.ensamblaje_ruta <> %s
                    GROUP BY c2.ensamblaje_ruta
                    ORDER BY comunes DESC
                    LIMIT 80
                )
                SELECT a.nombre_archivo, cand.comunes,
                       (SELECT count(*) FROM buscador.componentes cc
                        WHERE cc.ensamblaje_ruta = cand.ensamblaje_ruta) AS n_suyo,
                       (SELECT count(*) FROM mis) AS n_mio,
                       a.cliente, a.proyecto, a.anio, cand.ensamblaje_ruta
                FROM cand
                LEFT JOIN buscador.archivos a ON a.ruta_completa = cand.ensamblaje_ruta
                ORDER BY cand.comunes DESC
            ''', (ensamblaje_ruta, ensamblaje_ruta))
            filas = []
            for nom, comunes, n_suyo, n_mio, cliente, proyecto, anio, ruta in cursor.fetchall():
                base = max(n_suyo or 0, n_mio or 0, 1)
                pct = int(round(100.0 * comunes / base))
                filas.append((nom, pct, comunes, n_suyo, n_mio, cliente, proyecto, anio, ruta))
            filas.sort(key=lambda f: (-f[1], -f[2]))
            return filas[:limite]
        except Exception as e:
            logger.error(f"Error en ensamblajes_similares de {ensamblaje_ruta}: {e}")
            return []
        finally:
            wrapper.close()

    def piezas_identicas(self, ruta_completa):
        """Posibles duplicados geométricos de la pieza (V2.0.3), por dos señales:
        - 'archivo idéntico': misma extensión y mismo tamaño exacto de archivo
          (copias renombradas).
        - 'vista previa idéntica': misma miniatura embebida bit a bit (md5) —
          los archivos copiados conservan el preview aunque cambie el nombre.
        Filas: (nombre, coincidencia, anio, cliente, proyecto, ruta)."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            # Señal principal: misma miniatura embebida bit a bit (md5). El
            # tamaño de archivo por sí solo da falsos positivos (verificado),
            # así que solo se usa para CONFIRMAR ("copia exacta").
            cursor.execute('''
                SELECT a2.nombre_archivo, a2.anio, a2.cliente, a2.proyecto,
                       a2.ruta_completa,
                       (a2.tamano_bytes = a1.tamano_bytes) AS mismo_tamano
                FROM buscador.miniaturas m1
                JOIN buscador.miniaturas m2
                  ON md5(m2.imagen) = md5(m1.imagen)
                 AND m2.ruta_completa <> m1.ruta_completa
                JOIN buscador.archivos a1 ON a1.ruta_completa = m1.ruta_completa
                JOIN buscador.archivos a2 ON a2.ruta_completa = m2.ruta_completa
                WHERE m1.ruta_completa = %s
                ORDER BY a2.anio DESC NULLS LAST
                LIMIT 200
            ''', (ruta_completa,))
            filas = []
            for nom, anio, cli, pro, ruta, mismo_tam in cursor.fetchall():
                etiqueta = "copia exacta" if mismo_tam else "vista previa idéntica"
                filas.append((nom, etiqueta, anio, cli, pro, ruta))
            filas.sort(key=lambda f: (0 if f[1] == "copia exacta" else 1, str(f[0])))
            return filas
        except Exception as e:
            logger.error(f"Error en piezas_identicas de {ruta_completa}: {e}")
            return []
        finally:
            wrapper.close()

    def obtener_ultima_indexacion(self):
        """Timestamp (epoch) de la indexación más reciente, o None (V2.0.0)."""
        wrapper = self.get_connection()
        try:
            cursor = wrapper._conn.cursor()
            cursor.execute("SELECT MAX(ultima_indexacion) FROM buscador.estado_indexacion")
            res = cursor.fetchone()
            return res[0] if res and res[0] else None
        except Exception:
            return None
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

        # V2.1.4: una sola gramatica para todo el buscador. '-palabra' quita
        # del resultado los nombres que la lleven; convive con ';' y ','.
        keywords, excluidas, is_and_search = self.parsear_termino(termino)
        if excluidas:
            logger.info("Excluyendo del nombre: %s", ", ".join(excluidas))

        params = []
        base_cols = """nombre_archivo, origen, anio, cliente, proyecto, tipo_carpeta,
                       codigo_proyecto, nombre_proyecto, codigo_orden, nombre_orden,
                       ruta_completa, sw_material, sw_tratamiento, sw_espesor,
                       sw_laser, sw_torno, sw_fresa, sw_soldadura, sw_pintura, sw_montaje,
                       sw_masa_kg, sw_area_m2"""

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
                    f"CASE WHEN {NOMBRE_NORM} LIKE %s THEN {peso_posicion * 100} ELSE 0 END"
                )
                params.append(f"%{kw_norm}%")

            # Los planos que vienen de un nº de placa puntúan por encima de todo
            for plano in planos_de_placas:
                score_cases.append("CASE WHEN UPPER(nombre_archivo) LIKE %s THEN 10000 ELSE 0 END")
                params.append(f"{plano.upper()}%")

            score_sql = " + ".join(score_cases)
            logic_op = " AND " if is_and_search else " OR "
            where_clause = logic_op.join(
                [f"{NOMBRE_NORM} LIKE %s" for _ in keywords]
            )
            params.extend([f"%{self.normalizar_texto(k)}%" for k in keywords])

            # La coincidencia por placa siempre entra en OR (aunque la búsqueda sea AND)
            if planos_de_placas:
                placa_clause = " OR ".join(["UPPER(nombre_archivo) LIKE %s" for _ in planos_de_placas])
                where_clause = f"({where_clause}) OR ({placa_clause})"
                params.extend([f"{p.upper()}%" for p in planos_de_placas])

            query_select = f"SELECT {base_cols}, ({score_sql}) as score FROM buscador.archivos"
            base_where = f"({where_clause})"

        # V2.1.4: '-palabra' -> fuera todo nombre que la contenga. Va siempre
        # en Y, aunque la busqueda sea de tipo O: quitar es quitar.
        for fuera in excluidas:
            base_where += f" AND {NOMBRE_NORM} NOT LIKE %s"
            params.append(f"%{self.normalizar_texto(fuera)}%")

        # V2.1.0 - Filtro "Solo máquinas con placa CE": el prefijo del nombre de
        # archivo (ej. "26047.E107") debe existir como num_plano en placas_ce
        if solo_placa_ce:
            # V2.0.3: MISMA regla (código .E del nombre presente en placas_ce)
            # reescrita como EXISTS correlacionado: el planificador filtra
            # primero por término/años/tipo y sondea placas_ce por índice
            # (con IN(subconsulta) elegía un plan de ~20s; ahora ~0.1s).
            base_where += (
                " AND EXISTS (SELECT 1 FROM buscador.placas_ce pce"
                "  WHERE pce.num_plano IS NOT NULL AND pce.num_plano != ''"
                "    AND UPPER(pce.num_plano) ="
                "        UPPER(SUBSTRING(nombre_archivo FROM '^[0-9]{4,6}\\.E[0-9]+')))"
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

        # V2.0.7: ruta_completa como último criterio de desempate. Sin él, al
        # cortar en 5000 el conjunto devuelto dependía del plan de acceso, así
        # que dos búsquedas idénticas podían enseñar 5000 filas DISTINTAS (se
        # notó al indexar la búsqueda: mismo conjunto, distinto recorte).
        query += (" ORDER BY score DESC, ultima_modificacion DESC NULLS LAST,"
                  " ruta_completa LIMIT 5000")

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
