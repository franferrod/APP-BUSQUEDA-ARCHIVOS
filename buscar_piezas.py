import sys
import os

# Redirigir errores críticos a un archivo temporal (para debug de PyInstaller noconsole)
error_log = os.path.expanduser("~/.alsi_busqueda/startup_error.log")
try:
    os.makedirs(os.path.dirname(error_log), exist_ok=True)
    sys.stderr = open(error_log, 'w', encoding='utf-8')
    sys.stdout = sys.stderr
except Exception:
    pass

import time
import sqlite3
import re
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QStatusBar, QProgressBar, QLabel, QMessageBox, 
                             QMenu, QAction, QAbstractItemView, QListWidget, QListWidgetItem,
                             QDialog, QDialogButtonBox, QSplitter, QGroupBox, QFrame, QScrollArea,
                             QCheckBox, QSizePolicy, QGraphicsOpacityEffect, QTextBrowser, QFileDialog, QListView, QGraphicsDropShadowEffect,
                             QStyledItemDelegate, QStyleOptionViewItem, QStyle, QButtonGroup, QStackedWidget,
                             QSlider)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QPoint, QMimeData, QUrl, QTimer, QPropertyAnimation, QEvent, QSettings, QRect, QObject
from PyQt5.QtGui import QIcon, QFont, QColor, QPixmap, QDrag, QImage, QPainter, QPen, QPalette
from PyQt5.QtWidgets import QFileIconProvider
import pythoncom
import logging
import logging.handlers
import threading
import uuid
import json
from win32com.shell import shell, shellcon
from PyQt5.QtWinExtras import QtWin


class CheckableMenu(QMenu):
    """QMenu que no se cierra al hacer clic en acciones checkable (V1.0.0 R5)"""
    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action and action.isCheckable():
            action.trigger()
            return  # No cerrar el menú
        super().mouseReleaseEvent(event)

# Configuración de directorios y Logging profesional
LOG_DIR = os.path.expanduser("~/.alsi_busqueda")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)

RUTA_LOG = os.path.join(LOG_DIR, "app.log")

# V2.1.0 - El log se rota: antes crecia sin limite y acababa siendo inmanejable
# justo cuando hacia falta leerlo. 3 MB x 4 archivos = historial de sobra.
_manejadores = [logging.handlers.RotatingFileHandler(
    RUTA_LOG, maxBytes=3_000_000, backupCount=3, encoding='utf-8')]
# OJO: en el .exe empaquetado sin consola, sys.stderr es None. Un StreamHandler
# sobre None revienta al primer log y puede tumbar la app antes de que se vea
# nada. Solo se anade si hay consola de verdad.
if getattr(sys, 'stderr', None) is not None:
    _manejadores.append(logging.StreamHandler())
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=_manejadores
)
logger = logging.getLogger("BuscadorALSI")

# V2.1.0 - Los cuelgues duros (fallo de segmentacion en Qt, DLL que revienta) no
# pasan por excepthook: no dejaban ni una linea y el usuario solo veia que "no
# abre". faulthandler escribe la pila en un archivo aparte antes de morir.
try:
    import faulthandler
    _f_crash = open(os.path.join(LOG_DIR, "crash.log"), "a", encoding="utf-8")
    _f_crash.write("\n===== %s arranque =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    _f_crash.flush()
    faulthandler.enable(file=_f_crash)
except Exception:
    pass


def proceso_vivo(pid):
    """True si ese PID sigue existiendo (V2.1.1).

    Se usa para no dejar a nadie fuera por un candado huerfano: si el proceso
    que lo puso ya no existe, el candado se retira. Ante la duda se responde
    True, que es el lado seguro (respetar el candado).
    """
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        codigo = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(codigo))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and codigo.value == STILL_ACTIVE
    except Exception:
        return True


def avisar_usuario(titulo, mensaje):
    """Ensena un aviso SIEMPRE, haya o no interfaz creada todavia (V2.1.0).

    El error de arranque es justo el que ocurre antes de que exista QApplication,
    y ahi un QMessageBox lanza excepcion: el aviso se perdia y la app moria en
    silencio. Con ctypes se usa el cuadro de dialogo de Windows, que no depende
    de Qt."""
    # V2.1.1: solo el titulo y el principio del mensaje. Volcar textos largos
    # (el informe de diagnostico entero, por ejemplo) en una sola linea deja el
    # registro ilegible justo cuando hay que leerlo.
    resumen = str(mensaje).replace(chr(10), " / ")
    if len(resumen) > 240:
        resumen = resumen[:240] + " […]"
    logger.warning("AVISO AL USUARIO | %s | %s", titulo, resumen)
    # V2.1.0: los arranques desatendidos (comprobaciones automaticas, pases
    # nocturnos) NO deben quedarse esperando un clic que nadie va a dar. Misma
    # leccion que en la V2.0.8 con los scripts de noche.
    if os.environ.get("ALSI_SIN_DIALOGOS"):
        return
    try:
        if QApplication.instance() is not None:
            QMessageBox.critical(None, titulo, mensaje)
            return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, mensaje, titulo, 0x10)
    except Exception:
        pass


def exception_hook(exctype, value, traceback):
    """Captura cualquier excepcion no gestionada para que la app no se cierre"""
    logger.error("Excepcion no capturada", exc_info=(exctype, value, traceback))
    # V2.0.0: las carreras benignas de cierre (senal llega a un widget ya
    # destruido) se registran en el log pero no molestan al usuario con un popup
    if exctype is RuntimeError and "has been deleted" in str(value):
        return
    import traceback as _tb
    mostrar_error(
        "Error inesperado",
        "Se ha producido un error inesperado. La aplicación intentará seguir "
        "funcionando.\n\n%s" % value,
        "".join(_tb.format_exception(exctype, value, traceback)))

sys.excepthook = exception_hook

def resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso, funciona para dev y para PyInstaller"""
    try:
        # PyInstaller crea una carpeta temporal y guarda la ruta en _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    # Intentar encontrar el archivo en la ruta base
    full_path = os.path.join(base_path, relative_path)
    if not os.path.exists(full_path):
        # Fallback para desarrollo: buscar relativo al script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, relative_path)
        
    return full_path

# Importaciones locales (MVC Architecture)
from models import IndexManager, PG_CONFIG, SinConexionBD
from controllers import SearchController, IndexadorThread

# Configuración Global
CONFIG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
# V1.0.7 - Base de datos PostgreSQL compartida (ya no hay DB_PATH local)

# Colores Corporativos ALSI
RAL_2010_NARANJA = "#E15B1E"  # Naranja corporativo
RAL_7000_GRIS = "#78858B"     # Gris corporativo
WHITE = "#FFFFFF"

# Logos y Recursos (V1.0.0)
LOGO_ISOTIPO = resource_path("ALSI_ISOTIPO_naranja.png")
LOGO_IMAGOTIPO = resource_path("ALSI_IMAGOTIPO_naranja.png")
APP_ICON = resource_path("ALSI_BUSCADOR.ico")

# V2.0.1 - Host del NAS Synology: algunos equipos acceden por IP (192.168.1.10)
# y otros por nombre (NASCENTRAL) — por IP les pide credenciales y fallan los
# archivos. Las rutas se guardan en BD con la IP; al TOCAR un archivo se reescriben
# al host que funcione en ESTE equipo. El primero de la lista que responda se usa.
NAS_HOSTS = ["192.168.1.10", "NASCENTRAL"]
NAS_HOST_CANONICO = "192.168.1.10"  # como se guardan las rutas en la BD
NAS_HOST_ACTIVO = None              # detectado al arrancar


def existe_con_limite(ruta, segundos=3.0):
    """os.path.exists con tope de tiempo (V2.1.0).

    En Windows, comprobar un recurso de red que no responde puede bloquear
    decenas de segundos: resolucion del nombre (NASCENTRAL por NetBIOS/DNS) mas
    la negociacion SMB. Esa llamada estaba en el arranque, ANTES de dibujar la
    ventana, y es la causa de los "no me abre la app" de Pablo y Marcos: el
    proceso existia pero no pintaba nada hasta que Windows se rendia.

    La comprobacion corre en un hilo demonio: si tarda mas de la cuenta se da
    por fallida y el arranque sigue.
    """
    resultado = {}

    def _probar():
        try:
            resultado['ok'] = os.path.exists(ruta)
        except Exception:
            resultado['ok'] = False

    h = threading.Thread(target=_probar, daemon=True)
    h.start()
    h.join(segundos)
    if 'ok' not in resultado:
        logger.warning("Comprobacion de %s abandonada tras %.1fs (no responde)",
                       ruta, segundos)
        return False
    return resultado['ok']


def detectar_nas_host(segundos_por_host=3.0):
    """Detecta por cual host es accesible el NAS en este equipo (V2.0.1).

    V2.1.0: con tope de tiempo por host. Si ninguno responde NO se bloquea el
    arranque: se sigue con el host por defecto y "Abrir carpeta" vuelve a
    detectarlo en el momento de usarlo (resolver_para_abrir, V2.0.9)."""
    global NAS_HOST_ACTIVO
    t0 = time.time()
    for host in NAS_HOSTS:
        try:
            if existe_con_limite(r"\\%s\Oficina Tecnica" % host, segundos_por_host):
                NAS_HOST_ACTIVO = host
                logger.info("NAS accesible por: %s (%.1fs)", host, time.time() - t0)
                return host
        except Exception:
            continue
    NAS_HOST_ACTIVO = NAS_HOSTS[0]
    logger.warning("Ningun host del NAS respondio en %.1fs; se usara %s "
                   "(se reintentara al abrir archivos)",
                   time.time() - t0, NAS_HOST_ACTIVO)
    return NAS_HOST_ACTIVO


def ruta_accesible(ruta):
    """Reescribe el host del NAS en 'ruta' al que funciona en este equipo.
    Si aún no se ha detectado, la deja igual (V2.0.1)."""
    if not ruta or not NAS_HOST_ACTIVO:
        return ruta
    for host in NAS_HOSTS:
        if host.upper() == NAS_HOST_ACTIVO.upper():
            continue
        pref = "\\\\" + host + "\\"
        if ruta[:len(pref)].upper() == pref.upper():
            return "\\\\" + NAS_HOST_ACTIVO + "\\" + ruta[len(pref):]
    return ruta


def _con_host(ruta, host):
    """Devuelve 'ruta' con el host UNC sustituido por 'host'."""
    B = chr(92)
    if not ruta or not ruta.startswith(B + B):
        return ruta
    resto = ruta[2:]
    i = resto.find(B)
    if i < 0:
        return ruta
    return B + B + host + resto[i:]


def resolver_para_abrir(ruta):
    """Devuelve (ruta_utilizable, motivo) para abrir un archivo (V2.0.9).

    NAS_HOST_ACTIVO se detecta UNA sola vez al arrancar. Si el NAS no respondia
    en ese instante -- abrir la app nada mas iniciar sesion, antes de que la red
    o las credenciales esten listas, es lo tipico -- TODOS los "Abrir carpeta"
    fallaban el resto de la sesion aunque la red se recuperase enseguida, y el
    aviso culpaba al servidor sin comprobarlo.

    Aqui se prueban todas las variantes de host en el momento de usarlo, se
    redetecta el host bueno si cambia, y se distingue la causa real.

    motivo: 'ok' | 'archivo_no_esta' | 'sin_permiso' | 'sin_servidor'
    """
    global NAS_HOST_ACTIVO
    if not ruta:
        return (None, 'sin_servidor')

    candidatas, vistas = [], set()
    for cand in [ruta_accesible(ruta), ruta] + [_con_host(ruta, h) for h in NAS_HOSTS]:
        if cand and cand not in vistas:
            vistas.add(cand)
            candidatas.append(cand)

    carpeta_vista = False
    for cand in candidatas:
        try:
            if os.path.exists(cand):
                host = cand[2:].split(chr(92))[0] if cand.startswith(chr(92) * 2) else ''
                if host and host.upper() != (NAS_HOST_ACTIVO or '').upper():
                    NAS_HOST_ACTIVO = host
                    logger.info("NAS re-detectado: accesible por %s" % host)
                return (cand, 'ok')
            if os.path.isdir(os.path.dirname(cand)):
                carpeta_vista = True
        except PermissionError:
            return (cand, 'sin_permiso')
        except OSError as e:
            if getattr(e, 'winerror', None) in (5, 1314):
                return (cand, 'sin_permiso')
        except Exception:
            continue

    if carpeta_vista:
        return (candidatas[0], 'archivo_no_esta')
    return (candidatas[0], 'sin_servidor')


MENSAJES_RUTA = {
    'archivo_no_esta': (
        "El archivo ya no esta en esa carpeta.\n\n"
        "Lo mas probable es que se haya movido o renombrado despues de la "
        "ultima indexacion. La carpeta si es accesible: se abrira para que "
        "puedas buscarlo."),
    'sin_permiso': (
        "No tienes permiso para acceder a esa carpeta del NAS.\n\n"
        "Habla con quien gestione los permisos del servidor: no es un "
        "problema de la aplicacion."),
    'sin_servidor': (
        "No se llega al servidor en este momento.\n\n"
        "Comprueba la conexion de red. Si acabas de encender el equipo, "
        "espera unos segundos y vuelve a intentarlo."),
}


def rutas_nas_activas():
    """RUTAS_NAS con el host activo (para diagnóstico y diálogo de reindexado)."""
    return {k: ruta_accesible(v) for k, v in RUTAS_NAS.items()}


# v1.0.7 - Rutas NAS nuevo (modelo por origen, sustituye RUTAS_RED por compañero)
RUTAS_NAS = {
    'PROYECTOS':     r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS',
    'BIBLIOTECA_3D': r'\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D',
    'ALSI_ESTANDAR': r'\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR',
}

# Etiquetas legibles para la UI (V2.0.0: unificadas en mayúsculas en TODA la app:
# filtros, columnas de tabla, preview, galería y diálogos)
ETIQUETAS_ORIGEN = {
    'PROYECTOS':     'PROYECTOS',
    'BIBLIOTECA_3D': 'BIBLIOTECA 3D',
    'ALSI_ESTANDAR': 'ALSI ESTANDAR',
}


def etiqueta_origen(texto):
    """Convierte claves internas (ALSI_ESTANDAR, BIBLIOTECA_3D) a su etiqueta
    unificada de UI. Deja intacto cualquier otro valor."""
    return ETIQUETAS_ORIGEN.get(texto, texto)

# Versión de la app (fuente única: "Acerca de" y comprobación de updates)
APP_VERSION = "2.3.2"

# Carpeta de despliegue de la app en el NAS (para auto-actualización / check_for_updates).
# NAS nuevo (2026): migrado desde \\192.168.1.229\Volume_1\ALSI INTERCAMBIO\...
RUTA_DESPLIEGUE_APP = r'\\192.168.1.10\Oficina Tecnica\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS'

EXTENSIONES = ('.sldprt', '.sldasm', '.slddrw', '.dwg', '.pdf', '.step', '.stp', '.iges', '.igs')

# Mapeo de filtro de carpetas (Cambio V1.2.2 - Recuperado)
FILTRO_CARPETAS = [
    'TODOS',
    'MECANICA',
    'LAYOUT',
    'PLIEGO DE CONDICIONES',
    'LISTADOS',
    'OFERTAS Y PEDIDOS',
    'OTROS'
]

# Mapeo de filtro tipo archivo → extensiones SQL
FILTRO_EXTENSIONES = {
    'TODOS': None,
    'PIEZAS': ['.sldprt'],          # Antes: PIEZAS (.sldprt)
    'ENSAMBLAJES': ['.sldasm'],     # Antes: ENSAMBLAJES (.sldasm)
    'DIBUJOS': ['.slddrw'],         # Antes: DIBUJOS (.slddrw)
    'DWG': ['.dwg'],                # Antes: DWG (.dwg)
    'PDF': ['.pdf'],
    'STEP / IGES': ['.step', '.stp', '.iges', '.igs'],
}

# Iconos por extensión para el panel de previsualización
ICONOS_EXTENSION = {
    '.sldprt': '🔧',   # Pieza
    '.sldasm': '⚙️',    # Ensamblaje
    '.slddrw': '📐',   # Plano SolidWorks
    '.dwg': '📐',      # Plano AutoCAD
    '.pdf': '📄',      # PDF
    '.step': '📦', '.stp': '📦',
    '.iges': '📦', '.igs': '📦',
}

DESCRIPCIONES_EXTENSION = {
    '.sldprt': 'Pieza SolidWorks',
    '.sldasm': 'Ensamblaje SolidWorks',
    '.slddrw': 'Plano SolidWorks',
    '.dwg': 'Plano AutoCAD',
    '.pdf': 'Documento PDF',
    '.step': 'Archivo STEP', '.stp': 'Archivo STEP',
    '.iges': 'Archivo IGES', '.igs': 'Archivo IGES',
}

# ═══════════════════════════════════════════════════════════════════════════
# V2.0.0 - SISTEMA DE MARCA (fuentes + tema oscuro, ver handoff/SPEC.md)
#   AG ALSI     → solo H1 (título principal y "Acerca de")
#   Nizzoli Alt → títulos secundarios H2 (secciones de panel, diálogos)
#   Poppins     → cuerpo (fuente base de toda la UI)
# ═══════════════════════════════════════════════════════════════════════════
FUENTES = {'h1': 'Segoe UI', 'h2': 'Segoe UI', 'body': 'Segoe UI'}

def cargar_fuentes_marca():
    """Registra las fuentes de fonts/ y guarda el nombre interno real de cada
    familia en FUENTES. Si falta algún archivo, cae en cascada al siguiente
    nivel (AG ALSI → Poppins → Segoe UI) sin romper el arranque."""
    from PyQt5.QtGui import QFontDatabase

    def cargar_familia(archivos, fallback):
        familia = None
        for nombre in archivos:
            ruta = resource_path(os.path.join("fonts", nombre))
            if os.path.exists(ruta):
                fid = QFontDatabase.addApplicationFont(ruta)
                if fid != -1:
                    familias = QFontDatabase.applicationFontFamilies(fid)
                    if familias and familia is None:
                        familia = familias[0]
            else:
                logger.warning(f"Fuente no encontrada: {ruta}")
        return familia if familia else fallback

    FUENTES['body'] = cargar_familia(
        ["Poppins-Regular.ttf", "Poppins-Medium.ttf",
         "Poppins-SemiBold.ttf", "Poppins-Bold.ttf"], "Segoe UI")
    FUENTES['h1'] = cargar_familia(["AG-ALSI.otf"], FUENTES['body'])
    FUENTES['h2'] = cargar_familia(
        ["Los Andes - Nizzoli Alt Regular.otf",
         "Los Andes - Nizzoli Alt SemiBold.otf",
         "Los Andes - Nizzoli Alt Bold.otf"], FUENTES['body'])
    logger.info(f"Fuentes de marca: H1='{FUENTES['h1']}' H2='{FUENTES['h2']}' Cuerpo='{FUENTES['body']}'")


def aplicar_h1(widget, size=17, color="#F5F5F5"):
    """Aplica la tipografía H1 (AG ALSI). Se usa stylesheet por-widget porque
    el font-family del QSS global pisaría un QFont programático."""
    widget.setStyleSheet(
        f'font-family: "{FUENTES["h1"]}"; font-size: {size}px; '
        f'font-weight: 800; color: {color}; background: transparent;')


def aplicar_h2(widget, size=11, color="#999999"):
    """Aplica la tipografía H2 (Nizzoli Alt) a títulos de sección."""
    widget.setStyleSheet(
        f'font-family: "{FUENTES["h2"]}"; font-size: {size}px; font-weight: 800; '
        f'letter-spacing: 1px; color: {color}; background: transparent;')


def svg_pixmap(nombre, color="#999999", size=18):
    """Renderiza icons/<nombre>.svg a QPixmap recoloreado (SPEC §6)."""
    from PyQt5.QtSvg import QSvgRenderer
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    ruta = resource_path(os.path.join("icons", f"{nombre}.svg"))
    if os.path.exists(ruta):
        renderer = QSvgRenderer(ruta)
        p = QPainter(pm)
        renderer.render(p)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(pm.rect(), QColor(color))
        p.end()
    else:
        logger.warning(f"Icono SVG no encontrado: {ruta}")
    return pm


def svg_icon(nombre, color="#999999", size=18):
    """QIcon desde SVG recoloreado. Reposo #999999, activo #E66C32, sobre naranja #FFFFFF."""
    return QIcon(svg_pixmap(nombre, color, size))


# Badges de extensión para placeholders de miniatura (SPEC §4)
COLORES_BADGE = {
    '.sldprt': '#E66C32', '.sldasm': '#3BA55D',
    '.slddrw': '#5B8DD9', '.dwg': '#5B8DD9',
    '.pdf': '#C75450',
    '.step': '#999999', '.stp': '#999999', '.iges': '#999999', '.igs': '#999999',
}
ETIQUETAS_BADGE = {
    '.sldprt': 'PRT', '.sldasm': 'ASM', '.slddrw': 'DRW', '.dwg': 'DWG',
    '.pdf': 'PDF', '.step': 'STEP', '.stp': 'STEP', '.iges': 'IGES', '.igs': 'IGES',
}


def pixmap_badge_extension(ext, size=56):
    """Placeholder cuadrado con la extensión (PRT/ASM/DRW/PDF...) coloreada por tipo."""
    color = QColor(COLORES_BADGE.get(ext, '#777777'))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    fondo = QColor(color)
    fondo.setAlpha(46)
    p.setBrush(fondo)
    p.setPen(QPen(color, 1.5))
    radio = max(4, size // 8)
    p.drawRoundedRect(1, 1, size - 2, size - 2, radio, radio)
    p.setPen(QPen(color))
    f = QFont(FUENTES['body'], max(7, size // 5))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, ETIQUETAS_BADGE.get(ext, ext.lstrip('.').upper()[:4]))
    p.end()
    return pm


# Ajustes de la app que el QSS del handoff no cubre (se concatenan al cargarlo)
QSS_EXTRAS = """
/* ---- Extras específicos de la app (V2.0.0) ---- */
/* __FONT_H2__ se sustituye en cargar_qss_marca() por el nombre real de Nizzoli Alt */
QLabel#PanelTitle { font-family: "__FONT_H2__"; }
QLabel, QCheckBox { background: transparent; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

QSplitter::handle { background-color: transparent; }
QSplitter::handle:hover { background-color: #E66C32; }

/* Con ::item estilizado, Qt requiere :alternate explícito (sin él usa la paleta clara) */
QTableWidget::item:alternate, QTableView::item:alternate { background-color: #1D1D1D; }

/* Cubrir la paleta Highlight (azul Fusion) en rutas de pintado con delegados */
QTableWidget, QTableView, QListWidget {
    selection-background-color: #3A2C21;
    selection-color: #F5F5F5;
}

/* Banner de actualización (V2.0.0): degradado de marca, discreto */
QFrame#UpdateBanner {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E66C32, stop:1 #BF5320);
    border: none;
}

/* Toggle Placa CE (V2.1.0): pastilla junto al buscador */
QPushButton#ToggleCE {
    background-color: #2E2E2E; border: 1.5px solid #4A4A4A; border-radius: 10px;
    padding: 8px 14px; color: #999999; font-weight: 700;
}
QPushButton#ToggleCE:hover { border-color: #E66C32; color: #DFDFDF; }
QPushButton#ToggleCE:checked {
    background-color: #3A2C21; border-color: #E66C32; color: #F0A377;
}

/* Segmented control por dynamic property (un widget solo admite un objectName) */
QPushButton[segmento="true"] {
    background-color: #2E2E2E; border: 1px solid #4A4A4A; border-radius: 0;
    padding: 6px 14px; color: #999999; font-weight: 700; font-size: 12px;
}
QPushButton[segmento="true"]:checked { background-color: #E66C32; color: #FFFFFF; border-color: #E66C32; }
QPushButton[segmento="true"]:hover:!checked { border-color: #E66C32; color: #DFDFDF; }
QPushButton[segPos="first"] { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton[segPos="last"]  { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }

/* Barra de contexto bajo el header (V2.0.1) */
QFrame#ContextBar { background-color: #242424; border-bottom: 1px solid #333333; }

/* Todos/Ninguno como enlaces de texto compactos (V2.0.1) */
QPushButton#btn_toggle {
    background: transparent; border: none; padding: 0 2px;
    font-size: 10px; font-weight: 700; color: #999999;
}
QPushButton#btn_toggle:hover { color: #E66C32; }
QPushButton#btn_cancelar { background-color: #8C3A32; border: none; color: #FFFFFF; }
QPushButton#btn_cancelar:hover { background-color: #A6443B; }

QFrame#panel_preview { background-color: #2E2E2E; border: 1px solid #3D3D3D; border-radius: 10px; }
/* Tarjeta lightbox de la miniatura en el preview (V2.0.1) */
QFrame#PreviewImage { background-color: #1D1D1D; border: 1px solid #3D3D3D; border-radius: 8px; }

QListWidget { background-color: #1D1D1D; border: 1px solid #3D3D3D; border-radius: 8px; outline: 0; }
QListWidget::item { padding: 3px 4px; border-radius: 4px; color: #DFDFDF; }
QListWidget::item:hover { background-color: #33291F; }
QListWidget::item:selected { background-color: #3A2C21; color: #F5F5F5; }
QListWidget::indicator {
    width: 14px; height: 14px; border: 1.5px solid #5A5A5A;
    border-radius: 4px; background: transparent;
}
QListWidget::indicator:checked {
    background-color: #E66C32; border-color: #E66C32; image: url(icons/check.svg);
}

QMenu { background-color: #2E2E2E; border: 1px solid #3D3D3D; border-radius: 8px; padding: 4px; color: #DFDFDF; }
QMenu::item { padding: 6px 24px; border-radius: 6px; }
QMenu::item:selected { background-color: #3A2C21; color: #F5F5F5; }
QMenu::separator { height: 1px; background: #3D3D3D; margin: 4px 8px; }
QMenu::indicator { width: 14px; height: 14px; border: 1.5px solid #5A5A5A; border-radius: 4px; margin-left: 6px; }
QMenu::indicator:checked { background-color: #E66C32; border-color: #E66C32; image: url(icons/check.svg); }

QGroupBox {
    background-color: #262626; border: 1px solid #3D3D3D; border-radius: 8px;
    margin-top: 10px; font-weight: 700; color: #DFDFDF;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #999999; }

QMessageBox { background-color: #2E2E2E; }
QTextBrowser { background-color: #1D1D1D; border: 1px solid #3D3D3D; border-radius: 8px; color: #DFDFDF; }
"""


def cargar_qss_marca():
    """Lee alsi_buscador.qss + extras, resolviendo url(icons/...) tanto en
    desarrollo como empaquetado con PyInstaller. Devuelve '' si falla."""
    ruta_qss = resource_path("alsi_buscador.qss")
    try:
        with open(ruta_qss, encoding="utf-8") as fh:
            qss = fh.read()
    except Exception as e:
        logger.error(f"No se pudo cargar el QSS de marca ({ruta_qss}): {e}")
        return ""
    qss += QSS_EXTRAS
    qss = qss.replace("__FONT_H2__", FUENTES['h2'])
    icons_dir = resource_path("icons").replace("\\", "/")
    # URL entre comillas: la ruta puede contener espacios ("OFITEC 4", "BÚSQUEDA PIEZAS")
    # y sin comillas el parser CSS de Qt falla ("Could not parse application stylesheet")
    qss = re.sub(r'url\(icons/([^)]+)\)', lambda m: f'url("{icons_dir}/{m.group(1)}")', qss)
    return qss


# QSS legacy V1.0.5 — se conserva solo como fallback si falta alsi_buscador.qss
MODERN_QSS = """
/* ============================================================
   ESTILOS MODERNOS (V1.0.5) - FLUENT / macOS Inspired
   ============================================================ */

/* 1. Base y Ventana Principal */
QMainWindow { background-color: #F5F7FA; }
QWidget { font-family: "Segoe UI", sans-serif; color: #2D3748; }

/* 2. Scrollbars (Más gruesos y claros para usabilidad) */
QScrollBar:vertical {
    border: none; background: #F1F5F9; width: 16px; margin: 0px;
}
QScrollBar::handle:vertical { background-color: #94A3B8; min-height: 30px; border-radius: 8px; }
QScrollBar::handle:vertical:hover { background-color: #64748B; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QScrollBar:horizontal {
    border: none; background: #F1F5F9; height: 16px; margin: 0px;
}
QScrollBar::handle:horizontal { background-color: #94A3B8; min-width: 30px; border-radius: 8px; }
QScrollBar::handle:horizontal:hover { background-color: #64748B; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }

/* Splitter (Para que sea evidente que se puede arrastrar el panel derecho) */
QSplitter::handle { background-color: transparent; }
QSplitter::handle:horizontal { width: 6px; }
QSplitter::handle:hover { background-color: #E15B1E; }
QSplitter::handle:pressed { background-color: #D35400; }

/* 3. Inputs (Barra de Búsqueda) */
QLineEdit {
    background-color: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 8px; padding: 8px 12px; font-size: 14px;
    selection-background-color: #E15B1E;
}
QLineEdit:focus { border: 2px solid #E15B1E; padding: 7px 11px; }
QLineEdit:hover:!focus { border: 1px solid #CBD5E1; }

/* 4. Botones Estándar */
QPushButton {
    background-color: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 6px; padding: 6px 14px; color: #4A5568; font-weight: 600;
}
QPushButton:hover { background-color: #F7FAFC; border: 1px solid #CBD5E1; color: #2D3748; }
QPushButton:pressed { background-color: #EDF2F7; }

QPushButton#btn_toggle { font-size: 11px; padding: 4px; border-radius: 4px; }

/* 5. Botón Primario (Buscar y Acciones) */
QPushButton#btn_buscar, QPushButton#btn_abrir_carpeta {
    background-color: #E15B1E; color: #FFFFFF; border: none; font-size: 14px; border-radius: 8px; font-weight: bold;
}
QPushButton#btn_buscar:hover, QPushButton#btn_abrir_carpeta:hover { background-color: #D35400; }
QPushButton#btn_buscar:pressed, QPushButton#btn_abrir_carpeta:pressed { background-color: #B34700; }
QPushButton:disabled { background-color: #E2E8F0; color: #A0AEC0; }

/* 6. Listas (Checkboxes laterales) */
QListWidget { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 4px; outline: none; }
QListWidget::item { border-radius: 2px; padding: 2px; }
QListWidget::item:hover { background-color: #F7FAFC; }
QListWidget::item:selected { background-color: #F1F5F9; color: #2D3748; }

/* 7. GroupBox (Contenedores) */
QGroupBox { font-weight: bold; color: #78858B; border: 1px solid #E2E8F0; border-radius: 8px; margin-top: 8px; background-color: #FFFFFF; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 4px; color: #E15B1E; background-color: #F5F7FA; }

/* 8. Tabla Principal */
QTableWidget {
    background-color: #FFFFFF; alternate-background-color: #FAFAFA;
    border: 1px solid #E2E8F0; border-radius: 8px; gridline-color: transparent;
    selection-background-color: rgba(225, 91, 30, 0.12); selection-color: #1A202C; outline: none;
}
QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid #F1F5F9; }
QTableWidget::item:focus { outline: none; border: none; }

QHeaderView { background-color: transparent; }
QHeaderView::section {
    background-color: #F8FAFC; color: #64748B; padding: 8px; border: none;
    border-right: 1px solid #E2E8F0; border-bottom: 2px solid #E2E8F0; font-weight: bold; font-size: 11px; text-transform: uppercase;
}
QHeaderView::section:hover { background-color: #F1F5F9; }

/* 9. Panel Visualizador Derecho (Card Flotante) */
#panel_preview { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; }
#panel_preview QLabel { color: #2D3748; }
#preview_title { font-size: 18px; font-weight: bold; color: #E15B1E; }

/* Separadores */
QFrame[frameShape="4"] { color: #E2E8F0; }

/* Checkboxes sueltos */
QCheckBox { spacing: 8px; color: #4A5568; font-weight: 500; }

/* Combobox y su Desplegable (Scroll controlado) */
QComboBox { border: 1px solid #E2E8F0; border-radius: 6px; padding: 5px; background: white; combobox-popup: 0; }
QComboBox:hover { border: 1px solid #CBD5E1; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: none; }
"""

# MOTOR DE BASE DE DATOS E INDEXACIÓN MOVIDOS A models.py Y controllers.py

# -----------------------------------------------------------------------------
# DIÁLOGO DE INDEXACIÓN SELECTIVA (Cambio 2)
# -----------------------------------------------------------------------------
class DialogIndexacion(QDialog):
    """Modal para elegir qué orígenes y años indexar (V2.0.0 - rediseño 3a).
    Orígenes como tarjetas #FilterCard y años como chips #Chip."""
    def __init__(self, rutas_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar Indexación NAS")
        self.setMinimumSize(480, 520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Cabecera ---
        header = QFrame()
        header.setObjectName("DialogHeader")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(2, 2, 2, 10)
        h_lay.setSpacing(10)
        icono_hdr = QLabel()
        icono_hdr.setPixmap(svg_pixmap("reindexar-refrescar", color="#E66C32", size=28))
        h_lay.addWidget(icono_hdr)
        titulos_lay = QVBoxLayout()
        titulos_lay.setSpacing(2)
        lbl_titulo = QLabel("Reindexar NAS")
        lbl_titulo.setObjectName("DialogTitle")
        lbl_titulo.setStyleSheet(
            f'font-family: "{FUENTES["h2"]}"; font-size: 16px; font-weight: 800; '
            f'color: #F5F5F5; background: transparent;')
        lbl_sub = QLabel("192.168.1.10 · Oficina Técnica")
        lbl_sub.setObjectName("DialogSub")
        titulos_lay.addWidget(lbl_titulo)
        titulos_lay.addWidget(lbl_sub)
        h_lay.addLayout(titulos_lay)
        h_lay.addStretch()
        layout.addWidget(header)

        # --- Orígenes como tarjetas ---
        lbl_origenes = QLabel("ORÍGENES")
        lbl_origenes.setObjectName("PanelTitle")
        layout.addWidget(lbl_origenes)

        self._checks_origen = {}  # key -> QCheckBox
        for key, ruta in rutas_dict.items():
            card = QFrame()
            card.setObjectName("FilterCard")
            c_lay = QHBoxLayout(card)
            c_lay.setContentsMargins(10, 8, 10, 8)
            chk = QCheckBox(ETIQUETAS_ORIGEN.get(key, key))
            chk.setChecked(True)
            chk.setCursor(Qt.PointingHandCursor)
            lbl_ruta = QLabel(ruta)
            lbl_ruta.setStyleSheet("color: #777777; font-size: 10px; background: transparent;")
            c_lay.addWidget(chk)
            c_lay.addStretch()
            c_lay.addWidget(lbl_ruta)
            self._checks_origen[key] = chk
            layout.addWidget(card)

        btn_comp_layout = QHBoxLayout()
        btn_todos = QPushButton("Todos")
        btn_todos.setCursor(Qt.PointingHandCursor)
        btn_todos.clicked.connect(lambda: self._toggle(self._checks_origen, True))
        btn_ninguno = QPushButton("Ninguno")
        btn_ninguno.setCursor(Qt.PointingHandCursor)
        btn_ninguno.clicked.connect(lambda: self._toggle(self._checks_origen, False))
        btn_comp_layout.addWidget(btn_todos)
        btn_comp_layout.addWidget(btn_ninguno)
        btn_comp_layout.addStretch()
        layout.addLayout(btn_comp_layout)

        # --- Años como chips ---
        lbl_anos_t = QLabel("AÑOS DE PROYECTO")
        lbl_anos_t.setObjectName("PanelTitle")
        layout.addWidget(lbl_anos_t)

        self._chips_años = {}  # "2026" -> QPushButton checkable
        chips_widget = QWidget()
        from PyQt5.QtWidgets import QGridLayout
        chips_grid = QGridLayout(chips_widget)
        chips_grid.setContentsMargins(0, 0, 0, 0)
        chips_grid.setSpacing(6)
        años_actuales = [str(a) for a in range(datetime.now().year, 2010, -1)]
        POR_FILA = 8
        for i, año in enumerate(años_actuales):
            chip = QPushButton(año)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.setCursor(Qt.PointingHandCursor)
            chips_grid.addWidget(chip, i // POR_FILA, i % POR_FILA)
            self._chips_años[año] = chip
        layout.addWidget(chips_widget)

        btn_años_layout = QHBoxLayout()
        btn_t_años = QPushButton("Todos")
        btn_t_años.setCursor(Qt.PointingHandCursor)
        btn_t_años.clicked.connect(lambda: self._toggle(self._chips_años, True))
        btn_n_años = QPushButton("Ninguno")
        btn_n_años.setCursor(Qt.PointingHandCursor)
        btn_n_años.clicked.connect(lambda: self._toggle(self._chips_años, False))
        btn_años_layout.addWidget(btn_t_años)
        btn_años_layout.addWidget(btn_n_años)
        btn_años_layout.addStretch()
        layout.addLayout(btn_años_layout)

        # --- Info ---
        lbl_info = QLabel("El proceso puede tardar varios minutos según el tamaño del NAS. "
                          "Puedes cancelar en cualquier momento; el índice anterior sigue disponible.")
        lbl_info.setStyleSheet("color: #999999; font-style: italic; padding: 4px; background: transparent;")
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)
        layout.addStretch()

        # --- Footer ---
        footer = QFrame()
        footer.setObjectName("DialogFooter")
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(2, 8, 2, 2)
        f_lay.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Iniciar Indexación")
        self.btn_ok.setIcon(svg_icon("reindexar-refrescar", color="#FFFFFF"))
        self.btn_ok.setObjectName("Primary")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self.accept)
        f_lay.addWidget(btn_cancel)
        f_lay.addWidget(self.btn_ok)
        layout.addWidget(footer)

    def _toggle(self, coleccion, state):
        """Marca/desmarca todos los checkables de un dict {clave: widget}."""
        for w in coleccion.values():
            w.setChecked(state)

    def get_selected_items(self, coleccion):
        """Devuelve las claves de los checkables marcados."""
        return [clave for clave, w in coleccion.items() if w.isChecked()]

    def get_companeros_seleccionados(self):
        # V2.0.0: devuelve las CLAVES de RUTAS_NAS (antes devolvía etiquetas,
        # que nunca coincidían con las claves en IndexadorThread — bug de master)
        return self.get_selected_items(self._checks_origen)

    def get_años_seleccionados(self):
        return self.get_selected_items(self._chips_años)
    


# -----------------------------------------------------------------------------
# TABLA CON DRAG & DROP (Cambio 5)
# -----------------------------------------------------------------------------
class TablaArrastrable(QTableWidget):
    """QTableWidget con drag habilitado para arrastrar archivos a SolidWorks y pan con botón central"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        
        # Panning manual con botón central
        self._pan_start = None
        self.viewport().installEventFilter(self)

    def eventFilter(self, source, event):
        if source is self.viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.MiddleButton:
                self._pan_start = event.pos()
                self.viewport().setCursor(Qt.ClosedHandCursor)
                return True
            elif event.type() == QEvent.MouseMove and self._pan_start is not None:
                delta = event.pos() - self._pan_start
                h_bar = self.horizontalScrollBar()
                v_bar = self.verticalScrollBar()
                h_bar.setValue(h_bar.value() + delta.x())
                v_bar.setValue(v_bar.value() + delta.y())
                self._pan_start = event.pos()
                return True
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.MiddleButton:
                self._pan_start = None
                self.viewport().unsetCursor()
                return True
        return super().eventFilter(source, event)
    
    def mimeData(self, items):
        """Genera mimeData con file:/// URI para drag & drop a SolidWorks"""
        mime = QMimeData()
        urls = []
        
        # Obtener las filas seleccionadas (sin duplicados)
        rows = set()
        for item in items:
            if item:
                rows.add(item.row())
        
        for row in rows:
            # Columna 0 = ruta completa
            ruta_item = self.item(row, 0)
            if ruta_item:
                ruta = ruta_item.text()
                if ruta:
                    # V2.0.1: reescribir al host accesible (IP/NASCENTRAL)
                    url = QUrl.fromLocalFile(ruta_accesible(ruta))
                    urls.append(url)

        if urls:
            mime.setUrls(urls)

        return mime
        
# -----------------------------------------------------------------------------
# VISTA GALERÍA (V2.0.0 - Tarjetas con drag & drop a SolidWorks)
# -----------------------------------------------------------------------------
class GaleriaArrastrable(QListWidget):
    """QListWidget en IconMode con el mismo drag & drop a SolidWorks que la tabla.
    La ruta completa de cada archivo viaja en Qt.UserRole."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Gallery")
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(10)
        self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        # V2.0.0: NO uniformItemSizes — cacheaba el tamaño del primer item y no
        # recalculaba la zona de texto al cambiar S/M/L (etiquetas invisibles hasta
        # forzar un M→L). Sin él, cada cambio de rejilla recompone bien el texto.
        self.zoom_callback = None  # V2.0.3: lo fija la ventana (Ctrl+rueda)

    def wheelEvent(self, event):
        """V2.0.3: Ctrl + rueda = zoom de las tarjetas (como en el Explorador)."""
        if event.modifiers() == Qt.ControlModifier and self.zoom_callback:
            self.zoom_callback(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def mimeData(self, items):
        """file:/// URLs para arrastrar a SolidWorks (idéntico a TablaArrastrable)."""
        mime = QMimeData()
        urls = []
        for item in items:
            ruta = item.data(Qt.UserRole)
            if ruta:
                urls.append(QUrl.fromLocalFile(ruta_accesible(ruta)))  # V2.0.1
        if urls:
            mime.setUrls(urls)
        return mime


class FiltrosJerarquicosWorker(QThread):
    """V2.3.1: Clientes y Proyectos, fuera del hilo de la interfaz.

    Estas dos consultas se hacian en el hilo de UI desde la V1.0.0, asi que
    cada clic en un filtro congelaba la ventana mientras duraban. Medido
    contra el servidor: 0,14 s los clientes y 0,51 s los proyectos cuando no
    hay ningun cliente marcado — que es justo como arranca la app.

    Devuelve tambien si la consulta salio bien: ante un fallo NO se tocan las
    listas, porque vaciarlas dejaria al usuario sin filtros por un corte de
    red pasajero."""
    listo = pyqtSignal(int, bool, list, list)   # generacion, ok, clientes, proyectos

    def __init__(self, generacion, controller, compañeros, años, clientes_marcados):
        super().__init__()
        self.generacion = generacion
        self.controller = controller
        self.compañeros = compañeros
        self.años = años
        self.clientes_marcados = clientes_marcados

    def run(self):
        try:
            clientes = self.controller.get_all_clients(
                companions=self.compañeros, years=self.años) or []
            # Solo pesan las marcas que siguen existiendo en el contexto nuevo,
            # igual que hacia la version sincrona al releer la lista tras
            # repoblarla.
            vivos = [c for c in self.clientes_marcados if c in clientes]
            proyectos = self.controller.get_all_projects(
                clientes=vivos or None,
                companions=self.compañeros or None,
                years=self.años or None) or []
            self.listo.emit(self.generacion, True, list(clientes), list(proyectos))
        except Exception as e:
            logger.warning("No se han podido refrescar Clientes y Proyectos: %s", e)
            self.listo.emit(self.generacion, False, [], [])


class PropsContextWorker(QThread):
    """V2.3.0: cascada de los filtros de propiedades SW — consulta en segundo
    plano qué valores de Material/Tratamiento/Espesor/Cierre existen en el
    contexto filtrado (origen/años/clientes/proyectos), igual que la cascada
    de Clientes y Proyectos pero sin tocar el hilo de UI. Lleva número de
    generación para descartar respuestas obsoletas."""
    listo = pyqtSignal(int, dict)  # generacion, {'materiales': set, ...}

    def __init__(self, generacion, controller, kwargs):
        super().__init__()
        self.generacion = generacion
        self.controller = controller
        self.kwargs = kwargs

    def run(self):
        try:
            data = self.controller.get_propiedades_contexto(**self.kwargs)
        except Exception as e:
            logger.debug(f"PropsContextWorker falló: {e}")
            data = {}
        self.listo.emit(self.generacion, data)


# -----------------------------------------------------------------------------
# LISTA DE ARCHIVOS DE DIÁLOGO (V2.0.5 - arrastrable a SolidWorks)
# -----------------------------------------------------------------------------
class ListaArrastrable(QListWidget):
    """Lista de archivos de los diálogos (¿dónde se usa?, despiece, similares…)
    con las mismas posibilidades que la tabla principal: arrastrar a SolidWorks
    para insertar el componente, y selección múltiple para arrastrar varios.

    La ruta completa de cada archivo viaja en Qt.UserRole, igual que en la
    galería. Se reescribe al host accesible (IP/NASCENTRAL) al soltar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

    def rutas_seleccionadas(self):
        """Rutas (canónicas) de lo seleccionado, sin huecos ni duplicados."""
        vistas, rutas = set(), []
        for it in self.selectedItems():
            r = it.data(Qt.UserRole)
            if r and r not in vistas:
                vistas.add(r)
                rutas.append(r)
        return rutas

    def mimeData(self, items):
        mime = QMimeData()
        urls = []
        for item in items:
            ruta = item.data(Qt.UserRole)
            if ruta:
                urls.append(QUrl.fromLocalFile(ruta_accesible(ruta)))
        if urls:
            mime.setUrls(urls)
        return mime


class VistaPreviaFlotante(QWidget):
    """Ventanita flotante con la vista previa grande al pasar el ratón por
    encima de una miniatura (V2.0.6), al estilo del Pack&Go de SolidWorks.

    Es una ventana sin marco (tipo tooltip): no roba el foco ni interrumpe lo
    que estés haciendo. Se coloca al lado del cursor y se aparta sola si no
    cabe en la pantalla."""

    LADO = 320          # lado máximo de la imagen
    MARGEN = 8

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.lbl_img = QLabel()
        self.lbl_img.setAlignment(Qt.AlignCenter)
        self.lbl_img.setStyleSheet("background: #FFFFFF; padding: 6px;")
        self.lbl_txt = QLabel()
        self.lbl_txt.setAlignment(Qt.AlignCenter)
        self.lbl_txt.setWordWrap(True)
        self.lbl_txt.setStyleSheet(
            "background: #2E2E2E; color: #DFDFDF; font-size: 11px; padding: 5px 8px;")
        lay.addWidget(self.lbl_img)
        lay.addWidget(self.lbl_txt)
        self.setStyleSheet("VistaPreviaFlotante { background: #E66C32; }")  # borde naranja

    def mostrar(self, pixmap, texto, pos_global):
        if pixmap is None or pixmap.isNull():
            return
        pm = pixmap.scaled(self.LADO, self.LADO, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lbl_img.setPixmap(pm)
        self.lbl_img.setFixedSize(pm.width() + 12, pm.height() + 12)
        self.lbl_txt.setText(texto or "")
        self.lbl_txt.setVisible(bool(texto))
        self.adjustSize()
        self.move(self._sitio(pos_global))
        self.show()
        self.raise_()

    def _sitio(self, pos):
        """Debajo-derecha del cursor, pero sin salirse de la pantalla."""
        pantalla = QApplication.desktop().availableGeometry(pos)
        x = pos.x() + 18
        y = pos.y() + 18
        if x + self.width() > pantalla.right():
            x = pos.x() - self.width() - 18
        if y + self.height() > pantalla.bottom():
            y = pos.y() - self.height() - 18
        x = max(pantalla.left(), x)
        y = max(pantalla.top(), y)
        return QPoint(x, y)


class HoverPreview(QObject):
    """Engancha la vista previa flotante a una tabla o lista (V2.0.6).

    Funciona con cualquier vista (rejilla principal, galería y los diálogos):
    solo hay que decirle cómo sacar la ruta de un índice. Las imágenes salen
    de la caché de la BD, nunca del NAS, y se guardan en memoria para que
    pasar el ratón arriba y abajo no repita consultas."""

    RETARDO_MS = 450    # tiempo parado sobre la fila antes de asomar

    def __init__(self, vista, ruta_de_indice, db, texto_de_indice=None, parent=None):
        super().__init__(parent or vista)
        self.vista = vista
        self.ruta_de_indice = ruta_de_indice
        self.texto_de_indice = texto_de_indice
        self.db = db
        self.popup = VistaPreviaFlotante(vista)
        self._cache = {}
        self._ruta_actual = None
        self._pos = QPoint()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.RETARDO_MS)
        self.timer.timeout.connect(self._asomar)
        vista.setMouseTracking(True)
        vista.viewport().setMouseTracking(True)
        vista.viewport().installEventFilter(self)
        vista.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseMove:
            if ev.buttons() != Qt.NoButton:      # arrastrando: fuera
                self.ocultar()
            else:
                self._sobre(ev.globalPos(), ev.pos())
        elif t in (QEvent.Leave, QEvent.Wheel, QEvent.MouseButtonPress,
                   QEvent.FocusOut, QEvent.Hide, QEvent.WindowDeactivate):
            self.ocultar()
        return False

    def _sobre(self, pos_global, pos_vista):
        try:
            idx = self.vista.indexAt(pos_vista)
        except Exception:
            return
        ruta = self.ruta_de_indice(idx) if idx.isValid() else None
        if not ruta:
            self.ocultar()
            return
        self._pos = pos_global
        if ruta != self._ruta_actual:
            self._ruta_actual = ruta
            self.popup.hide()
            self.timer.start()
        elif not self.popup.isVisible():
            self.timer.start()

    def _asomar(self):
        ruta = self._ruta_actual
        if not ruta:
            return
        # Si la miniatura ya se ve tan grande como la ventanita, no molestar
        # (galería en XL o con el deslizador alto)
        try:
            if self.vista.iconSize().width() >= self.popup.LADO * 0.9:
                return
        except Exception:
            pass
        pm = self._cache.get(ruta)
        if pm is None:
            pm = QPixmap()
            try:
                datos = self.db.obtener_miniatura(ruta)
                if datos:
                    img = QImage.fromData(datos)
                    if not img.isNull():
                        pm = QPixmap.fromImage(img)
            except Exception as e:
                logger.debug(f"Vista previa flotante falló para {ruta}: {e}")
            if len(self._cache) > 300:
                self._cache.clear()
            self._cache[ruta] = pm
        if not pm.isNull():
            self.popup.mostrar(pm, os.path.basename(ruta), self._pos)

    def ocultar(self):
        self.timer.stop()
        self._ruta_actual = None
        self.popup.hide()


class TablaDialogoArrastrable(QTableWidget):
    """Tabla de resultados de los diálogos (despiece, similares, comparar…)
    arrastrable a SolidWorks (V2.0.6).

    A diferencia de TablaArrastrable (rejilla principal, ruta en la columna 0
    como texto), aquí la ruta viaja en Qt.UserRole de la columna 0, que es la
    de la miniatura."""

    COL_RUTA = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

    def rutas_seleccionadas(self):
        vistas, rutas = set(), []
        for f in sorted({i.row() for i in self.selectedItems()}):
            it = self.item(f, self.COL_RUTA)
            r = it.data(Qt.UserRole) if it else None
            if r and r not in vistas:
                vistas.add(r)
                rutas.append(r)
        return rutas

    def mimeData(self, items):
        mime = QMimeData()
        urls = [QUrl.fromLocalFile(ruta_accesible(r)) for r in self.rutas_seleccionadas()]
        if urls:
            mime.setUrls(urls)
        return mime


# -----------------------------------------------------------------------------
# LISTA DE CASILLAS DE FILTRO (V2.0.5)
# -----------------------------------------------------------------------------
class ListaFiltro(QListWidget):
    """Lista de casillas de la barra lateral de filtros.

    Arregla dos quejas de la oficina técnica:

    1) ALTO DESIGUAL Y CORTO. Cada lista tenía su propio mínimo/máximo
       (100-140, 140-220, 160-300, 120-240, 120-260...) y, al no caber todo
       en la barra lateral, el layout las encogía a su MÍNIMO: unas mostraban
       4 casillas y otras 5. Ahora el alto se fija (mínimo == máximo) a un
       número exacto de casillas, medido en tiempo de ejecución sobre la
       fuente y el estilo reales, así que todas enseñan las mismas.

    2) RUEDA DEL RATÓN DEMASIADO BRUSCA. Qt desplaza 3 filas por muesca; con
       5 casillas a la vista, un golpe de rueda se llevaba media lista. Aquí
       se desplaza de FILAS_POR_MUESCA en FILAS_POR_MUESCA y en píxeles, así
       que el movimiento es fino y predecible. Cuando la lista ya está al
       tope, el evento se cede al panel para que siga bajando la barra
       lateral entera (comportamiento natural de siempre).

    Además se quita la barra horizontal: los nombres largos se recortan con
    puntos suspensivos y el texto completo queda en el tooltip. Así el alto
    no baila según haya o no barra inferior.
    """

    FILAS_VISIBLES = 6      # tope de casillas a la vista (igual en todas)
    FILAS_POR_MUESCA = 2    # avance por muesca de rueda (Qt trae 3)

    def __init__(self, parent=None, ajustar_a_contenido=False):
        """ajustar_a_contenido: para listas CORTAS y de contenido fijo (ORIGEN
        tiene 3 casillas, CIERRE 5). Se quedan en su número real en vez de
        dejar filas en blanco hasta 6. No usarlo en listas que se rellenan
        desde la base de datos (clientes, proyectos, material): al filtrar en
        cascada cambian de tamaño y el panel daría saltos."""
        super().__init__(parent)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self._ajustar_a_contenido = ajustar_a_contenido
        self._alto_aplicado = 0
        self._resto_rueda = 0
        self._fijar_alto()

    # --- alto uniforme -------------------------------------------------
    def _filas_a_mostrar(self):
        if self._ajustar_a_contenido and self.count():
            return min(self.count(), self.FILAS_VISIBLES)
        return self.FILAS_VISIBLES

    def _alto_fila(self):
        """Alto real de una casilla. Si la lista aún está vacía (clientes y
        proyectos se rellenan después) se mide con una casilla de sonda."""
        alto = self.sizeHintForRow(0)
        if alto <= 0:
            sonda = QListWidgetItem("Ag")
            sonda.setFlags(sonda.flags() | Qt.ItemIsUserCheckable)
            sonda.setCheckState(Qt.Unchecked)
            QListWidget.addItem(self, sonda)
            alto = self.sizeHintForRow(0)
            self.takeItem(self.row(sonda))
        return alto if alto > 0 else self.fontMetrics().height() + 8

    def _fijar_alto(self):
        alto = self._alto_fila() * self._filas_a_mostrar() + 2 * self.frameWidth() + 2
        if alto != self._alto_aplicado:
            self._alto_aplicado = alto
            self.setMinimumHeight(alto)
            self.setMaximumHeight(alto)

    def showEvent(self, event):
        """Se remide al mostrarse: aquí la hoja de estilo ya está aplicada y
        el alto de fila es el definitivo."""
        super().showEvent(event)
        self._fijar_alto()

    def addItem(self, item):
        """Tooltip automático con el texto completo (la barra horizontal está
        desactivada y los nombres largos salen recortados)."""
        if isinstance(item, QListWidgetItem) and not item.toolTip():
            item.setToolTip(item.text())
        super().addItem(item)
        if self._ajustar_a_contenido and self.count() <= self.FILAS_VISIBLES:
            self._fijar_alto()   # crece con el contenido hasta el tope

    # --- rueda del ratón -----------------------------------------------
    def wheelEvent(self, event):
        barra = self.verticalScrollBar()
        if barra.maximum() <= 0:
            event.ignore()      # nada que desplazar: que lo mueva la barra lateral
            return
        self._resto_rueda += event.angleDelta().y()
        muescas = int(self._resto_rueda / 120)   # ratones de precisión mandan <120
        if muescas:
            self._resto_rueda -= muescas * 120
            paso = self._alto_fila() * self.FILAS_POR_MUESCA
            barra.setValue(barra.value() - muescas * paso)
        event.accept()


# -----------------------------------------------------------------------------
# SECCIÓN ACORDEÓN (V2.0.1 - Sidebar única de filtros)
# -----------------------------------------------------------------------------
class SeccionAcordeon(QFrame):
    """Grupo de filtro colapsable: cabecera clicable con icono + chevron
    y un contenido que se muestra/oculta. Añadir widgets via self.lay."""
    def __init__(self, titulo, icono=None, expandido=True, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterCard")
        self.titulo = titulo
        self.icono = icono
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(4)

        self._activo = False  # V2.0.0: True si hay filtros activos dentro
        self.btn_header = QPushButton(f" {titulo}  ▾")
        if icono:
            self.btn_header.setIcon(svg_icon(icono, size=14))
        self.btn_header.setCheckable(True)
        self.btn_header.setChecked(expandido)
        self.btn_header.setCursor(Qt.PointingHandCursor)
        self._aplicar_estilo_header()

        self.contenido = QWidget()
        self.lay = QVBoxLayout(self.contenido)
        self.lay.setContentsMargins(2, 0, 2, 0)
        self.lay.setSpacing(4)

        self.btn_header.toggled.connect(self._on_toggle)
        v.addWidget(self.btn_header)
        v.addWidget(self.contenido)
        self._on_toggle(expandido)

    def _aplicar_estilo_header(self):
        color = "#E66C32" if self._activo else "#DFDFDF"
        self.btn_header.setStyleSheet(
            f'QPushButton {{ background: transparent; border: none; text-align: left; '
            f'font-family: "{FUENTES["h2"]}"; font-size: 11px; font-weight: 800; '
            f'letter-spacing: 1px; color: {color}; padding: 4px 2px; }} '
            f'QPushButton:hover {{ color: #E66C32; }}')

    def set_activo(self, activo):
        """Marca visualmente que la sección tiene filtros aplicados: punto naranja,
        icono y título en color de marca (V2.0.0)."""
        activo = bool(activo)
        if activo == self._activo:
            return
        self._activo = activo
        if self.icono:
            self.btn_header.setIcon(svg_icon(self.icono, "#E66C32" if activo else "#999999", 14))
        self._aplicar_estilo_header()
        self._on_toggle(self.btn_header.isChecked())

    def _on_toggle(self, abierto):
        self.contenido.setVisible(abierto)
        flecha = "▾" if abierto else "▸"
        punto = " ●" if self._activo else ""
        self.btn_header.setText(f" {self.titulo}{punto}  {flecha}")


# -----------------------------------------------------------------------------
# LABEL DE IMAGEN AUTO-CONTENIDA (V2.0.1)
# -----------------------------------------------------------------------------
class PreviewImagenLabel(QLabel):
    """QLabel que pinta su imagen en el propio paintEvent, escalada al rect
    actual (KeepAspectRatio) y sin ampliar más allá del tamaño original.
    Al pintar dentro de contentsRect() es IMPOSIBLE que desborde el contenedor,
    sea cual sea el DPI del monitor o el timing de carga de la miniatura."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = None
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(1, 1)

    def set_imagen(self, pixmap):
        self._pm = pixmap
        self.update()

    def setPixmap(self, pixmap):
        # Compatibilidad: cualquier setPixmap externo pasa por el pintado contenido
        self.set_imagen(pixmap)

    def paintEvent(self, event):
        if self._pm is None or self._pm.isNull():
            return super().paintEvent(event)
        r = self.contentsRect()
        # Escalar para caber en el rect (KeepAspectRatio). V2.0.3: se permite
        # AMPLIAR hasta 2.5x el original — así al ensanchar el panel la vista
        # previa crece de verdad; el tope evita el pixelado feo cuando la
        # miniatura cacheada es pequeña (256px).
        MAX_AMPLIACION = 2.5
        destino = self._pm.size().scaled(r.size(), Qt.KeepAspectRatio)
        tope_w = int(self._pm.width() * MAX_AMPLIACION)
        tope_h = int(self._pm.height() * MAX_AMPLIACION)
        destino.setWidth(min(destino.width(), tope_w))
        destino.setHeight(min(destino.height(), tope_h))
        escalado = self._pm.scaled(destino, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = r.x() + (r.width() - escalado.width()) // 2
        y = r.y() + (r.height() - escalado.height()) // 2
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(x, y, escalado)
        p.end()


# -----------------------------------------------------------------------------
# THUMBNAIL WORKER (V1.0.3 - Extracción asíncrona)
# -----------------------------------------------------------------------------
class ThumbnailWorker(QThread):
    # row, ruta, image (QImage), hbitmap (int)
    thumbnail_ready = pyqtSignal(int, str, object, int)

    LOTE_BD = 400  # miniaturas de BD por consulta

    def __init__(self, vistas_pendientes, method_extractor, db=None):
        super().__init__()
        self.vistas_pendientes = vistas_pendientes # list of (row, ruta)
        self.method_extractor = method_extractor
        self.db = db  # V2.0.3: caché de BD por LOTES (rápido) antes del extractor
        self._cancelar = False

    def cancelar(self):
        self._cancelar = True

    def run(self):
        # Inicializa COM en este hilo para IShellItemImageFactory
        pythoncom.CoInitialize()
        try:
            pendientes = list(self.vistas_pendientes)

            # FASE 1 (V2.0.3): resolver por LOTES contra la caché de BD — una
            # consulta por cada 400 filas en vez de una por fila. La inmensa
            # mayoría sale de aquí en decisegundos, sin tocar el NAS.
            restantes = []
            if self.db is not None:
                for i in range(0, len(pendientes), self.LOTE_BD):
                    if self._cancelar:
                        return
                    chunk = pendientes[i:i + self.LOTE_BD]
                    try:
                        lote = self.db.obtener_miniaturas_lote([r for _, r in chunk])
                    except Exception as e:
                        logger.debug(f"Lote de miniaturas BD falló: {e}")
                        lote = {}
                    for row, ruta in chunk:
                        if self._cancelar:
                            return
                        data = lote.get(ruta)
                        if data:
                            image = QImage.fromData(data)
                            if not image.isNull():
                                self.thumbnail_ready.emit(row, ruta, image, 0)
                                continue
                        restantes.append((row, ruta))
            else:
                restantes = pendientes

            # FASE 2: misses de caché → extracción clásica (shell/embebido/NAS)
            for row, ruta in restantes:
                if self._cancelar:
                    break
                try:
                    image, hbitmap = self.method_extractor(ruta, size=128)
                    if image is not None or hbitmap != 0:
                        self.thumbnail_ready.emit(row, ruta, image, hbitmap)
                except Exception as e:
                    logger.debug(f"Error procesando miniatura en hilo para {ruta}: {e}")
        finally:
            pythoncom.CoUninitialize()


class PreviewWorker(QThread):
    """V2.0.3: el trabajo pesado del previsualizador (os.path.exists/getsize en
    el NAS + render 1024px) corre fuera del hilo de UI. Antes clicar una pieza
    congelaba la interfaz 1-2s. El preview muestra al instante la miniatura de
    BD y este worker la mejora a alta calidad cuando llega."""
    resultado = pyqtSignal(int, str, str, object, int)  # gen, ruta, tam_txt, QImage, hbitmap

    def __init__(self, generacion, ruta, extractor):
        super().__init__()
        self.generacion = generacion
        self.ruta = ruta
        self.extractor = extractor

    def run(self):
        pythoncom.CoInitialize()
        try:
            ruta_local = ruta_accesible(self.ruta)
            if not ruta_local or not os.path.exists(ruta_local):
                self.resultado.emit(self.generacion, self.ruta, "No accesible", None, 0)
                return
            size = os.path.getsize(ruta_local)
            if size < 1024:
                tam = f"{size} B"
            elif size < 1024 * 1024:
                tam = f"{size / 1024:.1f} KB"
            else:
                tam = f"{size / (1024 * 1024):.1f} MB"
            image, hbitmap = self.extractor(self.ruta, size=1024)
            self.resultado.emit(self.generacion, self.ruta, tam, image, hbitmap)
        except Exception as e:
            logger.debug(f"PreviewWorker falló para {self.ruta}: {e}")
            self.resultado.emit(self.generacion, self.ruta, "—", None, 0)
        finally:
            pythoncom.CoUninitialize()


class SearchWorker(QThread):
    """V2.0.3: la consulta SQL corre fuera del hilo de UI — la app nunca se
    congela buscando (Placa CE, filtros pesados, etc.). Cada búsqueda lleva un
    número de generación: si el usuario encadena clics, las respuestas viejas
    se descartan al llegar.
    modo='contiene' busca ENSAMBLAJES que lleven la pieza escrita."""
    listo = pyqtSignal(int, list)   # generacion, resultados
    fallo = pyqtSignal(int, str)    # generacion, mensaje

    def __init__(self, generacion, controller, args, kwargs, modo='nombre',
                 db=None, contiene_kwargs=None):
        super().__init__()
        self.generacion = generacion
        self.controller = controller
        self.args = args
        self.kwargs = kwargs
        self.modo = modo
        self.db = db
        self.contiene_kwargs = contiene_kwargs or {}

    def run(self):
        try:
            if self.modo == 'contiene':
                resultados = self.db.buscar_ensamblajes_que_contienen(**self.contiene_kwargs)
            else:
                resultados = self.controller.perform_search(*self.args, **self.kwargs)
            self.listo.emit(self.generacion, resultados or [])
        except Exception as e:
            self.fallo.emit(self.generacion, str(e))


# -----------------------------------------------------------------------------
# TOAST NOTIFICATION WIDGET (V1.0.8)
# -----------------------------------------------------------------------------
class ToastNotification(QWidget):
    def __init__(self, parent=None, text=""):
        super().__init__(parent)
        self.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(15, 10, 15, 10)
        
        self.label = QLabel(text)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                font-weight: bold;
                background-color: rgba(40, 44, 52, 230);
                padding: 8px 16px;
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 50);
            }
        """)
        self.layout.addWidget(self.label)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

        # V2.0.1: oculto hasta que haya un mensaje. Sin esto, el toast vacío se
        # renderizaba en (0,0) sobre el logo como un recuadro oscuro con borde.
        self.hide()

    def show_message(self, text, duration=2000):
        self.label.setText(text)
        self.adjustSize()
        
        # Position at bottom center of parent
        if self.parent():
            parent_rect = self.parent().rect()
            x = parent_rect.width() // 2 - self.width() // 2
            y = parent_rect.height() - self.height() - 40
            self.move(x, y)
            
        self.show()
        self.timer.start(duration)

class PillDelegate(QStyledItemDelegate):
    """Pinta el valor de la celda como píldora coloreada (columna Tipo, V2.0.0).
    Solo afecta al pintado: la ordenación y el texto del item quedan intactos."""
    COLORES = {
        'MECANICA': '#E66C32', 'LAYOUT': '#5B8DD9', 'LISTADOS': '#3BA55D',
        'OFERTAS Y PEDIDOS': '#C7A23F', 'PLIEGO DE CONDICIONES': '#9B6DD6',
        'BIBLIOTECA': '#3BA55D', 'ESTANDAR': '#999999', 'COMERCIAL': '#999999',
        'OTRO': '#777777', 'OTROS': '#777777',
    }

    def paint(self, painter, option, index):
        texto = index.data() or ""
        # Fondo de fila (hover/selección) con el estilo base, sin texto
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        estilo = opt.widget.style() if opt.widget else QApplication.style()
        estilo.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        if not texto:
            return
        color = QColor(self.COLORES.get(texto, '#999999'))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        f = painter.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        f.setBold(True)
        painter.setFont(f)
        fm = painter.fontMetrics()
        texto_corto = texto if len(texto) <= 14 else texto[:12] + '…'
        w = fm.horizontalAdvance(texto_corto) + 16
        h = fm.height() + 4
        r = option.rect
        rect_pill = QRect(r.x() + 6, r.y() + (r.height() - h) // 2, min(w, r.width() - 12), h)
        fondo = QColor(color)
        fondo.setAlpha(40)
        painter.setBrush(fondo)
        painter.setPen(QPen(color, 1))
        painter.drawRoundedRect(rect_pill, h // 2, h // 2)
        painter.setPen(QPen(color))
        painter.drawText(rect_pill, Qt.AlignCenter, texto_corto)
        painter.restore()


class FabricacionDelegate(QStyledItemDelegate):
    """Pinta ✓ naranja (valor presente) o · atenuado (vacío) en las columnas
    de fabricación L/T/F/S/P/M. El texto real del item ("SÍ"/"") se conserva
    para ordenación y exportación (V2.0.0)."""

    def paint(self, painter, option, index):
        texto = (index.data() or "").strip()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        estilo = opt.widget.style() if opt.widget else QApplication.style()
        estilo.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        f = painter.font()
        f.setBold(True)
        painter.setFont(f)
        if texto:
            painter.setPen(QPen(QColor("#E66C32")))
            painter.drawText(option.rect, Qt.AlignCenter, "✓")
        else:
            painter.setPen(QPen(QColor("#777777")))
            painter.drawText(option.rect, Qt.AlignCenter, "·")
        painter.restore()


# -----------------------------------------------------------------------------
# INTERFAZ PRINCIPAL
# -----------------------------------------------------------------------------
def generar_diagnostico():
    """Informe de estado del equipo (V2.1.0).

    Nace de la incidencia de Pablo y Marcos: "no me abre" no es un dato con el
    que se pueda trabajar. Esto comprueba, con tope de tiempo, TODO lo que la
    app necesita para arrancar y devuelve un texto que se pega en un mensaje.
    Funciona tambien sin interfaz (BuscadorPiezas.exe --diagnostico)."""
    import socket, getpass, platform, shutil
    L = []
    def add(k, v):
        L.append("%-26s %s" % (k + ":", v))

    add("Version de la app", APP_VERSION)
    add("Equipo / usuario", "%s / %s" % (platform.node(), getpass.getuser()))
    add("Windows", platform.platform())
    add("Ejecutable", sys.executable if getattr(sys, 'frozen', False) else "(desde codigo)")
    add("Carpeta de trabajo", os.getcwd())

    L.append("")
    L.append("--- Base de datos ---")
    add("Servidor", "%s:%s" % (PG_CONFIG.get('host'), PG_CONFIG.get('port')))
    add("Base / usuario", "%s / %s" % (PG_CONFIG.get('dbname'), PG_CONFIG.get('user')))
    add("Tiempo de espera", "%ss" % PG_CONFIG.get('connect_timeout'))
    t0 = time.time()
    try:
        with socket.create_connection((PG_CONFIG['host'], int(PG_CONFIG['port'])), 5):
            add("Puerto TCP", "ABIERTO (%.1fs)" % (time.time() - t0))
    except Exception as e:
        add("Puerto TCP", "CERRADO/INACCESIBLE tras %.1fs -> %s" % (time.time() - t0, e))
    t0 = time.time()
    try:
        import psycopg2
        c = psycopg2.connect(**PG_CONFIG)
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM buscador.archivos")
        n = cur.fetchone()[0]
        c.close()
        add("Consulta de prueba", "OK, %s archivos indexados (%.1fs)" % (n, time.time() - t0))
    except Exception as e:
        add("Consulta de prueba", "FALLA tras %.1fs -> %s" % (time.time() - t0,
                                                              str(e).splitlines()[0]))

    L.append("")
    L.append("--- NAS ---")
    primero_ok = None
    for host in NAS_HOSTS:
        t0 = time.time()
        ok = existe_con_limite(r"\\%s\Oficina Tecnica" % host, 5.0)
        add("  " + host, ("accesible" if ok else "NO responde") + " (%.1fs)" % (time.time() - t0))
        if ok and primero_ok is None:
            primero_ok = host
    add("Host en uso", NAS_HOST_ACTIVO or primero_ok or "NINGUNO RESPONDE")

    L.append("")
    L.append("--- Version desplegada ---")
    try:
        vf = os.path.join(RUTA_DESPLIEGUE_APP, "version.txt")
        if existe_con_limite(vf, 5.0):
            with open(vf, encoding="utf-8", errors="ignore") as f:
                add("En la carpeta de red", f.read().strip())
        else:
            add("En la carpeta de red", "no se llega a la carpeta")
    except Exception as e:
        add("En la carpeta de red", "error: %s" % e)

    L.append("")
    L.append("--- Disco y temporales ---")
    try:
        tmp = os.environ.get("TEMP", "")
        prueba = os.path.join(tmp, "alsi_prueba.tmp")
        with open(prueba, "w") as f:
            f.write("x")
        os.remove(prueba)
        add("TEMP escribible", "SI (%s)" % tmp)
    except Exception as e:
        add("TEMP escribible", "NO -> %s" % e)
    try:
        libre = shutil.disk_usage(os.path.expanduser("~")).free / (1024 ** 3)
        add("Espacio libre", "%.1f GB" % libre)
    except Exception:
        pass
    add("Log", "%s (%s KB)" % (RUTA_LOG,
                               os.path.getsize(RUTA_LOG) // 1024
                               if os.path.exists(RUTA_LOG) else 0))

    L.append("")
    L.append("--- Ultimos errores del log ---")
    try:
        with open(RUTA_LOG, encoding="utf-8", errors="ignore") as f:
            # se descarta el ruido de Qt: no dice nada del problema real
            malas = [l.rstrip() for l in f
                     if (" - ERROR - " in l or " - WARNING - " in l)
                     and " - Qt: " not in l]
        L.extend(malas[-8:] or ["(ninguno)"])
    except Exception:
        L.append("(no se ha podido leer el log)")

    return chr(10).join(L)


def informe_de_error(titulo, mensaje, detalle=None, ultimas_lineas=30):
    """Arma el texto que un companero puede pegar en un mensaje (V2.1.1).

    Lleva version, equipo, hora, el error y el final del log. La idea es que
    nadie tenga que explicar "me ha dado un error": pega esto y ya esta todo.
    """
    import getpass, platform
    partes = ["===== Buscador de Piezas ALSI - informe de error =====",
              "Version:  %s" % APP_VERSION,
              "Equipo:   %s / %s" % (platform.node(), getpass.getuser()),
              "Fecha:    %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
              "Titulo:   %s" % titulo,
              "",
              "--- Mensaje ---", str(mensaje)]
    if detalle:
        partes += ["", "--- Detalle tecnico ---", str(detalle)]
    partes += ["", "--- Ultimas lineas del registro ---"]
    try:
        with open(RUTA_LOG, encoding="utf-8", errors="ignore") as f:
            lineas = [l.rstrip() for l in f]
        partes += [l for l in lineas[-ultimas_lineas:] if " - Qt: " not in l]
    except Exception as e:
        partes.append("(no se ha podido leer el registro: %s)" % e)
    partes += ["", "Registro completo en: %s" % RUTA_LOG,
               "====================================================="]
    return chr(10).join(partes)


class DialogoError(QDialog):
    """Aviso de error CON boton de copiar (V2.1.1).

    Peticion de la oficina: que cuando salga un error se pueda mandar tal cual,
    sin capturas de pantalla ni transcribir nada a mano."""

    def __init__(self, titulo, mensaje, detalle=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(660, 430)
        self._informe = informe_de_error(titulo, mensaje, detalle)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        cab = QLabel(titulo)
        cab.setStyleSheet("font-size: 15px; font-weight: 800; color: #F5F5F5; "
                          "background: transparent;")
        cab.setWordWrap(True)
        lay.addWidget(cab)

        cuerpo = QLabel(str(mensaje))
        cuerpo.setWordWrap(True)
        cuerpo.setStyleSheet("color: #DFDFDF; background: transparent;")
        lay.addWidget(cuerpo)

        pista = QLabel("Pulsa «Copiar para enviar» y pega el resultado en un "
                       "mensaje: lleva la versión, el equipo y el registro.")
        pista.setObjectName("StatusDim")
        pista.setWordWrap(True)
        lay.addWidget(pista)

        self.txt = QTextBrowser()
        self.txt.setPlainText(self._informe)
        self.txt.setStyleSheet("font-family: Consolas, 'Courier New', monospace; "
                               "font-size: 11px;")
        lay.addWidget(self.txt, stretch=1)

        pie = QHBoxLayout()
        btn_copiar = QPushButton("Copiar para enviar")
        btn_copiar.setCursor(Qt.PointingHandCursor)
        btn_copiar.setStyleSheet(
            "QPushButton { background: #E66C32; color: #FFFFFF; border: none; "
            "border-radius: 6px; padding: 7px 16px; font-weight: 800; } "
            "QPushButton:hover { background: #F07C45; }")
        btn_copiar.clicked.connect(self._copiar)
        pie.addWidget(btn_copiar)
        self.lbl_copiado = QLabel("")
        self.lbl_copiado.setStyleSheet("color: #7BC67B; background: transparent;")
        pie.addWidget(self.lbl_copiado)
        pie.addStretch()
        btn_carpeta = QPushButton("Abrir carpeta del registro")
        btn_carpeta.setCursor(Qt.PointingHandCursor)
        btn_carpeta.clicked.connect(
            lambda: subprocess.Popen('explorer /select,"%s"' % RUTA_LOG))
        pie.addWidget(btn_carpeta)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.clicked.connect(self.accept)
        pie.addWidget(btn_cerrar)
        lay.addLayout(pie)

    def _copiar(self):
        QApplication.clipboard().setText(self._informe)
        self.lbl_copiado.setText("Copiado - ya puedes pegarlo en el mensaje")
        logger.info("Informe de error copiado al portapapeles por el usuario")


def avisar_atencion(padre, titulo, mensaje):
    """Aviso normal (no es un error) que respeta el modo desatendido (V2.1.1).

    Un QMessageBox modal en un arranque automatico o en un pase nocturno deja
    el proceso esperando un clic que nadie va a dar. Misma leccion que en la
    V2.0.8 con los scripts de noche."""
    logger.info("AVISO | %s | %s", titulo, str(mensaje).replace(chr(10), " / "))
    if os.environ.get("ALSI_SIN_DIALOGOS"):
        return
    try:
        QMessageBox.warning(padre, titulo, mensaje)
    except Exception as e:
        logger.warning("No se ha podido mostrar el aviso: %s", e)


def mostrar_error(titulo, mensaje, detalle=None, parent=None):
    """Punto UNICO para ensenar un error al usuario (V2.1.1).

    Siempre deja el error en el registro y, si hay interfaz, abre el dialogo
    con el boton de copiar. Sin interfaz (o en modo desatendido) se limita al
    registro, para no bloquear un proceso esperando un clic."""
    logger.error("ERROR MOSTRADO | %s | %s", titulo,
                 str(mensaje).replace(chr(10), " / "))
    if detalle:
        logger.error("Detalle: %s", str(detalle).replace(chr(10), " / "))
    if os.environ.get("ALSI_SIN_DIALOGOS"):
        return
    try:
        if QApplication.instance() is not None:
            DialogoError(titulo, mensaje, detalle, parent).exec_()
            return
    except Exception as e:
        logger.error("No se ha podido abrir el dialogo de error: %s", e)
    avisar_usuario(titulo, "%s\n\nDetalle en:\n%s" % (mensaje, RUTA_LOG))


class ConexionWorker(QThread):
    """Intenta conectar con PostgreSQL sin congelar la ventana (V2.1.0).

    El intento tarda hasta connect_timeout segundos. Hacerlo en el hilo de la
    interfaz dejaba la ventana tiesa en cada reintento; ahora la ventana sigue
    viva y solo cambia el mensaje."""
    resultado = pyqtSignal(bool, str)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

    def run(self):
        try:
            ok, motivo = self.db.reconectar()
        except Exception as e:
            ok, motivo = False, str(e)
        self.resultado.emit(ok, motivo)


class DiagnosticoWorker(QThread):
    """Genera el informe en segundo plano: las comprobaciones de red tardan
    hasta unos segundos y no deben congelar la ventana (V2.1.0)."""
    listo = pyqtSignal(str)

    def run(self):
        try:
            self.listo.emit(generar_diagnostico())
        except Exception as e:
            self.listo.emit("El diagnostico ha fallado: %s" % e)


class Fase:
    """Cronometro de las fases de arranque (V2.1.0).

    Cada paso deja en el log cuanto ha tardado. Cuando un companero dice "no me
    abre", la ultima linea del log dice exactamente en que se quedo y cuanto
    llevaba esperando, en vez de tener que adivinarlo."""

    def __init__(self, nombre):
        self.nombre = nombre

    def __enter__(self):
        self.t0 = time.time()
        logger.info("[arranque] %s ...", self.nombre)
        return self

    def __exit__(self, tipo, valor, tb):
        seg = time.time() - self.t0
        if tipo is None:
            nivel = logger.warning if seg > 5 else logger.info
            nivel("[arranque] %s: %.1fs", self.nombre, seg)
        else:
            logger.error("[arranque] %s FALLO tras %.1fs: %s", self.nombre, seg, valor)
        return False


class BuscadorPiezas(QMainWindow):
    def __init__(self):
        super().__init__()
        try:
            pythoncom.CoInitialize() # Inicialización COM Hilo Principal (V1.0.3)
        except:
            pass
        # V2.1.0 - REGLA DE ARRANQUE: aqui NO se toca la red. Ni el NAS ni la
        # base de datos. Todo lo que dependa de un cable va despues de que la
        # ventana este en pantalla (_carga_inicial_diferida). Esta es la causa
        # raiz de los "no me abre" de Pablo y Marcos: el proceso existia, pero
        # se quedaba esperando a la red antes de dibujar nada.
        self.db = IndexManager(tolerante=True, diferido=True)
        self.bd_disponible = False
        self.controller = SearchController(self.db)
        self.thread = None  # Referencia al thread de indexación activo
        self.bloqueo_filtros = False 
        self.cache_miniaturas = {} # V1.0.0 Caché de miniaturas (LRU simple)
        self._badge_cache = {}     # V2.0.0 Caché de badges de extensión (placeholder de Vista)
        
        # Debouncing para filtros (Evitar bloqueos) V1.0.0.2
        self.timer_filtros = QTimer()
        self.timer_filtros.setSingleShot(True)
        self.timer_filtros.timeout.connect(self._refrescar_real_jerarquico)

        # Debouncing para Previsualización (Optimización V1.0.05)
        self.timer_preview = QTimer()
        self.timer_preview.setSingleShot(True)
        self.timer_preview.timeout.connect(self._actualizar_preview_recursos_pesados)
        self.current_preview_data = {} # Almacena datos para la carga diferida
        
        with Fase("construir interfaz"):
            self.init_ui()
        self.toast = ToastNotification(self) # Inicializar Toast

        # V2.0.0: la carga inicial (consultas a PostgreSQL para poblar filtros y
        # preferencias) se difiere a DESPUÉS de mostrar la ventana. Antes corría
        # en el constructor, así que con la BD lenta o saturada (p.ej. durante una
        # reindexación) la ventana tardaba en aparecer ("abre al rato"). Ahora la
        # ventana sale al instante y los filtros se rellenan un momento después.
        QTimer.singleShot(0, self._carga_inicial_diferida)

        # Diagnóstico de red (V1.0.7)
        QTimer.singleShot(1200, self.verificar_rutas_red)
        # V2.0.0: comprobar si hay versión nueva en la carpeta de red
        QTimer.singleShot(3000, self._comprobar_actualizacion)

    # check_for_updates eliminado en V1.0.7 — El aviso de actualización lo gestiona
    # el administrador directamente con los compañeros.

    def _carga_inicial_diferida(self):
        """Carga inicial de filtros y preferencias, tras mostrar la ventana (V2.0.0).

        V2.1.0: aqui es donde se toca la red POR PRIMERA VEZ. La ventana ya esta
        en pantalla, asi que un servidor caido se traduce en un aviso, no en una
        aplicacion que parece no arrancar."""
        # Guardia de reentrada: processEvents() puede volver a disparar esta
        # misma carga (el singleShot pendiente) y encadenar intentos; se
        # midieron 15 s de ventana congelada por este motivo.
        if getattr(self, '_cargando_inicial', False):
            return
        self._cargando_inicial = True
        try:
            if NAS_HOST_ACTIVO is None:
                self.lbl_status.setText("Buscando el servidor de archivos…")
                QApplication.processEvents()
                with Fase("detectar NAS"):
                    detectar_nas_host()
            if not self.db.esta_disponible():
                # Conexion en segundo plano: la ventana NO se congela.
                self.lbl_status.setText("Conectando con la base de datos…")
                self._lanzar_conexion_bd()
                return
            self.lbl_status.setText("Cargando filtros…")
            QApplication.processEvents()
            self.cargar_filtros_propiedades()
            self.cargar_preferencias()
            # V2.3.1: Clientes y Proyectos DESPUÉS de restaurar las
            # preferencias. Antes se poblaban con el contexto por defecto y
            # quedaban desajustados con los orígenes y años restaurados hasta
            # que el usuario tocaba algo.
            self.refrescar_filtros_jerarquicos()
            # V2.3.0: cascada inicial de propiedades SW con las preferencias
            # ya restauradas (corre en segundo plano)
            self._refrescar_props_contexto()
            self._actualizar_chips_contexto()
            self.lbl_status.setText("Listo")
        except Exception as e:
            logger.error("Error en carga inicial diferida: %s", e, exc_info=True)
            self.lbl_status.setText("Listo")
        finally:
            self._cargando_inicial = False

    def _lanzar_conexion_bd(self, manual=False):
        """Intenta conectar en segundo plano (V2.1.0). Nunca bloquea la ventana."""
        anterior = getattr(self, '_conex_worker', None)
        if anterior is not None and anterior.isRunning():
            return          # ya hay un intento en marcha
        self._conex_manual = manual
        if manual:
            self.btn_bd_reintentar.setEnabled(False)
            self.btn_bd_reintentar.setText("Conectando…")
        self._conex_worker = ConexionWorker(self.db, self)
        self._conex_worker.resultado.connect(self._conexion_terminada)
        self._conex_worker.start()

    def _conexion_terminada(self, ok, motivo):
        """Resultado del intento de conexion (V2.1.0)."""
        self.btn_bd_reintentar.setEnabled(True)
        self.btn_bd_reintentar.setText("Reintentar")
        self.bd_disponible = ok
        intentos = getattr(self, '_reintentos_bd', 0)
        if ok:
            logger.info("Base de datos disponible tras %d intento(s)", intentos + 1)
            self.bd_banner.setVisible(False)
            self._reintentos_bd = 0
            if intentos:
                self.toast.show_message("✅ Conexión con la base de datos restablecida")
            self._carga_inicial_diferida()      # ahora si, a poblar filtros
            return
        self._reintentos_bd = intentos + 1
        logger.warning("Intento %d de conexion fallido: %s", self._reintentos_bd, motivo)
        self._mostrar_banner_bd(motivo)
        if getattr(self, '_conex_manual', False):
            self.toast.show_message("Sigue sin haber conexión con el servidor")
        # Reintento automatico espaciado: 10s, 20s, 40s... hasta 5 minutos
        espera = min(10000 * (2 ** min(self._reintentos_bd, 5)), 300000)
        QTimer.singleShot(espera, self._lanzar_conexion_bd)


    def mostrar_diagnostico(self):
        """Informe de estado para pegar en un mensaje cuando algo falla (V2.1.0)."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnóstico del equipo")
        dlg.resize(760, 560)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        cab = QLabel("Estado de este equipo")
        cab.setStyleSheet(
            'font-family: "%s"; font-size: 14px; font-weight: 800; '
            'color: #F5F5F5; background: transparent;' % FUENTES["h2"])
        lay.addWidget(cab)
        sub = QLabel("Comprobando servidor, NAS y disco… (unos segundos)")
        sub.setObjectName("StatusDim")
        lay.addWidget(sub)

        texto = QTextBrowser()
        texto.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
        texto.setPlainText("Comprobando…")
        lay.addWidget(texto, stretch=1)

        pie = QHBoxLayout()
        btn_copiar = QPushButton("Copiar al portapapeles")
        btn_copiar.setIcon(svg_icon("copiar-ruta", size=15))
        btn_copiar.setCursor(Qt.PointingHandCursor)
        btn_copiar.setEnabled(False)
        btn_copiar.clicked.connect(lambda: (
            QApplication.clipboard().setText(texto.toPlainText()),
            self.toast.show_message("✅ Diagnóstico copiado — pégalo en el mensaje")))
        pie.addWidget(btn_copiar)
        btn_log = QPushButton("Abrir carpeta del log")
        btn_log.setIcon(svg_icon("carpeta", size=15))
        btn_log.setCursor(Qt.PointingHandCursor)
        btn_log.clicked.connect(
            lambda: subprocess.Popen('explorer /select,"%s"' % RUTA_LOG))
        pie.addWidget(btn_log)
        pie.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.clicked.connect(dlg.accept)
        pie.addWidget(btn_cerrar)
        lay.addLayout(pie)

        def pintar(informe):
            texto.setPlainText(informe)
            sub.setText("Copia esto y mándalo si necesitas ayuda.")
            btn_copiar.setEnabled(True)
            logger.info("Diagnóstico generado por el usuario")

        self._diag_worker = DiagnosticoWorker(self)
        self._diag_worker.listo.connect(pintar)
        self._diag_worker.start()
        dlg.exec_()

    def _mostrar_banner_bd(self, motivo):
        """Ensena el aviso de 'sin base de datos' con la causa real (V2.1.0)."""
        primera = (str(motivo or "").strip().splitlines() or [""])[0]
        texto = primera[:160]
        self.lbl_bd.setText(
            "Sin conexión con la base de datos (%s:%s). "
            "La búsqueda no funcionará hasta que se restablezca.%s"
            % (PG_CONFIG.get('host', '?'), PG_CONFIG.get('port', '?'),
               ("  ·  " + texto) if texto else ""))
        self.bd_banner.setVisible(True)
        self.lbl_status.setText("Sin conexión con la base de datos")

    def _reintentar_bd(self, manual=False):
        """Boton 'Reintentar' del aviso (V2.1.0). El trabajo lo hace un hilo."""
        self._lanzar_conexion_bd(manual=manual)


    def verificar_rutas_red(self):
        """Comprueba si las rutas del NAS son accesibles (V1.0.7).
        V2.0.1: usa el host detectado (IP o NASCENTRAL), así que en equipos que
        solo llegan por nombre ya no salta el falso aviso."""
        error_msg = ""
        for origen, ruta in rutas_nas_activas().items():
            if not os.path.exists(ruta):
                error_msg += f"• {ETIQUETAS_ORIGEN.get(origen, origen)}: {ruta}\n"

        if error_msg:
            QMessageBox.warning(self, "Problema de Red",
                                "Atención: No se puede acceder a las siguientes rutas del NAS:\n\n" +
                                error_msg +
                                f"\nComprueba la conexión de red con el NAS ({NAS_HOST_ACTIVO or '192.168.1.10'}).")
            logger.error(f"Rutas NAS no accesibles (host {NAS_HOST_ACTIVO}): {error_msg}")
        else:
            logger.info(f"Rutas NAS OK por host: {NAS_HOST_ACTIVO}")

    def toggle_checkboxes(self, list_widget, state):
        """Activa o desactiva todos los checkboxes en un QListWidget.
        V2.3.0: 'Todos' no marca los valores ocultos por la cascada de
        propiedades (no existen en el contexto actual); 'Ninguno' desmarca
        siempre todo, ocultos incluidos."""
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if state and item.isHidden():
                continue
            item.setCheckState(Qt.Checked if state else Qt.Unchecked)
    
    def get_selected_items(self, list_widget):
        """Devuelve una lista con el texto o data de los items marcados en un QListWidget"""
        sel = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole)
                sel.append(data if data is not None else item.text())
        return sel

    def add_toggle_buttons(self, layout, list_widget):
        """Añade enlaces Todos/Ninguno compactos bajo un list_widget (V2.0.1)"""
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.setContentsMargins(2, 0, 0, 2)

        btn_todos = QPushButton("Todos")
        btn_todos.setObjectName("btn_toggle")
        btn_todos.setCursor(Qt.PointingHandCursor)
        btn_todos.setFixedHeight(18)
        btn_todos.clicked.connect(lambda: self.toggle_checkboxes(list_widget, True))

        btn_ninguno = QPushButton("Ninguno")
        btn_ninguno.setObjectName("btn_toggle")
        btn_ninguno.setCursor(Qt.PointingHandCursor)
        btn_ninguno.setFixedHeight(18)
        btn_ninguno.clicked.connect(lambda: self.toggle_checkboxes(list_widget, False))

        btn_layout.addWidget(btn_todos)
        btn_layout.addWidget(btn_ninguno)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def get_companeros_seleccionados(self):
        return self.get_selected_items(self.list_companeros)

    def get_años_seleccionados(self):
        return self.get_selected_items(self.list_años)

    def get_selected_tipos(self):
        """Devuelve lista de tipos seleccionados desde el nuevo menú superior (V1.0.0)"""
        sel = []
        for tipo, action in self.tipos_actions.items():
            if action.isChecked():
                sel.append(tipo)
        return sel

    def on_tipos_menu_changed(self):
        """Manejador para cuando se marca/desmarca un tipo en el menú superior"""
        self.actualizar_texto_tipos()

    def actualizar_texto_tipos(self):
        """Actualiza el texto del botón según la selección"""
        if not hasattr(self, 'tipos_actions'): return
        sel = self.get_selected_tipos()
        if len(sel) == len(self.tipos_actions):
            self.btn_tipos.setText("Tipos: TODOS")
        elif len(sel) == 0:
            self.btn_tipos.setText("Tipos: NINGUNO")
        elif len(sel) == 1:
            self.btn_tipos.setText(f"Tipos: {sel[0]}")
        else:
            self.btn_tipos.setText(f"Tipos: ({len(sel)})")

    def toggle_tipos_menu(self, state):
        """Marca o desmarca todos los tipos en el menú"""
        for action in self.tipos_actions.values():
            action.setChecked(state)
        self.actualizar_texto_tipos()

    def init_ui(self):
        self.setWindowTitle("Buscador de Piezas SolidWorks - ALSI")
        self.resize(1500, 850)
        
        # Cargar Icono de Aplicación Profesional (V1.0.0)
        if os.path.exists(APP_ICON):
            self.setWindowIcon(QIcon(APP_ICON))
        elif os.path.exists(LOGO_ISOTIPO):
            self.setWindowIcon(QIcon(LOGO_ISOTIPO))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        # V2.0.1: layout a sangre — header y footer edge-to-edge (sin franja oscura
        # del fondo #242424 rodeando el header). El padding va en la zona central.
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ═══════════════════════════════════════════
        # CABECERA (ISOTIPO + TÍTULO H1 + BARRA DE BÚSQUEDA) - V2.0.0
        # ═══════════════════════════════════════════
        self.header_frame = QFrame()
        self.header_frame.setObjectName("Header")
        header_layout = QHBoxLayout(self.header_frame)
        # V2.0.0: header más compacto (menos alto) y mejor repartido
        header_layout.setContentsMargins(14, 5, 14, 5)
        header_layout.setSpacing(10)

        # Isotipo corporativo (V2.0.0: precompuesto sobre el fondo oscuro del
        # header #2E2E2E para evitar franjas por transparencia parcial en Windows)
        self.lbl_logo = QLabel()
        self.lbl_logo.setStyleSheet("background-color: transparent; border: none; padding: 0px; margin: 0px;")
        if os.path.exists(LOGO_ISOTIPO):
            from PIL import Image as PILImage
            pil_img = PILImage.open(LOGO_ISOTIPO).convert("RGBA")
            bg = PILImage.new("RGBA", pil_img.size, (46, 46, 46, 255))  # #2E2E2E
            bg.paste(pil_img, (0, 0), pil_img)
            bg = bg.convert("RGB")
            target_h = 38
            aspect = pil_img.width / pil_img.height
            target_w = int(target_h * aspect)
            bg = bg.resize((target_w, target_h), PILImage.LANCZOS)
            from io import BytesIO
            buffer = BytesIO()
            bg.save(buffer, format="PNG")
            buffer.seek(0)
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.read())
            self.lbl_logo.setPixmap(pixmap)
            self.lbl_logo.setFixedSize(target_w, target_h)
        else:
            self.lbl_logo.setText("ALSI")
            self.lbl_logo.setStyleSheet(f"color: {RAL_2010_NARANJA}; font-size: 24px; font-weight: bold; background-color: transparent; border: none;")
        header_layout.addWidget(self.lbl_logo)

        # Título principal H1 (AG ALSI, único sitio junto con "Acerca de")
        self.lbl_titulo_h1 = QLabel('BUSCADOR DE <span style="color:#E66C32;">PIEZAS</span>')
        self.lbl_titulo_h1.setTextFormat(Qt.RichText)
        aplicar_h1(self.lbl_titulo_h1, size=17)
        header_layout.addWidget(self.lbl_titulo_h1)
        
        # Barra de búsqueda
        self.input_buscar = QLineEdit()
        self.input_buscar.setObjectName("SearchBox")
        # V2.1.4: el propio placeholder enseña la sintaxis, incluido el nuevo
        # '-palabra'. Es el primer sitio donde mira todo el mundo.
        self._placeholder_busqueda_original = (
            "Buscar:  cinta; 450; -banda      ·   ';' todas   ·   ',' cualquiera   ·   '-' quita")
        self.input_buscar.setPlaceholderText(self._placeholder_busqueda_original)
        self.input_buscar.setToolTip(
            "CÓMO BUSCAR\n"
            "  cinta 450      frase exacta (tal cual, con el espacio)\n"
            "  cinta;450      las DOS cosas en el nombre\n"
            "  cinta,tapa     cualquiera de las dos\n"
            "  -banda         QUITA lo que lleve 'banda' en el nombre\n"
            "\n"
            "Se pueden mezclar:  cinta; 450; -banda; -inox\n"
            "El guion solo quita si abre palabra:\n"
            "'26-0006' o 'AC30-Q6A014' se buscan tal cual.")
        self.input_buscar.setMinimumHeight(38)
        # V2.0.0: buscador amplio pero con tope, y un separador elástico después,
        # para que los botones de la derecha respiren sin que se inflen
        self.input_buscar.setMaximumWidth(1050)
        self.input_buscar.returnPressed.connect(self.ejecutar_busqueda)
        # El buscador se queda con 6/7 del espacio libre (amplio); el separador
        # con 1/7 evita que los botones se inflen cuando el buscador llega al tope
        header_layout.addWidget(self.input_buscar, stretch=6)
        header_layout.addStretch(1)

        # 4. TIPOS DE ARCHIVO (V1.0.0 - Reubicado a Barra Superior)
        self.btn_tipos = QPushButton("Tipos: TODOS")
        self.btn_tipos.setIcon(svg_icon("capas-tipos"))
        self.btn_tipos.setMinimumHeight(38)
        self.btn_tipos.setCursor(Qt.PointingHandCursor)
        # V2.0.0: ancho mínimo generoso para que "Tipos: ENSAMBLAJES" no se corte
        # ni siquiera con escalado de pantalla al 125/150%
        self.btn_tipos.setMinimumWidth(230)
        self.btn_tipos.setStyleSheet("""
            QPushButton::menu-indicator { image: none; }
            QPushButton { padding: 5px 14px; font-weight: bold; text-align: left; }
        """)
        
        self.menu_tipos = CheckableMenu(self)  # Menú que no se cierra al seleccionar (R5)
        
        action_todos = self.menu_tipos.addAction(svg_icon("check"), "Seleccionar Todos")
        action_todos.triggered.connect(lambda: self.toggle_tipos_menu(True))
        action_ninguno = self.menu_tipos.addAction("Deseleccionar Todos")
        action_ninguno.triggered.connect(lambda: self.toggle_tipos_menu(False))
        self.menu_tipos.addSeparator()

        self.tipos_actions = {}
        for tipo in list(FILTRO_EXTENSIONES.keys()):
            if tipo == 'TODOS': continue
            action = QMenu().addAction(tipo) # Hack para tener checkable en CSS/Style si se desea
            action = self.menu_tipos.addAction(tipo)
            action.setCheckable(True)
            action.setChecked(True)
            action.triggered.connect(self.on_tipos_menu_changed)
            action.triggered.connect(lambda: self.on_filtro_jerarquico_changed(None))
            self.tipos_actions[tipo] = action
            
        self.btn_tipos.setMenu(self.menu_tipos)
        header_layout.addWidget(self.btn_tipos)

        # V2.1.0 - Toggle "Placa CE": solo máquinas con placa CE registrada en
        # los Excel de NÚMEROS DE SERIE (y permite buscar por nº de placa)
        self.btn_placa_ce = QPushButton("Placa CE")
        self.btn_placa_ce.setObjectName("ToggleCE")
        self.btn_placa_ce.setIcon(svg_icon("check", size=15))
        self.btn_placa_ce.setCheckable(True)
        self.btn_placa_ce.setCursor(Qt.PointingHandCursor)
        self.btn_placa_ce.setMinimumHeight(38)
        self.btn_placa_ce.setToolTip(
            "Solo máquinas con placa CE registrada en NÚMEROS DE SERIE.\n"
            "Filtra ensamblajes/planos cuyo código (ej. 26047.E107) tiene placa asignada.\n"
            "Consejo: también puedes escribir directamente un nº de placa (ej. 26-0006)\n"
            "en el buscador para encontrar su máquina.")
        self.btn_placa_ce.toggled.connect(self._on_placa_ce_toggled)
        header_layout.addWidget(self.btn_placa_ce)

        self.btn_buscar = QPushButton("Buscar")
        self.btn_buscar.setIcon(svg_icon("buscar", color="#FFFFFF"))
        self.btn_buscar.setObjectName("Primary")
        self.btn_buscar.setToolTip("Haz clic para iniciar la búsqueda (o pulsa Enter)")
        self.btn_buscar.setCursor(Qt.PointingHandCursor)
        self.btn_buscar.setMinimumHeight(38)
        self.btn_buscar.setFixedWidth(120)
        self.btn_buscar.clicked.connect(self.ejecutar_busqueda)
        # V2.0.3: esquinas derechas rectas — se une con el selector de modo (▾)
        self.btn_buscar.setStyleSheet(
            "border-top-right-radius: 0px; border-bottom-right-radius: 0px;")
        header_layout.addWidget(self.btn_buscar)

        # V2.0.3: selector de modo de búsqueda, pegado al botón Buscar
        # - Por nombre (clásico)
        # - Conjuntos que LLEVEN la pieza escrita (cruza la tabla componentes)
        self.modo_busqueda = 'nombre'
        self.btn_modo_busqueda = QPushButton("▾")
        self.btn_modo_busqueda.setObjectName("BtnModoBusqueda")
        self.btn_modo_busqueda.setCursor(Qt.PointingHandCursor)
        self.btn_modo_busqueda.setMinimumHeight(38)
        self.btn_modo_busqueda.setFixedWidth(26)
        self.btn_modo_busqueda.setToolTip(
            "Modo de búsqueda:\n"
            "· Por nombre (lo habitual)\n"
            "· Conjuntos que lleven la pieza escrita")
        # Sin indicador de menú nativo (dibuja una flecha extra descolgada) y
        # visualmente unido al botón Buscar como un solo control.
        self.btn_modo_busqueda.setStyleSheet(
            "QPushButton#BtnModoBusqueda { background-color: #E66C32; color: #FFFFFF; "
            "border: none; border-left: 1px solid rgba(0,0,0,0.25); "
            "border-top-right-radius: 6px; border-bottom-right-radius: 6px; "
            "border-top-left-radius: 0px; border-bottom-left-radius: 0px; "
            "font-size: 11px; font-weight: 700; padding: 0px; }"
            "QPushButton#BtnModoBusqueda:hover { background-color: #D35400; }"
            "QPushButton#BtnModoBusqueda::menu-indicator { image: none; width: 0px; }")
        menu_modo = QMenu(self)
        self.act_modo_nombre = menu_modo.addAction("Buscar por nombre")
        self.act_modo_contiene = menu_modo.addAction("Buscar conjuntos que lleven esa pieza")
        for a in (self.act_modo_nombre, self.act_modo_contiene):
            a.setCheckable(True)
        self.act_modo_nombre.setChecked(True)
        self.act_modo_nombre.triggered.connect(
            lambda _=False: self._set_modo_busqueda('nombre'))
        self.act_modo_contiene.triggered.connect(
            lambda _=False: self._set_modo_busqueda('contiene'))
        self.btn_modo_busqueda.setMenu(menu_modo)
        header_layout.addWidget(self.btn_modo_busqueda)

        main_layout.addWidget(self.header_frame)

        # ═══════════════════════════════════════════
        # BARRA DE CONTEXTO (V2.0.1): filtros activos + Limpiar | Recientes + Guardadas
        # ═══════════════════════════════════════════
        self.context_frame = QFrame()
        self.context_frame.setObjectName("ContextBar")
        ctx_lay = QHBoxLayout(self.context_frame)
        ctx_lay.setContentsMargins(14, 6, 14, 6)
        ctx_lay.setSpacing(6)

        self.chips_activos_lay = QHBoxLayout()
        self.chips_activos_lay.setSpacing(6)
        ctx_lay.addLayout(self.chips_activos_lay)

        self.btn_limpiar = QPushButton("Limpiar")
        self.btn_limpiar.setObjectName("btn_toggle")
        self.btn_limpiar.setCursor(Qt.PointingHandCursor)
        self.btn_limpiar.clicked.connect(self._limpiar_filtros)
        self.btn_limpiar.setVisible(False)  # Solo visible con filtros activos
        ctx_lay.addWidget(self.btn_limpiar)

        ctx_lay.addStretch()

        lbl_recientes = QLabel("Recientes:")
        lbl_recientes.setObjectName("StatusDim")
        ctx_lay.addWidget(lbl_recientes)
        self.recientes_lay = QHBoxLayout()
        self.recientes_lay.setSpacing(4)
        ctx_lay.addLayout(self.recientes_lay)

        self.btn_guardadas = QPushButton("★ Guardadas")
        self.btn_guardadas.setObjectName("Chip")
        self.btn_guardadas.setCursor(Qt.PointingHandCursor)
        self.menu_guardadas = QMenu(self)
        self.btn_guardadas.setMenu(self.menu_guardadas)
        ctx_lay.addWidget(self.btn_guardadas)

        main_layout.addWidget(self.context_frame)

        # ═══════════════════════════════════════════
        # BANNER DE ACTUALIZACIÓN (V2.0.0): aparece si hay versión nueva en la red
        # ═══════════════════════════════════════════
        self.update_banner = QFrame()
        self.update_banner.setObjectName("UpdateBanner")
        ub_lay = QHBoxLayout(self.update_banner)
        ub_lay.setContentsMargins(14, 7, 14, 7)
        ub_lay.setSpacing(10)
        ub_icon = QLabel()
        ub_icon.setPixmap(svg_pixmap("reindexar-refrescar", color="#FFFFFF", size=16))
        ub_lay.addWidget(ub_icon)
        self.lbl_update = QLabel("Actualización disponible")
        self.lbl_update.setStyleSheet("color: #FFFFFF; font-weight: 700; background: transparent;")
        ub_lay.addWidget(self.lbl_update)
        ub_lay.addStretch()
        self.btn_update = QPushButton("Actualizar ahora")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.setStyleSheet(
            "QPushButton { background: #FFFFFF; color: #BF5320; border: none; "
            "border-radius: 6px; padding: 5px 14px; font-weight: 800; } "
            "QPushButton:hover { background: #FFE3D2; }")
        self.btn_update.clicked.connect(self._lanzar_actualizacion)
        ub_lay.addWidget(self.btn_update)
        btn_update_x = QPushButton("✕")
        btn_update_x.setCursor(Qt.PointingHandCursor)
        btn_update_x.setFixedSize(24, 24)
        btn_update_x.setToolTip("Ocultar (te lo recordaré en el próximo arranque)")
        btn_update_x.setStyleSheet(
            "QPushButton { background: transparent; color: #FFFFFF; border: none; "
            "font-weight: 800; } QPushButton:hover { color: #FFE3D2; }")
        btn_update_x.clicked.connect(lambda: self.update_banner.setVisible(False))
        ub_lay.addWidget(btn_update_x)
        self.update_banner.setVisible(False)
        main_layout.addWidget(self.update_banner)

        # V2.1.0 - Banner de estado de la base de datos. Antes, si el servidor
        # no respondia, la app ni se abria; ahora se abre y DICE que pasa, con
        # que reintentar y como diagnosticarlo. Nunca mas un "no funciona" mudo.
        self.bd_banner = QFrame()
        self.bd_banner.setObjectName("BdBanner")
        self.bd_banner.setStyleSheet(
            "#BdBanner { background: #8C2F2F; border-radius: 8px; }")
        bd_lay = QHBoxLayout(self.bd_banner)
        bd_lay.setContentsMargins(14, 8, 10, 8)
        bd_lay.setSpacing(10)
        self.lbl_bd = QLabel("Sin conexión con la base de datos")
        self.lbl_bd.setStyleSheet(
            "color: #FFFFFF; font-weight: 700; background: transparent;")
        self.lbl_bd.setWordWrap(True)
        bd_lay.addWidget(self.lbl_bd, stretch=1)
        self.btn_bd_reintentar = QPushButton("Reintentar")
        self.btn_bd_reintentar.setCursor(Qt.PointingHandCursor)
        self.btn_bd_reintentar.setStyleSheet(
            "QPushButton { background: #FFFFFF; color: #8C2F2F; border: none; "
            "border-radius: 6px; padding: 5px 14px; font-weight: 800; } "
            "QPushButton:hover { background: #FFE0E0; }")
        self.btn_bd_reintentar.clicked.connect(lambda: self._reintentar_bd(manual=True))
        bd_lay.addWidget(self.btn_bd_reintentar)
        btn_bd_diag = QPushButton("Diagnóstico")
        btn_bd_diag.setCursor(Qt.PointingHandCursor)
        btn_bd_diag.setStyleSheet(
            "QPushButton { background: transparent; color: #FFFFFF; border: "
            "1px solid #FFFFFF; border-radius: 6px; padding: 4px 12px; "
            "font-weight: 700; } QPushButton:hover { background: #A03A3A; }")
        btn_bd_diag.clicked.connect(self.mostrar_diagnostico)
        bd_lay.addWidget(btn_bd_diag)
        self.bd_banner.setVisible(False)
        main_layout.addWidget(self.bd_banner)
        self._version_red = None  # versión detectada en red (para el instalador)

        # ═══════════════════════════════════════════
        # CONTENIDO PRINCIPAL (SPLITTER: SIDEBAR + CONTENT) V1.0.0
        # ═══════════════════════════════════════════
        
        # Splitter Principal (Horizontal) para redimensionar barra lateral
        # (estilos del handle en QSS_EXTRAS)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(4) # Línea sutil

        # --- Panel filtros izquierdo (Scrollable Sidebar, colapsable a raíl V2.0.1) ---
        panel_izquierdo = QFrame()
        panel_izquierdo.setObjectName("Panel")
        panel_izquierdo.setMinimumWidth(80)
        panel_izquierdo.setMaximumWidth(500)
        izq_outer_layout = QVBoxLayout(panel_izquierdo)
        izq_outer_layout.setContentsMargins(10, 10, 10, 10)
        izq_outer_layout.setSpacing(6)
        self._panel_izquierdo = panel_izquierdo
        self._izq_outer_layout = izq_outer_layout

        sidebar_header = QHBoxLayout()
        lbl_panel_filtros = QLabel("FILTROS AVANZADOS")
        aplicar_h2(lbl_panel_filtros)
        self._lbl_panel_filtros = lbl_panel_filtros
        sidebar_header.addWidget(lbl_panel_filtros)
        sidebar_header.addStretch()
        self.btn_colapsar_sidebar = QPushButton()
        self.btn_colapsar_sidebar.setIcon(svg_icon("contraer-panel", size=14))
        self.btn_colapsar_sidebar.setToolTip("Contraer panel de filtros")
        self.btn_colapsar_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_colapsar_sidebar.setFixedSize(24, 24)
        self.btn_colapsar_sidebar.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; }")
        self.btn_colapsar_sidebar.clicked.connect(lambda: self._toggle_sidebar())
        sidebar_header.addWidget(self.btn_colapsar_sidebar)
        izq_outer_layout.addLayout(sidebar_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_widget = QWidget()
        izq_layout = QVBoxLayout(scroll_widget)
        izq_layout.setContentsMargins(4, 4, 4, 4)
        izq_layout.setSpacing(4)
        
        # ═══ V2.0.1 - SIDEBAR ÚNICA CON ACORDEONES ═══
        self._sidebar_layout = izq_layout
        self.acordeones = {}

        def _acordeon(clave, titulo, icono, expandido=True):
            sec = SeccionAcordeon(titulo, icono, expandido)
            izq_layout.addWidget(sec)
            self.acordeones[clave] = sec
            return sec

        # 1. ORIGEN
        sec_origen = _acordeon('origen', 'ORIGEN', 'carpeta')
        self.list_companeros = ListaFiltro(ajustar_a_contenido=True)  # solo 3 orígenes
        for key, label in ETIQUETAS_ORIGEN.items():
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)  # Internamente usamos la key
            item.setToolTip(RUTAS_NAS.get(key, ''))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_companeros.addItem(item)
        sec_origen.lay.addWidget(self.list_companeros)
        self.add_toggle_buttons(sec_origen.lay, self.list_companeros)

        # 2. AÑOS (V2.0.1: chips sincronizados con list_años oculto,
        # que sigue siendo la fuente de verdad para búsqueda y preferencias)
        sec_años = _acordeon('años', 'AÑOS DE PROYECTO', 'calendario-anos')
        self.list_años = QListWidget()
        año_actual = datetime.now().year
        for año in range(año_actual + 1, 2012, -1):
            item = QListWidgetItem(str(año))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Marcar por defecto hasta 2022 (o todo)
            item.setCheckState(Qt.Checked if año >= 2022 else Qt.Unchecked)
            self.list_años.addItem(item)
        self.list_años.setVisible(False)
        sec_años.lay.addWidget(self.list_años)

        self.chips_años = {}
        chips_años_w = QWidget()
        from PyQt5.QtWidgets import QGridLayout
        chips_grid = QGridLayout(chips_años_w)
        chips_grid.setContentsMargins(0, 0, 0, 0)
        chips_grid.setSpacing(4)
        AÑOS_POR_FILA = 3
        for i in range(self.list_años.count()):
            item = self.list_años.item(i)
            chip = QPushButton(item.text())
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setChecked(item.checkState() == Qt.Checked)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            chip.toggled.connect(
                lambda on, it=item: it.setCheckState(Qt.Checked if on else Qt.Unchecked))
            chips_grid.addWidget(chip, i // AÑOS_POR_FILA, i % AÑOS_POR_FILA)
            self.chips_años[item.text()] = chip
        sec_años.lay.addWidget(chips_años_w)
        self.list_años.itemChanged.connect(self._sync_chip_anio)
        self.add_toggle_buttons(sec_años.lay, self.list_años)

        # 3. CARPETAS (MECANICA, LAYOUT...)
        sec_carpetas = _acordeon('carpetas', 'CARPETAS', 'capas-tipos')
        self.list_carpetas = ListaFiltro()
        for folder in FILTRO_CARPETAS:
            if folder == 'TODOS': continue
            item = QListWidgetItem(folder)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_carpetas.addItem(item)
        sec_carpetas.lay.addWidget(self.list_carpetas)
        self.add_toggle_buttons(sec_carpetas.lay, self.list_carpetas)
        self.list_carpetas.itemChanged.connect(self.on_filtro_jerarquico_changed)

        # 5. CLIENTES
        sec_clientes = _acordeon('clientes', 'CLIENTES', 'clientes')
        self.list_clientes = ListaFiltro()
        sec_clientes.lay.addWidget(self.list_clientes)
        self.add_toggle_buttons(sec_clientes.lay, self.list_clientes)

        # 6. PROYECTOS
        sec_proyectos = _acordeon('proyectos', 'PROYECTOS', 'proyectos-maletin')
        self.list_proyectos = ListaFiltro()
        sec_proyectos.lay.addWidget(self.list_proyectos)
        self.add_toggle_buttons(sec_proyectos.lay, self.list_proyectos)

        # Conectar señales para Cascada (V1.0.0 - Completo)
        self.list_companeros.itemChanged.connect(self.on_filtro_jerarquico_changed)
        self.list_años.itemChanged.connect(self.on_filtro_jerarquico_changed)
        self.list_clientes.itemChanged.connect(self.on_filtro_jerarquico_changed)
        self.list_proyectos.itemChanged.connect(self.on_filtro_jerarquico_changed)

        # Las secciones de Propiedades SW y Fabricación se añaden más abajo
        # (V2.0.1: sidebar única, ya no hay panel derecho separado)
        scroll.setWidget(scroll_widget)
        izq_outer_layout.addWidget(scroll)
        self._scroll_filtros = scroll

        # Añadir panel izquierdo al splitter principal
        self.main_splitter.addWidget(panel_izquierdo)

        # --- Splitter Derecho: Tabla + Panel Preview ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(3)
        
        # Tabla (V1.0.6: 21 columnas | V2.0.0: cabeceras fabricación abreviadas)
        self.tabla = TablaArrastrable()
        shadow_effect2 = QGraphicsDropShadowEffect()
        shadow_effect2.setBlurRadius(15)
        shadow_effect2.setColor(QColor(0, 0, 0, 20))
        shadow_effect2.setOffset(0, 2)
        self.tabla.setGraphicsEffect(shadow_effect2)
        # V2.0.8: Peso y Superficie se añaden AL FINAL a propósito — así no se
        # mueve ningún índice de columna ya existente (delegados, exportación,
        # menú Columnas y preferencias guardadas siguen valiendo).
        self.tabla.setColumnCount(23)
        self.tabla.setHorizontalHeaderLabels([
            "Ruta_Hidden", "Orden_Orig", "Cód. Proy_Hidden", "Nom. Proy_Hidden", "Vista",
            "Nombre", "Origen", "Año", "Cliente", "Proyecto",
            "Orden", "Material", "Tratamiento", "Espesor", "L",
            "T", "F", "S", "P", "M", "Tipo",
            "Peso (kg)", "Sup. (m²)"
        ])
        for _c, _t in ((21, "Peso de la pieza o conjunto, leído de SolidWorks"),
                       (22, "Superficie exterior de la pieza o conjunto (m²)")):
            _h = self.tabla.horizontalHeaderItem(_c)
            if _h:
                _h.setToolTip(_t)
        # Tooltips con el nombre completo de las columnas de fabricación abreviadas
        NOMBRES_FABRICACION = {14: "Láser", 15: "Torno", 16: "Fresa", 17: "Soldadura", 18: "Pintura", 19: "Montaje"}
        for col_idx, nombre_completo in NOMBRES_FABRICACION.items():
            h_item = self.tabla.horizontalHeaderItem(col_idx)
            if h_item:
                h_item.setToolTip(nombre_completo)
        # Píldora coloreada en la columna Tipo (V2.0.0)
        self._pill_delegate = PillDelegate(self.tabla)
        self.tabla.setItemDelegateForColumn(20, self._pill_delegate)
        # ✓ / · en columnas de fabricación (V2.0.0)
        self._fab_delegate = FabricacionDelegate(self.tabla)
        for col_fab in range(14, 20):
            self.tabla.setItemDelegateForColumn(col_fab, self._fab_delegate)

        # V2.0.0: selección naranja tint también con la tabla sin foco y bajo delegados
        # (la paleta Fusion pone azul en activo y gris claro en inactivo)
        pal_tabla = self.tabla.palette()
        for grupo_pal in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            pal_tabla.setColor(grupo_pal, QPalette.Highlight, QColor("#3A2C21"))
            pal_tabla.setColor(grupo_pal, QPalette.HighlightedText, QColor("#F5F5F5"))
        self.tabla.setPalette(pal_tabla)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # V2.0.0: sin zebra — el diseño usa fondo uniforme #1D1D1D con separador entre filas
        self.tabla.setAlternatingRowColors(False)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setFrameStyle(QFrame.NoFrame)
        
        # 3-State Sorting Manual
        self.tabla.setSortingEnabled(False)
        self._sort_state = {"col": -1, "order": Qt.AscendingOrder}
        
        # Ajuste de tamaño de filas e iconos para las miniaturas (V2.0.0: Cómoda 64px/56px)
        self.tabla.setIconSize(QSize(56, 56))
        self.tabla.verticalHeader().setDefaultSectionSize(64)
        # V2.0.6: vista previa grande al pasar el ratón por encima de la fila
        # (la ruta es el texto de la columna 0, oculta)
        self._hover_tabla_principal = self._hover_tabla(self.tabla, 0, por_texto=True)
        
        header = self.tabla.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive) # Todas interactivas 
        header.setStretchLastSection(True) # Ahora la última (12) es Nombre Orden y es visible
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self.on_header_clicked)
        
        self.tabla.setColumnHidden(0, True) # Ruta_Hidden
        self.tabla.setColumnHidden(1, True) # Orden_Orig
        self.tabla.setColumnHidden(2, True) # Cód. Proy_Hidden
        self.tabla.setColumnHidden(3, True) # Nom. Proy_Hidden
        self.tabla.setColumnWidth(4, 68)  # Vista (miniatura 56px + margen)
        self.tabla.setColumnWidth(5, 250) # Nombre
        self.tabla.setColumnWidth(6, 95)  # Origen
        self.tabla.setColumnWidth(7, 55)  # Año
        self.tabla.setColumnWidth(8, 144) # Cliente
        self.tabla.setColumnWidth(9, 200) # Proyecto
        self.tabla.setColumnWidth(10, 180) # Orden combinada
        self.tabla.setColumnWidth(11, 100)# Material
        self.tabla.setColumnWidth(12, 100)# Tratamiento
        self.tabla.setColumnWidth(13, 60) # Espesor
        # Columnas de fabricación estrechas (V2.0.0: L T F S P M)
        for col_fab in range(14, 20):
            self.tabla.setColumnWidth(col_fab, 28)
        # Columna 20 (Tipo) estira automáticamente
        
        self.tabla.doubleClicked.connect(self.abrir_carpeta_seleccionada)
        self.tabla.selectionModel().currentRowChanged.connect(self.actualizar_preview)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self.mostrar_menu_contextual)

        # ═══════════════════════════════════════════
        # TOOLBAR CENTRAL (V2.0.0): Lista/Galería + Cómoda/Compacta | Columnas + Exportar
        # ═══════════════════════════════════════════
        self.qsettings = QSettings("ALSI", "BuscadorPiezas")

        def _crear_segmento(botones, grupo_exclusivo=True):
            """Crea QPushButtons checkables estilo segmented (dynamic property)."""
            grupo = QButtonGroup(self)
            grupo.setExclusive(grupo_exclusivo)
            widgets = []
            for i, (texto, icono) in enumerate(botones):
                btn = QPushButton(texto)
                if icono:
                    btn.setIcon(svg_icon(icono, size=15))
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setProperty("segmento", "true")
                if i == 0:
                    btn.setProperty("segPos", "first")
                elif i == len(botones) - 1:
                    btn.setProperty("segPos", "last")
                grupo.addButton(btn, i)
                widgets.append(btn)
            return grupo, widgets

        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(10)

        # Segmento Lista/Galería (V2.0.0)
        self.grupo_vista, botones_vista = _crear_segmento([("Lista", "vista-lista"), ("Galería", "vista-galeria")])
        self.btn_vista_lista, self.btn_vista_galeria = botones_vista
        self.btn_vista_lista.setChecked(True)
        self.grupo_vista.buttonClicked[int].connect(self._cambiar_vista)
        seg_vista_layout = QHBoxLayout()
        seg_vista_layout.setSpacing(0)
        for b in botones_vista:
            seg_vista_layout.addWidget(b)
        toolbar_layout.addLayout(seg_vista_layout)

        # Segmento Cómoda/Compacta (drive del combo existente para no romper la señal)
        # V2.0.0: solo visible en vista Lista — en Galería la densidad no aplica
        self.grupo_densidad, botones_dens = _crear_segmento([("Cómoda", None), ("Compacta", None)])
        self.btn_dens_comoda, self.btn_dens_compacta = botones_dens
        self.btn_dens_comoda.setChecked(True)
        self.grupo_densidad.buttonClicked[int].connect(self._on_densidad_segment)
        self.seg_dens_container = QWidget()
        seg_dens_layout = QHBoxLayout(self.seg_dens_container)
        seg_dens_layout.setContentsMargins(0, 0, 0, 0)
        seg_dens_layout.setSpacing(0)
        for b in botones_dens:
            seg_dens_layout.addWidget(b)
        toolbar_layout.addWidget(self.seg_dens_container)

        # Segmento S/M/L/XL + barra de zoom continua (solo en vista Galería).
        # V2.0.3: se añade XL y un deslizador para cualquier tamaño intermedio.
        self.grupo_tam_galeria, botones_tam = _crear_segmento(
            [("S", None), ("M", None), ("L", None), ("XL", None)])
        self.btn_tam_s, self.btn_tam_m, self.btn_tam_l, self.btn_tam_xl = botones_tam
        self.btn_tam_m.setChecked(True)
        self.grupo_tam_galeria.buttonClicked[int].connect(self._cambiar_tam_galeria)
        self.seg_tam_container = QWidget()
        seg_tam_layout = QHBoxLayout(self.seg_tam_container)
        seg_tam_layout.setContentsMargins(0, 0, 0, 0)
        seg_tam_layout.setSpacing(0)
        for b in botones_tam:
            seg_tam_layout.addWidget(b)
        self.seg_tam_container.setVisible(False)  # Solo visible en vista Galería
        toolbar_layout.addWidget(self.seg_tam_container)

        # Deslizador de zoom de la galería (72–420 px de icono)
        self.slider_zoom = QSlider(Qt.Horizontal)
        self.slider_zoom.setMinimum(self.ZOOM_MIN)
        self.slider_zoom.setMaximum(self.ZOOM_MAX)
        self.slider_zoom.setValue(128)
        self.slider_zoom.setFixedWidth(120)
        self.slider_zoom.setToolTip(
            "Tamaño de las tarjetas de la galería.\n"
            "Arrastra para el tamaño que quieras (o usa S/M/L/XL).\n"
            "Atajo: Ctrl + rueda del ratón sobre la galería.")
        self.slider_zoom.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: #333333; border-radius: 2px; }"
            "QSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0; "
            "background: #E66C32; border-radius: 6px; }"
            "QSlider::sub-page:horizontal { background: #E66C32; border-radius: 2px; }")
        self.slider_zoom.valueChanged.connect(self._on_zoom_galeria)
        self.slider_zoom.setVisible(False)  # Solo en vista Galería
        toolbar_layout.addWidget(self.slider_zoom)

        toolbar_layout.addStretch()

        # Botón Columnas (menú checkable, persistido en QSettings)
        self.btn_columnas = QPushButton("Columnas")
        self.btn_columnas.setIcon(svg_icon("columnas", size=15))
        self.btn_columnas.setCursor(Qt.PointingHandCursor)
        # V2.0.0: ancho mínimo y sin flecha de menú (cortaba la 's' final)
        self.btn_columnas.setMinimumWidth(130)
        self.btn_columnas.setStyleSheet(
            "QPushButton::menu-indicator { image: none; width: 0; } "
            "QPushButton { padding: 6px 16px; }")
        self.menu_columnas = CheckableMenu(self)
        self.columnas_actions = {}
        # V2.0.8: hasta columnCount() para que Peso y Sup. se puedan
        # ocultar/mostrar desde el menú igual que el resto
        for col_idx in range(5, self.tabla.columnCount()):
            h_item = self.tabla.horizontalHeaderItem(col_idx)
            # El tooltip solo sirve de nombre cuando la cabecera es una inicial
            # (L, T, F, S, P, M). Si ya es descriptiva se usa tal cual, o el
            # menú mostraría la explicación larga en vez del nombre corto.
            nombre_col = (h_item.text() if len(h_item.text()) > 2
                          else (h_item.toolTip() or h_item.text()))
            accion = self.menu_columnas.addAction(nombre_col)
            accion.setCheckable(True)
            accion.setChecked(True)
            accion.toggled.connect(lambda visible, c=col_idx: self._on_columna_toggled(c, visible))
            self.columnas_actions[col_idx] = accion
        self.btn_columnas.setMenu(self.menu_columnas)
        toolbar_layout.addWidget(self.btn_columnas)

        # Exportar (V2.0.0: movido del footer a la toolbar)
        self.btn_exportar = QPushButton("Exportar")
        self.btn_exportar.setIcon(svg_icon("exportar-descargar", size=15))
        self.btn_exportar.setToolTip("Exportar resultados a Excel (.csv)")
        self.btn_exportar.clicked.connect(self.exportar_excel_completo)
        self.btn_exportar.setCursor(Qt.PointingHandCursor)
        toolbar_layout.addWidget(self.btn_exportar)

        # V2.0.3: análisis sobre datos ya indexados
        self.btn_analisis = QPushButton("Análisis")
        self.btn_analisis.setIcon(svg_icon("fabricacion", size=15))
        self.btn_analisis.setToolTip("Análisis sobre el índice (candidatas a biblioteca...)")
        self.btn_analisis.setCursor(Qt.PointingHandCursor)
        self.menu_analisis = QMenu(self)
        self.menu_analisis.addAction(
            svg_icon("capas-tipos"), "Piezas más reutilizadas (candidatas a biblioteca)",
            self.mostrar_reutilizadas)
        # V2.2.0: los conjuntos que más vistas previas recuperan de una pasada
        self.menu_analisis.addAction(
            svg_icon("ensamblaje-cubo"), "Conjuntos con más piezas sin vista previa",
            self.mostrar_sin_vista_previa)
        self.btn_analisis.setMenu(self.menu_analisis)
        toolbar_layout.addWidget(self.btn_analisis)

        # Contenedor central: toolbar + stack de vistas (Lista / Galería)
        self.stack_vistas = QStackedWidget()
        self.stack_vistas.addWidget(self.tabla)

        # Vista Galería (V2.0.0)
        self.galeria = GaleriaArrastrable()
        self.galeria.zoom_callback = self._zoom_galeria_rueda  # V2.0.3: Ctrl+rueda
        pal_gal = self.galeria.palette()
        for grupo_pal in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            pal_gal.setColor(grupo_pal, QPalette.Highlight, QColor("#3A2C21"))
            pal_gal.setColor(grupo_pal, QPalette.HighlightedText, QColor("#F5F5F5"))
        self.galeria.setPalette(pal_gal)
        self.galeria.setIconSize(QSize(128, 128))
        self.galeria.setGridSize(QSize(180, 210))
        # V2.0.6: vista previa flotante en S/M/L (en XL la tarjeta ya es mayor
        # que la ventanita y HoverPreview se calla solo)
        self._hover_galeria = self._hover_lista(self.galeria)
        self.galeria.currentItemChanged.connect(self._on_galeria_seleccion)
        self.galeria.doubleClicked.connect(self.abrir_carpeta_seleccionada)
        self.galeria.setContextMenuPolicy(Qt.CustomContextMenu)
        self.galeria.customContextMenuRequested.connect(
            lambda pos: self.mostrar_menu_contextual(pos, origen_widget=self.galeria))
        self._galeria_items = {}  # ruta -> QListWidgetItem (para actualizar miniaturas)
        self.stack_vistas.addWidget(self.galeria)

        contenedor_central = QWidget()
        central_v = QVBoxLayout(contenedor_central)
        central_v.setContentsMargins(0, 0, 0, 0)
        central_v.setSpacing(6)
        central_v.addLayout(toolbar_layout)

        # ── V2.0.3: BARRA DE REFINADO (sub-búsqueda en cascada) ──
        # Niveles apilables con chips; Esc deshace el último; Ctrl+R enfoca.
        # Modo "Nombre" filtra EN VIVO mientras escribes; "Contiene pieza"
        # consulta la BD al pulsar Enter.
        self.barra_refinar = QFrame()
        self.barra_refinar.setObjectName("BarraRefinar")
        ref_lay = QHBoxLayout(self.barra_refinar)
        ref_lay.setContentsMargins(12, 6, 12, 6)
        ref_lay.setSpacing(8)

        ico_ref = QLabel()
        ico_ref.setPixmap(svg_pixmap("ensamblaje-cubo", color="#E66C32", size=15))
        ico_ref.setStyleSheet("background: transparent;")
        ref_lay.addWidget(ico_ref)

        # V2.0.8: la barra se lee como UNA FRASE — "De estos resultados, deja
        # los que [SI|NO] contengan [pieza]". Antes la etiqueta afirmaba "que
        # contengan" y al lado habia un boton que hacia lo contrario: el modo
        # estaba declarado en dos sitios que se contradecian, y no se entendia
        # que hacia cada cosa.
        lbl_ref = QLabel("De estos resultados, deja los que")
        lbl_ref.setToolTip(
            "Sub-busqueda sobre los resultados actuales (Ctrl+R).\n"
            "Filtra por lo que los ensamblajes LLEVAN DENTRO (su despiece),\n"
            "no por el nombre: para el nombre esta el buscador de arriba.\n"
            "Enter aplica y deja un chip; se pueden encadenar varios niveles.\n"
            "Sintaxis: espacio = frase exacta, ; = Y, , = O.\n"
            "Esc deshace el ultimo nivel hasta la busqueda general.")
        lbl_ref.setStyleSheet(
            f'font-family: "{FUENTES["h2"]}"; font-weight: 800; color: #E66C32; '
            f'background: transparent;')
        ref_lay.addWidget(lbl_ref)

        # Selector de modo SI/NO: excluyentes y siempre visibles, para que se
        # vea de un vistazo que existen las dos opciones y cual esta activa.
        self.grupo_modo_ref = QButtonGroup(self)
        self.grupo_modo_ref.setExclusive(True)
        self.btn_ref_si = QPushButton("SI contengan")
        self.btn_ref_no = QPushButton("NO contengan")
        for _b, _tip in (
            (self.btn_ref_si,
             "Dejar SOLO los ensamblajes que llevan esa pieza dentro.\n"
             "Ejemplo: cintas A450 -> SI contengan MOTOR REM 0.37KW."),
            (self.btn_ref_no,
             "Quitar los ensamblajes que llevan esa pieza; deja el resto.\n"
             "Ejemplo: cintas A450 -> NO contengan MOTOR REM = las que\n"
             "montan otro motor.\nAtajo: un '-' delante del termino y Enter.")):
            _b.setCheckable(True)
            _b.setCursor(Qt.PointingHandCursor)
            _b.setToolTip(_tip)
            self.grupo_modo_ref.addButton(_b)
            ref_lay.addWidget(_b)
        self.btn_ref_si.setChecked(True)
        self.grupo_modo_ref.buttonToggled.connect(lambda *_: self._pintar_modo_refinar())

        self.input_refinar = QLineEdit()
        self.input_refinar.setObjectName("InputRefinar")
        self.input_refinar.setClearButtonEnabled(True)
        self.input_refinar.returnPressed.connect(self._agregar_refinado)
        ref_lay.addWidget(self.input_refinar, stretch=1)

        # Boton de accion explicito: quien no sepa que Enter aplica, lo ve
        self.btn_ref_aplicar = QPushButton("Aplicar")
        self.btn_ref_aplicar.setCursor(Qt.PointingHandCursor)
        self.btn_ref_aplicar.setToolTip("Anadir este nivel de refinado (o pulsa Enter)")
        self.btn_ref_aplicar.clicked.connect(lambda _=False: self._agregar_refinado())
        ref_lay.addWidget(self.btn_ref_aplicar)

        # V2.0.3: profundidad — buscar también dentro de los subconjuntos
        self.btn_profundo = QPushButton("Subconjuntos")
        self.btn_profundo.setCheckable(True)
        self.btn_profundo.setCursor(Qt.PointingHandCursor)
        self.btn_profundo.setToolTip(
            "Buscar también DENTRO de los subconjuntos (cualquier nivel).\n"
            "Desactivado: solo componentes directos del despiece (más rápido).\n"
            "Activado: encuentra la pieza aunque esté dentro de un subconjunto\n"
            "del conjunto (tarda unos segundos más).")
        self.btn_profundo.toggled.connect(self._on_profundo_toggled)
        ref_lay.addWidget(self.btn_profundo)

        self.chips_refinar = QHBoxLayout()
        self.chips_refinar.setSpacing(4)
        ref_lay.addLayout(self.chips_refinar)

        self.btn_ref_limpiar = QPushButton("Limpiar")
        self.btn_ref_limpiar.setCursor(Qt.PointingHandCursor)
        self.btn_ref_limpiar.setToolTip("Quitar todos los niveles de refinado")
        self.btn_ref_limpiar.clicked.connect(self._limpiar_refinados)
        self.btn_ref_limpiar.setVisible(False)
        ref_lay.addWidget(self.btn_ref_limpiar)

        self._pintar_modo_refinar()   # estado inicial del selector SI/NO

        self.lbl_refinar_count = QLabel("")
        self.lbl_refinar_count.setStyleSheet(
            "color: #E66C32; font-weight: 700; background: transparent;")
        ref_lay.addWidget(self.lbl_refinar_count)

        self._pintar_estilo_refinar()
        self.barra_refinar.setVisible(False)
        central_v.addWidget(self.barra_refinar)

        central_v.addWidget(self.stack_vistas)

        self.splitter.addWidget(contenedor_central)

        # Panel Preview
        self.panel_preview = QFrame()
        self.panel_preview.setObjectName("panel_preview")
        self.panel_preview.setFrameStyle(QFrame.StyledPanel)
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(15)
        shadow_effect.setColor(QColor(0, 0, 0, 40))
        shadow_effect.setOffset(0, 4)
        self.panel_preview.setGraphicsEffect(shadow_effect)
        preview_layout = QVBoxLayout(self.panel_preview)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(10)

        # --- Tarjeta de imagen (lightbox) con altura fija: la miniatura de
        #     SolidWorks (fondo claro) queda enmarcada intencionalmente V2.0.1 ---
        self.preview_image_card = QFrame()
        self.preview_image_card.setObjectName("PreviewImage")
        # V2.0.3: altura ELÁSTICA — al ensanchar el panel (arrastrando el
        # divisor) la imagen crece con él; antes estaba fija a 210px y la
        # vista previa se quedaba pequeña por muy ancho que lo pusieras.
        self.preview_image_card.setMinimumHeight(210)
        self.preview_image_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        img_card_lay = QVBoxLayout(self.preview_image_card)
        img_card_lay.setContentsMargins(8, 8, 8, 8)
        # V2.0.1: label que pinta la imagen en su paintEvent → nunca desborda el
        # card, independiente del DPI del monitor (causa del desborde en pantallas
        # con escalado de Windows al 125/150%)
        self.lbl_preview_icon = PreviewImagenLabel()
        self.lbl_preview_icon.set_imagen(svg_pixmap("buscar", color="#777777", size=56))
        img_card_lay.addWidget(self.lbl_preview_icon)

        # V2.0.1: el QGraphicsOpacityEffect ya NO se adjunta al label — su caché
        # de render pintaba la miniatura desplazada (tapando el texto) y dejaba
        # el fantasma de la selección anterior. Los objetos se conservan porque
        # varios métodos legacy llaman a setOpacity()/anim (ahora inofensivos).
        self.preview_opacity = QGraphicsOpacityEffect()
        self.anim_opacity = QPropertyAnimation(self.preview_opacity, b"opacity")
        self.anim_opacity.setDuration(400)
        # stretch=1: el espacio libre del panel va a la IMAGEN (V2.0.3)
        preview_layout.addWidget(self.preview_image_card, stretch=1)

        # --- Nombre del archivo ---
        self.lbl_preview_nombre = QLabel("Seleccione un archivo")
        self.lbl_preview_nombre.setObjectName("FileName")
        self.lbl_preview_nombre.setAlignment(Qt.AlignLeft)
        self.lbl_preview_nombre.setWordWrap(True)
        preview_layout.addWidget(self.lbl_preview_nombre)

        # Píldora de tipo (Pieza/Ensamblaje/Plano/PDF)
        self.lbl_preview_pill = QLabel("")
        self.lbl_preview_pill.setVisible(False)
        preview_layout.addWidget(self.lbl_preview_pill, alignment=Qt.AlignLeft)

        # --- Metadatos como filas clave-valor ---
        self.meta_grid = QGridLayout()
        self.meta_grid.setContentsMargins(0, 4, 0, 4)
        self.meta_grid.setHorizontalSpacing(10)
        self.meta_grid.setVerticalSpacing(6)
        self.meta_grid.setColumnStretch(1, 1)
        self._meta_vals = {}
        self._meta_keys = {}
        for fila, (clave, etiqueta) in enumerate([
            ('origen', 'Origen'), ('anio', 'Año'), ('cliente', 'Cliente'),
            ('proyecto', 'Proyecto'), ('orden', 'Orden'), ('tamano', 'Tamaño'),
            # V2.0.3: documentación de la pieza y salud del ensamblaje
            ('plano', 'Plano'), ('comps', 'Componentes'),
            # V2.0.8: propiedades físicas leídas de SolidWorks
            # V2.0.8: solo Peso. La superficie se queda en la columna de la
            # lista: en el panel ocupaba sitio y, sobre todo, decía "a pintar"
            # sin saber si la pieza se pinta — afirmarlo era incorrecto.
            ('peso', 'Peso')]):
            lbl_k = QLabel(etiqueta)
            lbl_k.setObjectName("MetaKey")
            lbl_v = QLabel("—")
            lbl_v.setObjectName("MetaVal")
            lbl_v.setWordWrap(True)
            self.meta_grid.addWidget(lbl_k, fila, 0, Qt.AlignTop)
            self.meta_grid.addWidget(lbl_v, fila, 1, Qt.AlignTop)
            self._meta_vals[clave] = lbl_v
            self._meta_keys[clave] = lbl_k
        # Los enlaces "abrir" de Plano seleccionan el archivo en el Explorador
        self._meta_vals['plano'].linkActivated.connect(self._abrir_en_explorer)
        # V2.0.3: botón "Piezas similares" (solo piezas con material indexado)
        self.btn_similares = QPushButton("Piezas similares")
        self.btn_similares.setIcon(svg_icon("buscar", size=14))
        self.btn_similares.setCursor(Qt.PointingHandCursor)
        self.btn_similares.setVisible(False)
        self.btn_similares.clicked.connect(self.mostrar_similares)
        self.meta_widget = QWidget()
        self.meta_widget.setLayout(self.meta_grid)
        self.meta_widget.setVisible(False)
        preview_layout.addWidget(self.meta_widget)
        preview_layout.addWidget(self.btn_similares, alignment=Qt.AlignLeft)

        # Ruta completa (discreta, seleccionable)
        self.lbl_preview_ruta = QLabel("")
        self.lbl_preview_ruta.setWordWrap(True)
        self.lbl_preview_ruta.setStyleSheet("font-size: 9px; color: #6E6E6E;")
        self.lbl_preview_ruta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        preview_layout.addWidget(self.lbl_preview_ruta)

        # Compatibilidad: labels legacy que aún referencian otros métodos
        self.lbl_preview_tipo = QLabel("")
        self.lbl_preview_tipo.setVisible(False)
        self.lbl_preview_comp = QLabel("")
        self.lbl_preview_comp.setVisible(False)
        self.lbl_preview_proyecto = QLabel("")
        self.lbl_preview_proyecto.setVisible(False)
        self.lbl_preview_tamaño = self._meta_vals['tamano']

        # V2.0.3: sin stretch aquí — el espacio libre lo toma la tarjeta de
        # imagen (stretch=1), que es lo que interesa agrandar al ensanchar.

        tip_drag_layout = QHBoxLayout()
        tip_drag_layout.setSpacing(6)
        tip_drag_icon = QLabel()
        tip_drag_icon.setPixmap(svg_pixmap("arrastrar-solidworks", color="#777777", size=16))
        tip_drag = QLabel("Arrastra para abrir en SolidWorks")
        tip_drag.setStyleSheet("color: #777777; font-style: italic; font-size: 11px;")
        tip_drag_layout.addStretch()
        tip_drag_layout.addWidget(tip_drag_icon)
        tip_drag_layout.addWidget(tip_drag)
        tip_drag_layout.addStretch()
        preview_layout.addLayout(tip_drag_layout)

        self.splitter.addWidget(self.panel_preview)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        
        # ═══ V2.0.1 - Cada grupo de Propiedades SW es un acordeón independiente ═══
        # (antes iban apelotonados; ahora cada uno se expande/colapsa por separado
        #  y las listas muestran más filas)
        izq_layout = self._sidebar_layout

        # --- Fabricación (Láser/Torno/Fresa/Soldadura/Pintura/Montaje) ---
        sec_fabricacion = _acordeon('fabricacion', 'FABRICACIÓN', 'fabricacion', expandido=False)
        self.chk_laser = QCheckBox("Láser")
        self.chk_torno = QCheckBox("Torno")
        self.chk_fresa = QCheckBox("Fresa")
        self.chk_soldadura = QCheckBox("Soldadura")
        self.chk_pintura = QCheckBox("Pintura")
        self.chk_montaje = QCheckBox("Montaje")
        for chk in [self.chk_laser, self.chk_torno, self.chk_fresa, self.chk_soldadura, self.chk_pintura, self.chk_montaje]:
            sec_fabricacion.lay.addWidget(chk)
            chk.stateChanged.connect(self.ejecutar_busqueda)

        # --- Material ---
        sec_material = _acordeon('material', 'MATERIAL', 'propiedades-sliders', expandido=False)
        self.list_materiales = ListaFiltro()
        sec_material.lay.addWidget(self.list_materiales)
        self.add_toggle_buttons(sec_material.lay, self.list_materiales)
        self.list_materiales.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))

        # --- Tratamiento (valores oficiales de template_PZ.prtprp) ---
        sec_tratamiento = _acordeon('tratamiento', 'TRATAMIENTO', 'propiedades-sliders', expandido=False)
        self.list_tratamientos = ListaFiltro()
        TRATAMIENTOS_OFICIALES = [
            "ZINCADO", "CROMADO", "GRANALLADO", "VULCANIZADO", "VULCANIZADO ALIMENTARIO",
            "RAL 2010", "RAL 7000", "RAL 9003", "RAL 9006", "RAL 3020",
            "RAL 7047", "RAL 1018", "RAL 9005", "RAL 1021", "RAL 5018",
            "RAL 5021", "RAL 5003"
        ]
        for trat in TRATAMIENTOS_OFICIALES:
            item = QListWidgetItem(trat)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_tratamientos.addItem(item)
        sec_tratamiento.lay.addWidget(self.list_tratamientos)
        self.add_toggle_buttons(sec_tratamiento.lay, self.list_tratamientos)
        self.list_tratamientos.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))

        # --- Cierre ---
        sec_cierre = _acordeon('cierre', 'CIERRE', 'propiedades-sliders', expandido=False)
        self.list_cierres = ListaFiltro(ajustar_a_contenido=True)  # solo 5 cierres
        for cierre in ["SIN FIN", "CON GRAPA", "CON GRAPA OCULTA", "ABIERTA", "CON GRAPA EN UN LADO"]:
            item = QListWidgetItem(cierre)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_cierres.addItem(item)
        sec_cierre.lay.addWidget(self.list_cierres)
        self.add_toggle_buttons(sec_cierre.lay, self.list_cierres)
        self.list_cierres.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))

        # --- Tipo de Banda (independiente) ---
        sec_banda = _acordeon('banda', 'TIPO DE BANDA', 'propiedades-sliders', expandido=False)
        self.chk_filo_guiado = QCheckBox("Filo Guiado")
        self.chk_onda = QCheckBox("Onda")
        self.chk_cangilon = QCheckBox("Cangilón")
        self.chk_runer = QCheckBox("Runer")
        for chk in [self.chk_filo_guiado, self.chk_onda, self.chk_cangilon, self.chk_runer]:
            sec_banda.lay.addWidget(chk)
            chk.stateChanged.connect(self.ejecutar_busqueda)

        # --- Espesor (independiente, 1-20mm) ---
        sec_espesor = _acordeon('espesor', 'ESPESOR', 'propiedades-sliders', expandido=False)
        self.list_espesores = ListaFiltro()
        for mm in range(1, 21):
            item = QListWidgetItem(f"{mm}mm")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_espesores.addItem(item)
        sec_espesor.lay.addWidget(self.list_espesores)
        self.add_toggle_buttons(sec_espesor.lay, self.list_espesores)
        self.list_espesores.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))

        izq_layout.addStretch()

        # Raíl de iconos para el sidebar contraído (V2.0.1)
        self.rail_widget = QWidget()
        rail_lay = QVBoxLayout(self.rail_widget)
        rail_lay.setContentsMargins(0, 4, 0, 4)
        rail_lay.setSpacing(8)
        for clave, sec in self.acordeones.items():
            if not sec.icono:
                continue
            btn_rail = QPushButton()
            btn_rail.setIcon(svg_icon(sec.icono, size=18))
            btn_rail.setToolTip(sec.titulo.title())
            btn_rail.setCursor(Qt.PointingHandCursor)
            btn_rail.setFixedSize(32, 32)
            btn_rail.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 8px; padding: 0; } "
                "QPushButton:hover { background: #3A2C21; }")
            btn_rail.clicked.connect(lambda _, s=sec: self._abrir_desde_rail(s))
            rail_lay.addWidget(btn_rail, alignment=Qt.AlignHCenter)
        rail_lay.addStretch()
        self.rail_widget.setVisible(False)
        self._izq_outer_layout.addWidget(self.rail_widget)

        # Splitter principal: sidebar + zona central (ya sin panel derecho)
        self.main_splitter.addWidget(self.splitter)
        self.main_splitter.setStretchFactor(1, 1)
        
        # Restaurar ancho guardado (Persistencia)
        saved_width = self.controller.load_preference('sidebar_width')
        if saved_width:
             self.main_splitter.setSizes([int(saved_width), 1200, 200])
        else:
             self.main_splitter.setSizes([240, 1200, 200]) # Default original

        # Zona central con su propio padding (el main_layout va a sangre V2.0.1)
        zona_central = QWidget()
        zona_central_lay = QVBoxLayout(zona_central)
        zona_central_lay.setContentsMargins(12, 8, 12, 8)
        zona_central_lay.setSpacing(0)
        zona_central_lay.addWidget(self.main_splitter)
        main_layout.addWidget(zona_central, stretch=1)

        # PIE DE PÁGINA (Botones y Estado)
        # ═══════════════════════════════════════════
        self.footer_frame = QFrame()
        self.footer_frame.setObjectName("Footer")
        footer_layout = QHBoxLayout(self.footer_frame)
        footer_layout.setContentsMargins(10, 6, 10, 6)
        footer_layout.setSpacing(10)
        
        # Botones de Acción Rápida (V1.0.0)
        self.btn_abrir_carpeta = QPushButton("Abrir Carpeta")
        self.btn_abrir_carpeta.setIcon(svg_icon("carpeta"))
        self.btn_abrir_carpeta.setToolTip("Abre la carpeta que contiene el archivo")
        self.btn_abrir_carpeta.clicked.connect(self.abrir_carpeta_seleccionada)
        self.btn_abrir_carpeta.setEnabled(False)
        self.btn_abrir_carpeta.setCursor(Qt.PointingHandCursor)
        footer_layout.addWidget(self.btn_abrir_carpeta)
        
        self.btn_copiar_ruta = QPushButton("Copiar Ruta")
        self.btn_copiar_ruta.setIcon(svg_icon("copiar-ruta"))
        self.btn_copiar_ruta.setToolTip("Copia la ruta completa al portapapeles")
        self.btn_copiar_ruta.clicked.connect(self.copiar_ruta_seleccionada)
        self.btn_copiar_ruta.setEnabled(False)
        self.btn_copiar_ruta.setCursor(Qt.PointingHandCursor)
        footer_layout.addWidget(self.btn_copiar_ruta)
        
        self.btn_copiar_nombre = QPushButton("Copiar Nombre")
        self.btn_copiar_nombre.setIcon(svg_icon("copiar-nombre-lapiz"))
        self.btn_copiar_nombre.setToolTip("Copia solo el nombre del archivo (Ctrl+C)")
        self.btn_copiar_nombre.clicked.connect(self.copiar_nombre_seleccionado)
        self.btn_copiar_nombre.setEnabled(False)
        self.btn_copiar_nombre.setCursor(Qt.PointingHandCursor)
        footer_layout.addWidget(self.btn_copiar_nombre)
        
        # V2.0.0: Exportar vive ahora en la toolbar central (self.btn_exportar).
        # El combo de densidad se conserva oculto como fuente de verdad; lo
        # manejan los botones segmentados Cómoda/Compacta de la toolbar.
        self.combo_densidad = QComboBox()
        self.combo_densidad.setView(QListView())
        self.combo_densidad.setMaxVisibleItems(10)
        self.combo_densidad.addItems(["Cómoda", "Compacta"])
        self.combo_densidad.currentIndexChanged.connect(self.cambiar_densidad_tabla)
        self.combo_densidad.setVisible(False)
        footer_layout.addWidget(self.combo_densidad)

        # Separador visual
        line_sep = QFrame()
        line_sep.setFrameShape(QFrame.VLine)
        line_sep.setFrameShadow(QFrame.Sunken)
        footer_layout.addWidget(line_sep)
        # Botón Reindexar NAS (v1.0.7 - sustituye 3 botones anteriores)
        self.btn_indexar = QPushButton("Reindexar NAS")
        self.btn_indexar.setToolTip("Abre el diálogo para elegir qué orígenes indexar del NAS")
        self.btn_indexar.setIcon(svg_icon("reindexar-refrescar"))
        self.btn_indexar.setFixedWidth(185)
        self.btn_indexar.clicked.connect(self.confirmar_indexacion)
        footer_layout.addWidget(self.btn_indexar)
        
        # Botón Ocultar/Mostrar panel (Movido desde el panel derecho)
        self.btn_toggle_preview = QPushButton("Ocultar Previsualizador")
        self.btn_toggle_preview.setIcon(svg_icon("contraer-panel"))
        self.btn_toggle_preview.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_preview.clicked.connect(self.toggle_preview_panel)
        footer_layout.addWidget(self.btn_toggle_preview)
        
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setToolTip("Detiene la indexación actual")
        self.btn_cancelar.setCursor(Qt.PointingHandCursor)
        self.btn_cancelar.setMinimumHeight(35)
        self.btn_cancelar.setObjectName("btn_cancelar")
        self.btn_cancelar.setFixedWidth(100)
        self.btn_cancelar.setVisible(False)
        self.btn_cancelar.clicked.connect(self.cancelar_indexacion)
        footer_layout.addWidget(self.btn_cancelar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setToolTip("Progreso de la indexación de archivos")
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setRange(0, 0)
        footer_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Listo")
        self.lbl_status.setObjectName("StatusOk")
        footer_layout.addWidget(self.lbl_status, stretch=1)

        # V2.0.0: estado del índice (color por antigüedad, clic → reindexar)
        self.lbl_estado_indice = QLabel("")
        self.lbl_estado_indice.setObjectName("StatusDim")
        self.lbl_estado_indice.setTextFormat(Qt.RichText)
        self.lbl_estado_indice.setCursor(Qt.PointingHandCursor)
        self.lbl_estado_indice.mousePressEvent = lambda ev: self.confirmar_indexacion()
        footer_layout.addWidget(self.lbl_estado_indice)
        QTimer.singleShot(1500, self._actualizar_estado_indice)
        # Refresco periódico para que el color/antigüedad se mantengan al día
        self._timer_estado_indice = QTimer(self)
        self._timer_estado_indice.timeout.connect(self._actualizar_estado_indice)
        self._timer_estado_indice.start(10 * 60 * 1000)  # cada 10 min

        # Botones de Ayuda e Info (V2.0.0: botones redondos #RoundBtn del QSS)
        self.btn_ayuda = QPushButton("?")
        self.btn_ayuda.setObjectName("RoundBtn")
        self.btn_ayuda.setToolTip("Guía de uso rápida")
        self.btn_ayuda.setStatusTip("Botón de ayuda")
        self.btn_ayuda.setCursor(Qt.PointingHandCursor)
        self.btn_ayuda.clicked.connect(self.mostrar_ayuda)
        footer_layout.addWidget(self.btn_ayuda)

        self.btn_info = QPushButton("i")
        self.btn_info.setObjectName("RoundBtn")
        self.btn_info.setToolTip("Acerca de") # Tooltip simplificado
        self.btn_info.setStatusTip("Información de la aplicación")
        self.btn_info.setCursor(Qt.PointingHandCursor)
        self.btn_info.clicked.connect(self.mostrar_info)
        footer_layout.addWidget(self.btn_info)

        self.lbl_count = QLabel("0 resultados")
        self.lbl_count.setObjectName("StatusCount")
        footer_layout.addWidget(self.lbl_count)

        main_layout.addWidget(self.footer_frame)

        self._restaurar_config_ui()
        self.actualizar_estilos()

    # ═══════════════════════════════════════════
    # CONFIG UI V2.0.0 (QSettings: densidad, columnas, vista)
    # ═══════════════════════════════════════════
    def _on_densidad_segment(self, index):
        """Los segmentos Cómoda/Compacta manejan el combo oculto (fuente de verdad)."""
        self.combo_densidad.setCurrentIndex(index)
        self.qsettings.setValue("densidad", index)

    def _on_columna_toggled(self, col, visible):
        self.tabla.setColumnHidden(col, not visible)
        ocultas = [str(c) for c, a in self.columnas_actions.items() if not a.isChecked()]
        self.qsettings.setValue("columnas_ocultas", ",".join(ocultas))

    def _restaurar_config_ui(self):
        """Restaura densidad, columnas visibles, vista y tamaño galería desde QSettings."""
        try:
            densidad = int(self.qsettings.value("densidad", 0))
            if densidad == 1:
                self.btn_dens_compacta.setChecked(True)
                self.combo_densidad.setCurrentIndex(1)
            ocultas = self.qsettings.value("columnas_ocultas", "")
            if ocultas:
                for c_str in str(ocultas).split(','):
                    col = int(c_str)
                    if col in self.columnas_actions:
                        self.columnas_actions[col].setChecked(False)
                        self.tabla.setColumnHidden(col, True)
            # V2.0.3: se restaura el zoom exacto (px). Si el equipo solo tiene la
            # preferencia antigua S/M/L, se traduce a su preset.
            zoom = self.qsettings.value("galeria_zoom", None)
            if zoom is None:
                tam = int(self.qsettings.value("galeria_tam", 1))
                zoom = self.TAM_GALERIA_PX[max(0, min(tam, len(self.TAM_GALERIA_PX) - 1))]
            zoom = max(self.ZOOM_MIN, min(int(zoom), self.ZOOM_MAX))
            self.slider_zoom.blockSignals(True)
            self.slider_zoom.setValue(zoom)
            self.slider_zoom.blockSignals(False)
            self._aplicar_zoom_galeria(zoom, guardar=False)
            # V2.0.3: profundidad de búsqueda (local por equipo)
            if int(self.qsettings.value("busqueda_profunda", 0)) == 1:
                self.btn_profundo.blockSignals(True)
                self.btn_profundo.setChecked(True)
                self.btn_profundo.blockSignals(False)
                self._pintar_estilo_refinar()
            if int(self.qsettings.value("vista_modo", 0)) == 1:
                self.btn_vista_galeria.setChecked(True)
                self._cambiar_vista(1)
            # V2.0.1: barra de contexto y estado del sidebar
            self._refrescar_recientes()
            self._refrescar_guardadas()
            if int(self.qsettings.value("sidebar_colapsado", 0)) == 1:
                self._toggle_sidebar(True)
        except Exception as e:
            logger.debug(f"Error restaurando config UI: {e}")

    # ═══════════════════════════════════════════
    # VISTA GALERÍA (V2.0.0)
    # ═══════════════════════════════════════════
    def _cambiar_vista(self, index):
        """Conmuta Lista (0) / Galería (1)."""
        self.stack_vistas.setCurrentIndex(index)
        # Cómoda/Compacta solo aplica a la Lista; S/M/L solo a la Galería
        self.seg_dens_container.setVisible(index == 0)
        self.seg_tam_container.setVisible(index == 1)
        self.slider_zoom.setVisible(index == 1)  # V2.0.3: zoom solo en galería
        if index == 1:
            self._sincronizar_galeria()
        self.qsettings.setValue("vista_modo", index)

    # V2.0.3: presets S/M/L/XL en px de icono + zoom continuo con el deslizador
    ZOOM_MIN, ZOOM_MAX = 72, 420
    TAM_GALERIA_PX = [96, 128, 160, 260]  # S, M, L, XL

    def _grid_para_icono(self, icono):
        """Celda que envuelve al icono dejando sitio para 2-3 líneas de texto."""
        return QSize(icono + 54, icono + int(icono * 0.28) + 42)

    def _pixmap_para_galeria(self, pm):
        """Escala un pixmap AL TAMAÑO DE ICONO ACTUAL de la galería (V2.0.3).
        Clave: QIcon nunca amplía por encima del pixmap que se le da — si se
        guardaba a 160px, en XL (260) las tarjetas se separaban pero la imagen
        seguía igual de pequeña.

        Parche sobre V2.0.4: SIN tope por resolución nativa. El tope anterior (2x el
        original) hacía que los DWG dejasen de crecer a mitad del deslizador:
        su previsualización embebida es de 163x97 px (la de SolidWorks/PDF es
        de 256), así que se congelaban en 326 px mientras el resto llegaba a
        420. Ahora TODAS las tarjetas escalan al mismo lado mayor, sea cual sea
        el formato de origen."""
        if pm is None or pm.isNull():
            return pm
        objetivo = self.galeria.iconSize().width() or 128
        return pm.scaled(objetivo, objetivo, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _aplicar_zoom_galeria(self, icono, guardar=True):
        """Aplica un tamaño de icono ARBITRARIO a la galería (V2.0.3)."""
        icono = max(self.ZOOM_MIN, min(int(icono), self.ZOOM_MAX))
        self.galeria.setIconSize(QSize(icono, icono))
        self.galeria.setGridSize(self._grid_para_icono(icono))
        # Forzar recomposición inmediata para que las etiquetas se pinten ya
        self.galeria.doItemsLayout()
        self.galeria.viewport().update()
        # Los iconos ya creados tienen el tamaño ANTERIOR: hay que regenerarlos
        # para que la imagen crezca (no solo la celda). Con debounce para que
        # arrastrar el deslizador no reconstruya la galería en cada píxel.
        if self.stack_vistas.currentIndex() == 1 and self.galeria.count():
            if not hasattr(self, '_timer_regen_galeria'):
                self._timer_regen_galeria = QTimer(self)
                self._timer_regen_galeria.setSingleShot(True)
                self._timer_regen_galeria.setInterval(180)
                self._timer_regen_galeria.timeout.connect(self._sincronizar_galeria)
            self._timer_regen_galeria.start()
        # Marcar el preset correspondiente (si coincide) sin relanzar señales
        botones = [self.btn_tam_s, self.btn_tam_m, self.btn_tam_l, self.btn_tam_xl]
        for b, px in zip(botones, self.TAM_GALERIA_PX):
            b.blockSignals(True)
            b.setChecked(px == icono)
            b.blockSignals(False)
        if guardar:
            self.qsettings.setValue("galeria_zoom", icono)
        return icono

    def _aplicar_tam_galeria(self, index):
        """Preset S/M/L/XL (compatibilidad con la preferencia antigua)."""
        icono = self.TAM_GALERIA_PX[max(0, min(index, len(self.TAM_GALERIA_PX) - 1))]
        self.slider_zoom.blockSignals(True)
        self.slider_zoom.setValue(icono)
        self.slider_zoom.blockSignals(False)
        self._aplicar_zoom_galeria(icono)

    def _cambiar_tam_galeria(self, index):
        self._aplicar_tam_galeria(index)
        self.qsettings.setValue("galeria_tam", index)

    def _on_zoom_galeria(self, valor):
        """Deslizador movido: tamaño libre."""
        self._aplicar_zoom_galeria(valor)

    def _zoom_galeria_rueda(self, delta):
        """Ctrl + rueda sobre la galería: zoom en pasos de 16 px (V2.0.3)."""
        paso = 16 if delta > 0 else -16
        nuevo = max(self.ZOOM_MIN, min(self.slider_zoom.value() + paso, self.ZOOM_MAX))
        self.slider_zoom.setValue(nuevo)  # dispara _on_zoom_galeria

    def _sincronizar_galeria(self):
        """Reconstruye las tarjetas de la galería a partir de la tabla (fuente
        de verdad), POR TRAMOS para no congelar la UI con miles de tarjetas
        (V2.0.3: pintar 5000 tarjetas de golpe congelaba la app ~10s)."""
        self._gen_galeria = getattr(self, '_gen_galeria', 0) + 1
        self.galeria.blockSignals(True)
        self.galeria.clear()
        self.galeria.blockSignals(False)
        self._galeria_items = {}
        self._gal_fill = {'gen': self._gen_galeria, 'r': 0}
        self._llenar_tramo_galeria()

    _TRAMO_TARJETAS = 400

    def _llenar_tramo_galeria(self):
        st = getattr(self, '_gal_fill', None)
        if not st or st['gen'] != getattr(self, '_gen_galeria', 0):
            return  # relevada por otra sincronización
        try:
            self.galeria.blockSignals(True)
            self.galeria.setUpdatesEnabled(False)
            total = self.tabla.rowCount()
            ini = st['r']
            fin = min(ini + self._TRAMO_TARJETAS, total)

            # V2.0.3: lote de miniaturas de BD para ESTE tramo (una consulta).
            # A 160px fijos: nítidas en tamaño L y con memoria acotada. El icono
            # de la celda de tabla NO sirve aquí (está reducido a ~50px y Qt no
            # amplía: salían miniaturas enanas).
            rutas_tramo = []
            for r in range(ini, fin):
                it = self.tabla.item(r, 0)
                if it:
                    rutas_tramo.append(it.text())
            minis_bd = {}
            try:
                minis_bd = self.db.obtener_miniaturas_lote(rutas_tramo)
            except Exception as e:
                logger.debug(f"Lote de galería falló: {e}")

            for r in range(ini, fin):
                item_ruta = self.tabla.item(r, 0)
                item_nombre = self.tabla.item(r, 5)
                if not item_ruta or not item_nombre:
                    continue
                ruta = item_ruta.text()
                nombre = item_nombre.text()
                cliente = self.tabla.item(r, 8).text() if self.tabla.item(r, 8) else ""
                año = self.tabla.item(r, 7).text() if self.tabla.item(r, 7) else ""
                material = self.tabla.item(r, 11).text() if self.tabla.item(r, 11) else ""
                meta = " · ".join([p for p in (cliente, año, material) if p])
                card = QListWidgetItem(f"{nombre}\n{meta}")
                card.setData(Qt.UserRole, ruta)
                card.setToolTip(f"{nombre}\n{meta}\n{ruta}")
                card.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
                icono_puesto = False
                data_bd = minis_bd.get(ruta)
                if data_bd:
                    img = QImage.fromData(data_bd)
                    if not img.isNull():
                        card.setIcon(QIcon(self._pixmap_para_galeria(
                            QPixmap.fromImage(img))))
                        icono_puesto = True
                if not icono_puesto:
                    pm_full = self.cache_miniaturas.get((ruta, 256))
                    if pm_full and not pm_full.isNull():
                        card.setIcon(QIcon(self._pixmap_para_galeria(pm_full)))
                    else:
                        ext = Path(nombre).suffix.lower()
                        if ext not in self._badge_cache:
                            self._badge_cache[ext] = QIcon(pixmap_badge_extension(ext, size=48))
                        card.setIcon(self._badge_cache[ext])
                self.galeria.addItem(card)
                self._galeria_items[ruta] = card
            st['r'] = fin
        except Exception as e:
            logger.debug(f"Error sincronizando galería: {e}")
            st['r'] = self.tabla.rowCount()  # abortar tramos restantes
        finally:
            self.galeria.setUpdatesEnabled(True)
            self.galeria.blockSignals(False)
        if st['r'] < self.tabla.rowCount():
            QTimer.singleShot(0, self._llenar_tramo_galeria)

    def _set_preview_imagen(self, pixmap):
        """Muestra la miniatura en el label auto-contenido (paintEvent la ajusta)."""
        self.lbl_preview_icon.set_imagen(pixmap)

    def _on_galeria_seleccion(self, current, previous=None):
        """Selección en galería → selecciona la fila equivalente en la tabla
        (dispara actualizar_preview y habilita los botones del footer)."""
        if not current:
            return
        ruta = current.data(Qt.UserRole)
        if not ruta:
            return
        for r in range(self.tabla.rowCount()):
            item = self.tabla.item(r, 0)
            if item and item.text() == ruta:
                self.tabla.selectRow(r)
                return

    # ═══════════════════════════════════════════
    # BARRA DE CONTEXTO (V2.0.1): chips activos, Limpiar, Recientes, Guardadas
    # ═══════════════════════════════════════════
    # ═══════════════════════════════════════════
    # SIDEBAR COLAPSABLE A RAÍL (V2.0.1)
    # ═══════════════════════════════════════════
    def _toggle_sidebar(self, colapsar=None):
        """Contrae el sidebar a un raíl de iconos de 56px o lo expande."""
        try:
            actual = not self._scroll_filtros.isVisible()
            colapsar = (not actual) if colapsar is None else colapsar
            if colapsar:
                self._scroll_filtros.setVisible(False)
                self._lbl_panel_filtros.setVisible(False)
                self.rail_widget.setVisible(True)
                self._panel_izquierdo.setMinimumWidth(56)
                self._panel_izquierdo.setMaximumWidth(56)
                # V2.0.8: hay que repartir el espacio liberado A MANO. Fijar el
                # ancho del panel no mueve el divisor: este se quedaba con el
                # reparto anterior y dejaba un hueco muerto entre el raíl y la
                # tabla, en vez de que la búsqueda ocupara todo el ancho.
                sizes = self.main_splitter.sizes()
                if len(sizes) >= 2:
                    ganado = sizes[0] - 56
                    sizes[0] = 56
                    sizes[1] = sizes[1] + max(ganado, 0)
                    self.main_splitter.setSizes(sizes)
                self.btn_colapsar_sidebar.setIcon(svg_icon("expandir-panel", size=14))
                self.btn_colapsar_sidebar.setToolTip("Expandir panel de filtros")
            else:
                self.rail_widget.setVisible(False)
                self._scroll_filtros.setVisible(True)
                self._lbl_panel_filtros.setVisible(True)
                self._panel_izquierdo.setMinimumWidth(80)
                self._panel_izquierdo.setMaximumWidth(500)
                sizes = self.main_splitter.sizes()
                if len(sizes) >= 2 and sizes[0] < 200:
                    devuelto = 256 - sizes[0]
                    sizes[0] = 256
                    sizes[1] = max(sizes[1] - devuelto, 300)
                    self.main_splitter.setSizes(sizes)
                self.btn_colapsar_sidebar.setIcon(svg_icon("contraer-panel", size=14))
                self.btn_colapsar_sidebar.setToolTip("Contraer panel de filtros")
            self.qsettings.setValue("sidebar_colapsado", 1 if colapsar else 0)
        except Exception as e:
            logger.debug(f"Error conmutando sidebar: {e}")

    def _abrir_desde_rail(self, seccion):
        """Clic en un icono del raíl: expande el sidebar y abre esa sección."""
        self._toggle_sidebar(False)
        seccion.btn_header.setChecked(True)

    def _vaciar_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _chip_activo(self, texto, on_reset):
        """Chip de filtro activo con botón × para quitarlo."""
        marco = QFrame()
        marco.setObjectName("ActiveChip")
        lay = QHBoxLayout(marco)
        lay.setContentsMargins(10, 2, 6, 2)
        lay.setSpacing(4)
        lbl = QLabel(texto)
        lbl.setObjectName("ActiveChipText")
        btn = QPushButton("×")
        btn.setFixedSize(16, 16)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #F0A377; "
            "font-weight: 800; font-size: 13px; padding: 0; } "
            "QPushButton:hover { color: #FFFFFF; }")
        # V2.0.3: absorber el 'checked' que Qt pasa en clicked — si no, el bool
        # ocupa el primer parámetro de la lambda (p. ej. lambda lw=lw: ...) y
        # peta con "'bool' object has no attribute 'blockSignals'" (chip Clientes)
        btn.clicked.connect(lambda _checked=False: on_reset())
        lay.addWidget(lbl)
        lay.addWidget(btn)
        return marco

    def _set_all_items(self, list_widget, checked):
        """Marca/desmarca todos los items de golpe y dispara una sola cascada."""
        list_widget.blockSignals(True)
        estado = Qt.Checked if checked else Qt.Unchecked
        for i in range(list_widget.count()):
            list_widget.item(i).setCheckState(estado)
        list_widget.blockSignals(False)
        if list_widget is self.list_años:
            for chip in self.chips_años.values():
                chip.blockSignals(True)
                chip.setChecked(checked)
                chip.blockSignals(False)
        self.on_filtro_jerarquico_changed(None)

    def _quitar_exclusion(self, palabra):
        """Quita un «-palabra» del buscador y repite la búsqueda (V2.1.4).

        El término se reconstruye desde la gramática, no recortando texto:
        así da igual cómo se escribiera ('-banda', '; - banda', 'cinta -banda')
        y el resultado siempre vuelve a ser una búsqueda válida."""
        inc, exc, modo_and = self.db.parsear_termino(self.input_buscar.text())
        exc = [e for e in exc if e != palabra]
        sep = '; ' if modo_and else ', '
        partes = list(inc) + ['-' + e for e in exc]
        self.input_buscar.setText(sep.join(partes))
        self._excluidas_activas = exc
        if partes:
            self.ejecutar_busqueda(auto=True)
        else:
            self._actualizar_chips_contexto()
    def _actualizar_chips_contexto(self):
        """Reconstruye los chips de filtros activos bajo el buscador."""
        try:
            self._vaciar_layout(self.chips_activos_lay)
            chips = []

            def contar(lw):
                total = lw.count()
                marcados = sum(1 for i in range(total) if lw.item(i).checkState() == Qt.Checked)
                return total, marcados

            t, m = contar(self.list_companeros)
            if m < t:
                chips.append((f"Origen: {m}/{t}", lambda: self._set_all_items(self.list_companeros, True)))

            t, m = contar(self.list_años)
            if 0 < m < t:
                años_sel = [self.list_años.item(i).text() for i in range(t)
                            if self.list_años.item(i).checkState() == Qt.Checked]
                etiqueta = f"Años: {años_sel[-1]}–{años_sel[0]}" if len(años_sel) > 1 else f"Año: {años_sel[0]}"
                chips.append((etiqueta, lambda: self._set_all_items(self.list_años, True)))

            t, m = contar(self.list_carpetas)
            if m < t:
                chips.append((f"Carpetas: {m}/{t}", lambda: self._set_all_items(self.list_carpetas, True)))

            tipos_total = len(self.tipos_actions)
            tipos_sel = sum(1 for a in self.tipos_actions.values() if a.isChecked())
            if tipos_sel < tipos_total:
                chips.append((f"Tipos: {tipos_sel}/{tipos_total}", self._reset_tipos))

            for lw, nombre in ((self.list_clientes, "Clientes"), (self.list_proyectos, "Proyectos")):
                t, m = contar(lw)
                if m > 0:
                    chips.append((f"{nombre}: {m}", lambda lw=lw: self._set_all_items(lw, False)))

            for lw, nombre in ((self.list_materiales, "Material"), (self.list_tratamientos, "Tratamiento"),
                               (self.list_cierres, "Cierre"), (self.list_espesores, "Espesor")):
                t, m = contar(lw)
                if m > 0:
                    chips.append((f"{nombre}: {m}", lambda lw=lw: self._reset_lista_propiedades(lw)))

            chks_fab = [self.chk_laser, self.chk_torno, self.chk_fresa,
                        self.chk_soldadura, self.chk_pintura, self.chk_montaje]
            n_fab = sum(1 for c in chks_fab if c.isChecked())
            if n_fab:
                chips.append((f"Fabricación: {n_fab}", lambda: self._reset_checks(chks_fab)))

            chks_banda = [self.chk_filo_guiado, self.chk_onda, self.chk_cangilon, self.chk_runer]
            n_banda = sum(1 for c in chks_banda if c.isChecked())
            if n_banda:
                chips.append((f"Banda: {n_banda}", lambda: self._reset_checks(chks_banda)))

            # V2.1.0 - Toggle Placa CE activo
            if self.btn_placa_ce.isChecked():
                chips.append(("Solo placa CE", lambda: self.btn_placa_ce.setChecked(False)))
            # V2.1.4: cada '-palabra' se ve como chip y se quita de un clic.
            # Sin esto, un resultado corto por una exclusión olvidada no tiene
            # explicación visible en pantalla.
            for _p in reversed(getattr(self, '_excluidas_activas', []) or []):
                chips.insert(0, ('Sin «%s»' % _p,
                                 lambda p=_p: self._quitar_exclusion(p)))
            # V2.0.3: modo "conjuntos que lo lleven" bien visible y quitable
            if getattr(self, 'modo_busqueda', 'nombre') == 'contiene':
                chips.insert(0, ("Conjuntos que lo lleven",
                                 lambda: self._set_modo_busqueda('nombre')))

            for texto, cb in chips[:8]:
                self.chips_activos_lay.addWidget(self._chip_activo(texto, cb))
            self.btn_limpiar.setVisible(bool(chips))

            # V2.0.0: indicadores ● en las cabeceras de acordeón del sidebar
            estados = {}
            t, m = contar(self.list_companeros)
            estados['origen'] = m < t
            t, m = contar(self.list_años)
            estados['años'] = 0 < m < t
            t, m = contar(self.list_carpetas)
            estados['carpetas'] = m < t
            estados['clientes'] = contar(self.list_clientes)[1] > 0
            estados['proyectos'] = contar(self.list_proyectos)[1] > 0
            estados['material'] = contar(self.list_materiales)[1] > 0
            estados['tratamiento'] = contar(self.list_tratamientos)[1] > 0
            estados['cierre'] = contar(self.list_cierres)[1] > 0
            estados['espesor'] = contar(self.list_espesores)[1] > 0
            estados['fabricacion'] = n_fab > 0
            estados['banda'] = n_banda > 0
            for clave, sec in self.acordeones.items():
                sec.set_activo(estados.get(clave, False))
        except Exception as e:
            logger.debug(f"Error actualizando chips de contexto: {e}")

    # ═══════════════════════════════════════════
    # AUTO-ACTUALIZACIÓN (V2.0.0)
    # ═══════════════════════════════════════════
    @staticmethod
    def _version_tuple(v):
        """'v2.0.1' → (2,0,1) para comparar. Tolera prefijo 'v' y texto extra."""
        import re as _re
        nums = _re.findall(r'\d+', (v or "").strip())
        return tuple(int(n) for n in nums[:3]) if nums else (0,)

    def _comprobar_actualizacion(self):
        """Lee version.txt de la carpeta de red y, si hay una versión más nueva
        que la instalada, muestra el banner de actualización (V2.0.0)."""
        try:
            version_file = os.path.join(RUTA_DESPLIEGUE_APP, "version.txt")
            if not os.path.exists(version_file):
                return
            with open(version_file, encoding="utf-8", errors="ignore") as f:
                v_red = f.read().strip()
            if not v_red:
                return
            self._version_red = v_red
            if self._version_tuple(v_red) > self._version_tuple(APP_VERSION):
                self.lbl_update.setText(
                    f"Actualización disponible: {v_red}  (tienes la v{APP_VERSION})")
                self.update_banner.setVisible(True)
                logger.info(f"Actualización disponible: red={v_red} local={APP_VERSION}")
        except Exception as e:
            logger.debug(f"Error comprobando actualización: {e}")

    @staticmethod
    def _entorno_sin_pyinstaller():
        """Entorno para procesos hijo, sin rastro de PyInstaller (V2.0.9).

        Quitar las variables _MEI*/_PYI* no basta: el bootloader deja además
        la carpeta temporal (sys._MEIPASS) DENTRO del PATH, y ahí viven
        VCRUNTIME140.dll y compañía. Cualquier ejecutable del sistema lanzado
        con ese PATH puede cargar ESAS DLL en vez de las suyas y morir con
        0xc0000142 (DLL_INIT_FAILED) — que es justo lo que le pasó a un
        compañero con taskkill.exe al actualizar.
        """
        entorno = {k: v for k, v in os.environ.items()
                   if not k.startswith(('_MEI', '_PYI'))}
        mei = getattr(sys, '_MEIPASS', None)
        mei_norm = os.path.normcase(os.path.normpath(mei)) if mei else None

        def es_de_pyinstaller(parte):
            if not parte.strip():
                return True
            try:
                pn = os.path.normcase(os.path.normpath(parte))
            except Exception:
                return False
            if mei_norm and (pn == mei_norm or pn.startswith(mei_norm + os.sep)):
                return True
            # Carpetas _MEIxxxxx de ejecuciones anteriores que quedaron sueltas.
            # Se miran TODOS los tramos, no solo el ultimo: rutas como
            # ...\_MEI999\lib tambien apuntan a un empaquetado.
            return any(t.lower().startswith('_mei') for t in pn.split(os.sep) if t)

        ruta = entorno.get('PATH', '')
        limpio = [p for p in ruta.split(os.pathsep) if not es_de_pyinstaller(p)]
        if limpio:
            entorno['PATH'] = os.pathsep.join(limpio)
        entorno['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        return entorno

    def _lanzar_actualizacion(self):
        """Cierra la app y lanza un actualizador que copia la versión nueva desde
        la carpeta de red al equipo local y la reabre (V2.0.0)."""
        try:
            local_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ALSI_Buscador")
            exe_local = os.path.join(local_dir, "BuscadorPiezas.exe")
            # Si no se ejecuta desde la instalación local (p.ej. en desarrollo),
            # simplemente abrimos la carpeta de red para instalar a mano
            if not getattr(sys, 'frozen', False) or not os.path.isdir(local_dir):
                os.startfile(RUTA_DESPLIEGUE_APP)
                return
            resp = QMessageBox.question(
                self, "Actualizar Buscador de Piezas",
                f"Se instalará la versión {self._version_red or ''} y la aplicación se "
                f"reiniciará.\n\n¿Continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if resp != QMessageBox.Yes:
                return

            # Actualizador .bat (V2.0.3, reescrito): contenido 100%% ASCII.
            # La ruta de red lleva "BÚSQUEDA" con Ú: si se escribe DENTRO del
            # bat, la página de códigos de la consola (cp850/65001 según el
            # equipo) puede corromperla al parsear y todas las copias fallan
            # en silencio (bug reportado). Pasándola como ARGUMENTO viaja en
            # Unicode vía CreateProcess y es inmune a la codificación.
            # Además: log en %%TEMP%%\alsi_update.log y verificación de la
            # copia — si falla, lo dice en pantalla en vez de morir callado.
            bat = os.path.join(os.environ.get("TEMP", local_dir), "alsi_update.bat")
            recursos = ["SwPropExtractor.exe",
                        "SolidWorks.Interop.swdocumentmgr.dll", "config.ini",
                        "ALSI_BUSCADOR.ico", "reindexar_diario.py", "reindexar_tarea.bat"]
            lineas = [
                "@echo off",
                "setlocal",
                'set "NET=%~1"',
                'set "LOC=%~2"',
                'set "LOG=%TEMP%\\alsi_update.log"',
                'title Actualizando Buscador de Piezas ALSI...',
                'echo ==== %date% %time% ==== > "%LOG%"',
                'echo NET=[%NET%] >> "%LOG%"',
                'echo LOC=[%LOC%] >> "%LOG%"',
                "rem Margen para que la app se cierre por si misma",
                'set "SYS=%SystemRoot%\\System32"',
                'rem Rutas absolutas: si el PATH viene contaminado por el',
                'rem empaquetado, taskkill.exe fallaba con 0xc0000142',
                '"%SYS%\\timeout.exe" /t 2 /nobreak >nul 2>&1',
                "rem Forzar cierre de cualquier instancia restante",
                '"%SYS%\\taskkill.exe" /F /IM BuscadorPiezas.exe >nul 2>&1',
                '"%SYS%\\taskkill.exe" /F /IM SwPropExtractor.exe >nul 2>&1',
                '"%SYS%\\timeout.exe" /t 1 /nobreak >nul 2>&1',
                'copy /Y "%NET%\\BuscadorPiezas.exe" "%LOC%\\BuscadorPiezas.exe.nuevo" >> "%LOG%" 2>&1',
                'if not exist "%LOC%\\BuscadorPiezas.exe.nuevo" goto :fallo',
                'move /Y "%LOC%\\BuscadorPiezas.exe.nuevo" "%LOC%\\BuscadorPiezas.exe" >> "%LOG%" 2>&1',
                'if errorlevel 1 goto :fallo',
            ]
            for r in recursos:
                lineas.append(f'copy /Y "%NET%\\{r}" "%LOC%\\" >> "%LOG%" 2>&1')
            lineas += [
                'echo OK >> "%LOG%"',
                'start "" "%LOC%\\BuscadorPiezas.exe"',
                'del "%~f0" >nul 2>&1',
                'exit /b 0',
                ':fallo',
                'echo FALLO_COPIA >> "%LOG%"',
                'echo.',
                'echo  [ERROR] No se pudo copiar la nueva version desde la red.',
                'echo  Ejecuta INSTALAR_LOCAL.bat desde la carpeta de red.',
                'echo  (Detalle en %LOG%)',
                'echo.',
                'pause',
                'start "" "%LOC%\\BuscadorPiezas.exe"',
            ]
            with open(bat, "w", encoding="ascii", errors="strict") as f:
                f.write("\r\n".join(lineas))

            # Lanzar el .bat despegado (NET y LOC como argumentos Unicode).
            # cmd /s /c con TODO envuelto en comillas externas: a prueba de
            # rutas con espacios también en el propio .bat (usuarios con
            # espacios en el nombre tienen %TEMP% con espacios).
            # ENTORNO LIMPIO (V2.0.3): sin las variables _MEI*/_PYI* de
            # PyInstaller — si el exe nuevo las hereda, intenta cargar las DLL
            # desde la carpeta temporal del app VIEJO (ya borrada) y revienta
            # con "Failed to load Python DLL ..._MEIxxxx\python311.dll".
            entorno = self._entorno_sin_pyinstaller()
            DETACHED = 0x00000008
            linea = f'cmd /s /c ""{bat}" "{RUTA_DESPLIEGUE_APP}" "{local_dir}""'
            subprocess.Popen(linea, creationflags=DETACHED, close_fds=True,
                             env=entorno)
            self.close()
            QApplication.quit()
        except Exception as e:
            logger.error(f"Error lanzando actualización: {e}")
            QMessageBox.warning(
                self, "Actualización",
                "No se pudo iniciar la actualización automática.\n"
                "Puedes actualizar manualmente ejecutando INSTALAR_LOCAL.bat "
                "desde la carpeta de red.")
            try:
                os.startfile(RUTA_DESPLIEGUE_APP)
            except Exception:
                pass

    def _actualizar_estado_indice(self):
        """Estado del índice en el footer, con color según antigüedad (V2.0.0):
        verde ≤30 h, ámbar 30 h–4 días, rojo >4 días. Clic → diálogo Reindexar.
        Pensado para que a simple vista se detecte si la reindexación automática
        (tarea programada L-V 15:45 en OFITEC-4) ha dejado de correr."""
        try:
            ts = self.db.obtener_ultima_indexacion()
            if not ts:
                self.lbl_estado_indice.setText(
                    '<span style="color:#C7A23F;">●</span> Índice sin datos · clic para reindexar')
                self.lbl_estado_indice.setToolTip("No hay indexación registrada. Haz clic para reindexar el NAS.")
                return
            horas = max(0, (time.time() - ts) / 3600)
            if horas < 1:
                cuando = f"hace {int(horas * 60)} min"
            elif horas < 48:
                cuando = f"hace {int(horas)} h"
            else:
                cuando = f"hace {int(horas / 24)} días"
            if horas <= 30:
                color, prefijo = "#3BA55D", "Índice actualizado"      # verde
            elif horas <= 96:
                color, prefijo = "#C7A23F", "Índice"                   # ámbar
            else:
                color, prefijo = "#C75450", "Índice · conviene reindexar,"  # rojo
            self.lbl_estado_indice.setText(f'<span style="color:{color};">●</span> {prefijo} {cuando}')
            import datetime as _dt
            fecha = _dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
            self.lbl_estado_indice.setToolTip(
                f"Última indexación del NAS: {fecha}\n"
                f"Reindexación automática programada L-V a las 15:45 (equipo OFITEC-4).\n"
                f"Haz clic para reindexar ahora.")
        except Exception as e:
            logger.debug(f"Error estado índice: {e}")

    def _set_modo_busqueda(self, modo):
        """Cambia entre buscar por nombre y buscar conjuntos que CONTENGAN la
        pieza escrita (V2.0.3). Deja el buscador con pistas claras del modo."""
        self.modo_busqueda = modo
        contiene = (modo == 'contiene')
        self.act_modo_nombre.setChecked(not contiene)
        self.act_modo_contiene.setChecked(contiene)
        if contiene:
            # Texto explícito: cualquiera entiende qué va a hacer el botón
            self.btn_buscar.setText("Conjuntos")
            self.btn_buscar.setToolTip(
                "MODO ACTIVO: buscar conjuntos que lleven la pieza escrita.\n"
                "Escribe la pieza o referencia (ej. AC30-Q6A014) y pulsa Enter:\n"
                "saldrán los ENSAMBLAJES que la contienen.\n"
                "Sintaxis: ; = que lleven todas · , = cualquiera de ellas.\n"
                "Cambia de modo con la flecha ▾ de la derecha.")
            self.input_buscar.setPlaceholderText(
                "Pieza o referencia que deben llevar los conjuntos…  ej: AC30-Q6A014")
        else:
            self.btn_buscar.setText("Buscar")
            self.btn_buscar.setToolTip("Haz clic para iniciar la búsqueda (o pulsa Enter)")
            self.input_buscar.setPlaceholderText(self._placeholder_busqueda_original)
        self._actualizar_chips_contexto()
        if self.input_buscar.text().strip():
            self.ejecutar_busqueda(auto=True)

    def _on_placa_ce_toggled(self, activo):
        """Toggle 'Solo máquinas con placa CE' (V2.1.0)."""
        if activo:
            try:
                if self.db.contar_placas_ce() == 0:
                    self.toast.show_message(
                        "No hay placas CE indexadas todavía.\n"
                        "Pulsa 'Reindexar NAS' para cargarlas desde NÚMEROS DE SERIE.", 4000)
            except Exception:
                pass
        self.ejecutar_busqueda(auto=True)
        # La búsqueda puede retornar sin repintar chips (sin término/orígenes);
        # el chip del toggle debe reflejarse siempre
        self._actualizar_chips_contexto()

    def _reset_tipos(self):
        for a in self.tipos_actions.values():
            a.setChecked(True)
        self.actualizar_texto_tipos()
        self.on_filtro_jerarquico_changed(None)

    def _reset_checks(self, checks):
        for c in checks:
            c.blockSignals(True)
            c.setChecked(False)
            c.blockSignals(False)
        self.ejecutar_busqueda(auto=True)

    def _reset_lista_propiedades(self, lw):
        lw.blockSignals(True)
        for i in range(lw.count()):
            lw.item(i).setCheckState(Qt.Unchecked)
        lw.blockSignals(False)
        self.ejecutar_busqueda(auto=True)

    def _limpiar_filtros(self):
        """Devuelve todos los filtros al estado por defecto y relanza una única búsqueda."""
        try:
            for lw, marcado in ((self.list_companeros, True), (self.list_años, True),
                                (self.list_carpetas, True), (self.list_clientes, False),
                                (self.list_proyectos, False), (self.list_materiales, False),
                                (self.list_tratamientos, False), (self.list_cierres, False),
                                (self.list_espesores, False)):
                lw.blockSignals(True)
                estado = Qt.Checked if marcado else Qt.Unchecked
                for i in range(lw.count()):
                    lw.item(i).setCheckState(estado)
                lw.blockSignals(False)
            for chip in self.chips_años.values():
                chip.blockSignals(True)
                chip.setChecked(True)
                chip.blockSignals(False)
            for c in (self.chk_laser, self.chk_torno, self.chk_fresa, self.chk_soldadura,
                      self.chk_pintura, self.chk_montaje, self.chk_filo_guiado,
                      self.chk_onda, self.chk_cangilon, self.chk_runer):
                c.blockSignals(True)
                c.setChecked(False)
                c.blockSignals(False)
            for a in self.tipos_actions.values():
                a.setChecked(True)
            self.actualizar_texto_tipos()
            # V2.1.0: apagar el toggle Placa CE sin disparar búsqueda doble
            self.btn_placa_ce.blockSignals(True)
            self.btn_placa_ce.setChecked(False)
            self.btn_placa_ce.blockSignals(False)
            self._refrescar_real_jerarquico()
        except Exception as e:
            logger.debug(f"Error limpiando filtros: {e}")

    def _push_reciente(self, termino):
        try:
            rec = json.loads(str(self.qsettings.value("busquedas_recientes", "[]")))
            if termino in rec:
                rec.remove(termino)
            rec.insert(0, termino)
            self.qsettings.setValue("busquedas_recientes", json.dumps(rec[:3]))
            self._refrescar_recientes()
        except Exception as e:
            logger.debug(f"Error guardando búsqueda reciente: {e}")

    def _refrescar_recientes(self):
        try:
            self._vaciar_layout(self.recientes_lay)
            rec = json.loads(str(self.qsettings.value("busquedas_recientes", "[]")))
            for term in rec[:3]:
                chip = QPushButton(term if len(term) <= 18 else term[:16] + "…")
                chip.setObjectName("Chip")
                chip.setToolTip(term)
                chip.setCursor(Qt.PointingHandCursor)
                chip.clicked.connect(lambda _, t=term: self._aplicar_busqueda(t))
                self.recientes_lay.addWidget(chip)
        except Exception as e:
            logger.debug(f"Error refrescando recientes: {e}")

    def _aplicar_busqueda(self, termino):
        self.input_buscar.setText(termino)
        self.ejecutar_busqueda()

    def _refrescar_guardadas(self):
        try:
            self.menu_guardadas.clear()
            accion_guardar = self.menu_guardadas.addAction(svg_icon("check"), "Guardar búsqueda actual")
            accion_guardar.triggered.connect(self._guardar_busqueda_actual)
            guardadas = json.loads(str(self.qsettings.value("busquedas_guardadas", "[]")))
            if guardadas:
                self.menu_guardadas.addSeparator()
                for term in guardadas:
                    accion = self.menu_guardadas.addAction(svg_icon("buscar"), term)
                    accion.triggered.connect(lambda _, t=term: self._aplicar_busqueda(t))
                self.menu_guardadas.addSeparator()
                accion_vaciar = self.menu_guardadas.addAction("Vaciar guardadas")
                accion_vaciar.triggered.connect(self._vaciar_guardadas)
        except Exception as e:
            logger.debug(f"Error refrescando guardadas: {e}")

    def _guardar_busqueda_actual(self):
        term = self.input_buscar.text().strip()
        if not term:
            self.toast.show_message("Escribe un término antes de guardar")
            return
        guardadas = json.loads(str(self.qsettings.value("busquedas_guardadas", "[]")))
        if term not in guardadas:
            guardadas.insert(0, term)
            self.qsettings.setValue("busquedas_guardadas", json.dumps(guardadas[:10]))
        self._refrescar_guardadas()
        self.toast.show_message(f"Búsqueda guardada:\n{term}")

    def _vaciar_guardadas(self):
        self.qsettings.setValue("busquedas_guardadas", "[]")
        self._refrescar_guardadas()

    def actualizar_estilos(self):
        """V2.0.0: el tema vive en alsi_buscador.qss (aplicado a nivel de app
        en el bloque main). Este método se conserva por compatibilidad y solo
        garantiza que la ventana no arrastre estilos locales del tema antiguo."""
        self.setStyleSheet("")

    # ═══════════════════════════════════════════
    # PREFERENCIAS
    # ═══════════════════════════════════════════
    # V2.3.2 - Los cuatro filtros que se recuerdan entre sesiones. Estaban en
    # `buscador.preferencias`, que es una tabla COMPARTIDA de dos columnas
    # (clave, valor): una sola fila por clave para toda la oficina. O sea que
    # los filtros del último que cerraba la app se los encontraba puestos el
    # siguiente que la abría, y la app le devolvía de menos sin que supiera por
    # qué — ni un error en pantalla, solo resultados que faltan.
    # Es el mismo fallo que ya se corrigió con la última búsqueda (V2.0.3) y con
    # la geometría de ventana (V2.0.8); estos cuatro se quedaron atrás.
    FILTROS_RECORDADOS = ("companeros_checked", "años_checked",
                          "carpetas_checked", "tipos_checked",
                          "splitter_sizes")

    def _leer_filtro_guardado(self, clave):
        """El valor de ESTE equipo. La primera vez lo siembra del compartido.

        La siembra evita que a nadie le cambien los filtros de golpe el día que
        actualice: se toma una sola vez lo que hubiera en la tabla común y a
        partir de ahí cada equipo va por su cuenta. Mismo patrón que
        `ultimo_termino`."""
        local = self.qsettings.value(clave, None)
        if local is not None:
            return str(local)
        try:
            heredado = self.controller.load_preference(clave, "") or ""
        except Exception as e:
            logger.debug("No se ha podido heredar '%s': %s", clave, e)
            heredado = ""
        if heredado:
            logger.info("Filtro '%s' heredado de la configuración común "
                        "(a partir de ahora es de este equipo)", clave)
            self.qsettings.setValue(clave, heredado)
        return heredado

    def cargar_preferencias(self):
        # V2.0.3: NO pisar lo que el usuario ya haya escrito/buscado — la carga
        # de preferencias es diferida y podía llegar DESPUÉS de una búsqueda
        # del usuario, sustituyendo su término por el de la sesión anterior.
        if not self.input_buscar.text() and not getattr(self, '_gen_busqueda', 0):
            # V2.0.3: el último término es LOCAL de cada equipo (QSettings), no
            # compartido en la BD — cada uno arranca con SU última búsqueda.
            # Compatibilidad: si este equipo aún no tiene valor local, se toma
            # una única vez el de la BD (comportamiento previo) como semilla.
            local = str(self.qsettings.value("ultimo_termino", ""))
            if not local:
                local = self.controller.load_preference("ultimo_termino", "")
            self.input_buscar.setText(local)
        
        # Restaurar Checkbox Biblioteca (V1.0.0) - ELIMINADO PARA NAS NUEVO

        
        comp_guardados = self._leer_filtro_guardado("companeros_checked")
        if comp_guardados:
            comp_list = comp_guardados.split(',')
            for i in range(self.list_companeros.count()):
                item = self.list_companeros.item(i)
                item.setCheckState(Qt.Checked if item.text() in comp_list else Qt.Unchecked)

        # Restaurar Años (V1.2.3)
        años_guardados = self._leer_filtro_guardado("años_checked")
        if años_guardados:
            años_list = años_guardados.split(',')
            for i in range(self.list_años.count()):
                item = self.list_años.item(i)
                item.setCheckState(Qt.Checked if item.text() in años_list else Qt.Unchecked)

        # Restaurar Carpetas (V1.2.3)
        carpetas_guardadas = self._leer_filtro_guardado("carpetas_checked")
        if carpetas_guardadas:
            c_list = carpetas_guardadas.split(',')
            for i in range(self.list_carpetas.count()):
                item = self.list_carpetas.item(i)
                item.setCheckState(Qt.Checked if item.text() in c_list else Qt.Unchecked)

        # Restaurar Tipos (V1.0.0 - Desde Botón Superior)
        tipos_guardados = self._leer_filtro_guardado("tipos_checked")
        if tipos_guardados:
            t_list = tipos_guardados.split(',')
            for tipo, action in self.tipos_actions.items():
                action.setChecked(tipo in t_list)
            self.actualizar_texto_tipos()
        
        # V2.0.8: la geometría se guarda POR EQUIPO (QSettings). Antes salía de
        # 'preferencias', que es una tabla COMPARTIDA: si un compañero con dos
        # monitores guardaba x=2500, a todos los demás la app les abría fuera de
        # la pantalla y había que rescatarla con Windows+flecha.
        geom = self.qsettings.value("geometria", "")
        if not geom:
            geom = self.controller.load_preference("geometria") or ""
        if geom:
            try:
                parts = [int(x) for x in str(geom).split(',')]
                if len(parts) == 4:
                    self.setGeometry(*self._geometria_visible(*parts))
            except (ValueError, TypeError):
                pass

        # Restaurar tamaño splitter
        splitter_state = self._leer_filtro_guardado("splitter_sizes")
        if splitter_state:
            try:
                sizes = [int(s) for s in splitter_state.split(',')]
                if len(sizes) == 2:
                    self.splitter.setSizes(sizes)
            except ValueError:
                pass

    def _geometria_visible(self, x, y, w, h):
        """Encaja la ventana en una pantalla que exista de verdad (V2.0.8).

        Devuelve (x, y, w, h) garantizando que la barra de título queda
        accesible: si la posición guardada no cae en ninguna pantalla actual
        (monitor desconectado, o equipo distinto al que la guardó), se centra
        en la principal en vez de abrirse donde nadie la ve."""
        escritorio = QApplication.desktop()
        rect_guardado = QRect(x, y, max(w, 900), max(h, 600))
        # ¿se ve al menos una parte razonable en alguna pantalla?
        for i in range(escritorio.screenCount()):
            disponible = escritorio.availableGeometry(i)
            corte = disponible.intersected(rect_guardado)
            if corte.width() >= 200 and corte.height() >= 100:
                # cabe: solo se recorta al área utilizable de esa pantalla
                w = min(rect_guardado.width(), disponible.width())
                h = min(rect_guardado.height(), disponible.height())
                x = min(max(rect_guardado.x(), disponible.x()),
                        disponible.right() - w + 1)
                y = min(max(rect_guardado.y(), disponible.y()),
                        disponible.bottom() - h + 1)
                return (x, y, w, h)
        # No cae en ninguna pantalla: centrar en la principal
        disponible = escritorio.availableGeometry(escritorio.primaryScreen())
        w = min(rect_guardado.width(), disponible.width())
        h = min(rect_guardado.height(), disponible.height())
        logger.info("Geometría guardada fuera de pantalla: se centra la ventana")
        return (disponible.x() + (disponible.width() - w) // 2,
                disponible.y() + (disponible.height() - h) // 2, w, h)

    def save_window_state(self):
        rect = self.geometry()
        val = f"{rect.x()},{rect.y()},{rect.width()},{rect.height()}"
        # V2.0.8: por equipo, no compartida (ver load_window_state)
        self.qsettings.setValue("geometria", val)
        # V2.0.3: guardar el último término SOLO en local (privacidad por equipo)
        self.qsettings.setValue("ultimo_termino", self.input_buscar.text())
        
        # Guardar Checkbox Biblioteca (V1.0.0) - ELIMINADO PARA NAS NUEVO

        

        # V2.3.2: los filtros son de CADA EQUIPO (QSettings), ya no van a la
        # tabla compartida. Ver FILTROS_RECORDADOS.
        self.qsettings.setValue("companeros_checked",
                                ','.join(self.get_selected_items(self.list_companeros)))
        self.qsettings.setValue("años_checked",
                                ','.join(self.get_selected_items(self.list_años)))
        self.qsettings.setValue("carpetas_checked",
                                ','.join(self.get_selected_items(self.list_carpetas)))
        self.qsettings.setValue("tipos_checked",
                                ','.join(self.get_selected_tipos()))

        # Guardar tamaño splitter
        sizes = self.splitter.sizes()
        self.qsettings.setValue("splitter_sizes", f"{sizes[0]},{sizes[1]}")

    def closeEvent(self, event):
        # V2.0.0: parar timers e hilo de miniaturas ANTES de destruir widgets,
        # evita el "wrapped C/C++ object of type QLabel has been deleted"
        try:
            self.timer_filtros.stop()
            self.timer_preview.stop()
            if hasattr(self, 'thumb_worker') and self.thumb_worker and self.thumb_worker.isRunning():
                self.thumb_worker.cancelar()
                try:
                    self.thumb_worker.thumbnail_ready.disconnect(self.on_thumbnail_ready)
                except (TypeError, RuntimeError):
                    pass
                self.thumb_worker.wait(1000)
            # V2.0.3: esperar brevemente a los search workers (evita
            # 'QThread destroyed while running' al cerrar en plena búsqueda)
            for w in list(getattr(self, '_search_workers', [])):
                try:
                    w.listo.disconnect(self._on_resultados_busqueda)
                    w.fallo.disconnect(self._on_error_busqueda)
                except (TypeError, RuntimeError):
                    pass
                w.wait(1500)
            # V2.3.1: idem con los de la cascada y los de Clientes/Proyectos
            self._detener_workers_de_fondo()
        except Exception as e:
            logger.debug(f"Error deteniendo tareas al cerrar: {e}")
        self.save_window_state()
        super().closeEvent(event)

    def _sync_chip_anio(self, item):
        """Mantiene el chip visual del año sincronizado con list_años (V2.0.1)."""
        try:
            chip = self.chips_años.get(item.text())
            if chip:
                estado = item.checkState() == Qt.Checked
                if chip.isChecked() != estado:
                    chip.blockSignals(True)
                    chip.setChecked(estado)
                    chip.blockSignals(False)
        except (RuntimeError, AttributeError):
            pass

    def on_filtro_jerarquico_changed(self, item):
        """Manejador con debouncing para la cascada de filtros (V1.0.0.2)"""
        if self.bloqueo_filtros:
            return

        # Reiniciar el timer. Solo dispararemos la búsqueda pesada
        # tras 300ms de inactividad
        self.timer_filtros.start(300)

    def _refrescar_real_jerarquico(self):
        """Ejecución real de la cascada tras el debouncing.
        V2.3.1: todo va encadenado desde el worker de Clientes/Proyectos —
        primero se repueblan las listas y solo después salen la cascada de
        propiedades y la búsqueda, que es el orden que tenía la versión
        síncrona. El hilo de la interfaz no se bloquea en ningún punto."""
        self.refrescar_filtros_jerarquicos(disparar_busqueda=True)

    def cargar_filtros_propiedades(self):
        try:
            # Materiales (se cargan de la BD, filtrados por lista oficial de SW)
            materiales = self.controller.get_all_materiales()
            self.list_materiales.blockSignals(True)
            self.list_materiales.clear()
            for mat in materiales:
                item = QListWidgetItem(mat)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.list_materiales.addItem(item)
            self.list_materiales.blockSignals(False)
            # Tratamientos y Espesores son fijos (definidos en la UI)
        except Exception as e:
            logger.error(f"Error cargando propiedades: {e}")

    def _refrescar_props_contexto(self):
        """V2.3.0: cascada de los filtros de propiedades SW. Lanza en segundo
        plano la consulta de valores presentes en el contexto actual y oculta
        en Material/Tratamiento/Cierre/Espesor los que no tienen archivos.
        La consulta nunca corre en el hilo de UI: cero impacto en fluidez."""
        try:
            kwargs = {
                'companions': self.get_selected_items(self.list_companeros),
                'years': self.get_selected_items(self.list_años),
                'clientes': self.get_selected_items(self.list_clientes) or None,
                'proyectos': [i.split(' - ')[0]
                              for i in self.get_selected_items(self.list_proyectos)] or None,
            }
            # Mismo contexto que la última vez: nada que refrescar
            if getattr(self, '_props_ctx_kwargs', None) == kwargs:
                return
            self._asegurar_parada_al_salir()
            self._props_ctx_kwargs = kwargs
            self._gen_props = getattr(self, '_gen_props', 0) + 1
            worker = PropsContextWorker(self._gen_props, self.controller, kwargs)
            worker.listo.connect(self._on_props_contexto)
            if not hasattr(self, '_props_workers'):
                self._props_workers = []
            self._props_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._limpiar_props_worker(w))
            worker.start()
        except Exception as e:
            logger.debug(f"Error lanzando cascada de propiedades: {e}")

    def _limpiar_props_worker(self, worker):
        try:
            self._props_workers.remove(worker)
        except (ValueError, AttributeError):
            pass

    def _asegurar_parada_al_salir(self):
        """Un unico enganche a aboutToQuit para todos los hilos de fondo.

        Estos workers arrancan ya en la carga inicial, antes de que el usuario
        toque nada. Si el proceso termina por una via que no pasa por
        closeEvent, Qt destruye el hilo en marcha y el proceso se cae al salir
        (segmentation fault). aboutToQuit cubre todas las vias."""
        if getattr(self, '_parada_conectada', False):
            return
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._detener_workers_de_fondo)
        # Y una última red por debajo de Qt: aboutToQuit solo salta si se llegó
        # a entrar en el bucle de eventos. Un proceso que termina por otra vía
        # (una utilidad de linea de comandos, un banco de pruebas) destruiría
        # los hilos en marcha y se caería al salir. atexit corre siempre.
        import atexit
        atexit.register(self._detener_workers_de_fondo)
        self._parada_conectada = True

    def _detener_workers_de_fondo(self):
        """Para los hilos de fondo. Se llama desde closeEvent, desde aboutToQuit
        y desde atexit, y ese último puede llegar con Qt ya a medio desmontar:
        si el objeto C++ de la ventana ya no existe, tocar cualquier cosa suya
        tumba el proceso al salir. Por eso se comprueba antes."""
        try:
            from PyQt5 import sip
            if sip.isdeleted(self):
                return
        except Exception:
            pass
        self._detener_props_workers()
        self._detener_filtros_workers()

    def _detener_props_workers(self):
        """Espera a los workers de la cascada antes de que Qt se desmonte."""
        for w in list(getattr(self, '_props_workers', [])):
            try:
                w.listo.disconnect(self._on_props_contexto)
            except Exception:
                pass
            try:
                if w.isRunning():
                    w.wait(5000)
            except Exception:
                pass
        self._props_workers = []

    def _on_props_contexto(self, gen, data):
        """Aplica la cascada: oculta los valores sin archivos en el contexto.
        Lo marcado nunca se oculta (para poder desmarcarlo). setHidden no
        dispara itemChanged, así que no provoca búsquedas en cadena."""
        if gen != getattr(self, '_gen_props', 0):
            return  # respuesta obsoleta: hay un contexto más nuevo en curso
        try:
            listas = (self.list_materiales, self.list_tratamientos,
                      self.list_cierres, self.list_espesores)
            if not data:
                # Error de BD: mostrar todo (mismo comportamiento que antes)
                for lw in listas:
                    for i in range(lw.count()):
                        lw.item(i).setHidden(False)
                return
            mats = data.get('materiales', set())
            trats = data.get('tratamientos', set())
            cierres = data.get('cierres', set())
            # Espesores de BD ("3", "3.00", "3.5"...) -> mm enteros, con la
            # misma semántica que el filtro de buscar(): '3' o '3.%'
            esp_mm = set()
            for v in data.get('espesores', set()):
                m = re.match(r'^(\d+)(?:[.,]\d*)?$', v)
                if m:
                    esp_mm.add(int(m.group(1)))

            def aplicar(lw, visible_fn):
                for i in range(lw.count()):
                    item = lw.item(i)
                    try:
                        visible = visible_fn(item.text())
                    except Exception:
                        visible = True   # ante la duda, no se esconde nada
                    item.setHidden(item.checkState() != Qt.Checked and not visible)

            aplicar(self.list_materiales, lambda t: t.strip().upper() in mats)
            aplicar(self.list_tratamientos, lambda t: t.strip().upper() in trats)
            aplicar(self.list_cierres, lambda t: any(t.upper() in v for v in cierres))
            aplicar(self.list_espesores, lambda t: int(t.replace('mm', '').strip()) in esp_mm)
        except Exception as e:
            logger.debug(f"Error aplicando cascada de propiedades: {e}")

    def refrescar_filtros_jerarquicos(self, disparar_busqueda=False):
        """Puebla las listas de Clientes y Proyectos con lógica de cascada.

        V2.3.1: las dos consultas se hacían aquí mismo, en el hilo de la
        interfaz, y congelaban la ventana ~0,65 s en cada clic de filtro.
        Ahora se lanzan a un worker y la ventana no se bloquea; el repintado
        ocurre en `_on_filtros_jerarquicos` cuando llegan los datos.

        `disparar_busqueda=True` encadena la cascada de propiedades y la
        búsqueda automática DESPUÉS de repoblar, que es el orden que tenía la
        versión síncrona: si al cambiar de contexto desaparece un cliente que
        estaba marcado, la búsqueda tiene que salir ya sin él."""
        if self.bloqueo_filtros:
            return
        try:
            self._asegurar_parada_al_salir()
            comp_sel = self.get_selected_items(self.list_companeros)
            años_sel = self.get_selected_items(self.list_años)
            clientes_sel = self.get_selected_items(self.list_clientes)

            self._gen_filtros = getattr(self, '_gen_filtros', 0) + 1
            if not hasattr(self, '_filtros_buscan'):
                self._filtros_buscan = {}
            # Se apunta también en qué búsqueda estábamos al pedir el refresco.
            # Al volver, si ya hay una búsqueda más nueva (por ejemplo la que
            # lanza un refinado), NO se dispara la automática: pisaría a la que
            # el usuario acaba de pedir. Con la versión síncrona esto no podía
            # pasar porque el orden era siempre el mismo.
            self._filtros_buscan[self._gen_filtros] = (
                bool(disparar_busqueda), getattr(self, '_gen_busqueda', 0))

            worker = FiltrosJerarquicosWorker(self._gen_filtros, self.controller,
                                              comp_sel, años_sel, clientes_sel)
            worker.listo.connect(self._on_filtros_jerarquicos)
            if not hasattr(self, '_filtros_workers'):
                self._filtros_workers = []
            self._filtros_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._limpiar_filtros_worker(w))
            worker.start()
        except Exception as e:
            logger.error(f"Error lanzando el refresco de filtros: {e}")

    def _limpiar_filtros_worker(self, worker):
        try:
            self._filtros_workers.remove(worker)
        except (ValueError, AttributeError):
            pass

    def _detener_filtros_workers(self):
        """Espera a los workers de Clientes/Proyectos antes de desmontar Qt.

        Todo va protegido: esto corre también desde atexit, cuando Qt puede
        estar ya a medio desmontar y cualquier llamada sobre un objeto muerto
        tumbaría el proceso al salir."""
        for w in list(getattr(self, '_filtros_workers', [])):
            try:
                w.listo.disconnect(self._on_filtros_jerarquicos)
            except Exception:
                pass
            try:
                if w.isRunning():
                    w.wait(5000)
            except Exception:
                pass
        self._filtros_workers = []

    def _on_filtros_jerarquicos(self, gen, ok, clientes, proyectos):
        """Repuebla Clientes y Proyectos con lo que trajo el worker.

        Las marcas se conservan; las que ya no existen en el contexto nuevo
        desaparecen, igual que antes. Si la consulta falló no se toca nada:
        vaciar las listas por un corte de red dejaría al usuario sin filtros."""
        disparar, gen_busqueda_al_pedir = False, 0
        if hasattr(self, '_filtros_buscan'):
            disparar, gen_busqueda_al_pedir = self._filtros_buscan.pop(gen, (False, 0))
        if gen != getattr(self, '_gen_filtros', 0):
            return   # respuesta obsoleta: hay un contexto más nuevo en curso
        if ok:
            self.bloqueo_filtros = True
            self.list_clientes.blockSignals(True)
            self.list_proyectos.blockSignals(True)
            try:
                clientes_sel = set(self.get_selected_items(self.list_clientes))
                proyectos_sel = {t.split(' - ')[0]
                                 for t in self.get_selected_items(self.list_proyectos)}

                self.list_clientes.clear()
                for cli in clientes:
                    item = QListWidgetItem(cli)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if cli in clientes_sel else Qt.Unchecked)
                    self.list_clientes.addItem(item)

                self.list_proyectos.clear()
                for cod, nom in proyectos:
                    item = QListWidgetItem(f"{cod} - {nom}")
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if str(cod) in proyectos_sel
                                       else Qt.Unchecked)
                    self.list_proyectos.addItem(item)
            except Exception as e:
                logger.error(f"Error repoblando Clientes y Proyectos: {e}")
            finally:
                self.list_clientes.blockSignals(False)
                self.list_proyectos.blockSignals(False)
                self.bloqueo_filtros = False
        if disparar:
            # La cascada de propiedades siempre: depende del contexto, no de
            # qué búsqueda esté en curso.
            self._refrescar_props_contexto()
            # Dos motivos para NO lanzar la búsqueda automática. Con la versión
            # síncrona no podían darse, porque el refresco terminaba antes de
            # que nadie más pudiera pedir nada.
            if getattr(self, '_refinado_pendiente', None):
                # Hay un refinado esperando a unos resultados concretos: esa
                # búsqueda es suya. Si la pisamos, el refinado se aplica sobre
                # una lista vacía y se pierde — que es justo lo que arreglaba
                # la V2.1.1.
                logger.debug("Búsqueda automática omitida: hay un refinado en espera")
                return
            if getattr(self, '_gen_busqueda', 0) != gen_busqueda_al_pedir:
                # El usuario ha lanzado una búsqueda mientras se refrescaban
                # los filtros. Esa es la buena.
                logger.debug("Búsqueda automática omitida: ya hay una más nueva en curso")
                return
            self.ejecutar_busqueda(auto=True)

    # ═══════════════════════════════════════════
    # BÚSQUEDA (Cambio 3: filtro por extensión)
    # ═══════════════════════════════════════════
    def ejecutar_busqueda(self, auto=False):
        try:
            termino = self.input_buscar.text().strip()
            comp_sel = self.get_selected_items(self.list_companeros)
            años_sel = self.get_selected_items(self.list_años)

            # Validación: al menos un origen seleccionado (v1.0.7)
            if not comp_sel:
                if not auto:
                    avisar_atencion(self, "Atención", "Selecciona al menos un origen.")
                return
            
            if not termino:
                self._excluidas_activas = []      # V2.1.4: sin chip huérfano
                self._actualizar_chips_contexto()
                if not auto:
                    avisar_atencion(self, "Atención", "Introduce un término de búsqueda.")
                return

            # V2.1.4: '-palabra' quita resultados; si SOLO hay exclusiones no
            # hay nada que buscar. Se dice qué falta y cómo se arregla, en vez
            # de devolver medio índice o cero resultados sin explicación.
            _inc, _exc, _and = self.db.parsear_termino(termino)
            self._excluidas_activas = _exc
            if _exc and not _inc:
                ejemplo = 'cinta; ' + '; '.join('-' + e for e in _exc)
                aviso = ('Un «-palabra» sirve para QUITAR resultados, no para buscar.' + '\n\n' +
                         'Escribe primero lo que SÍ quieres encontrar:' + '\n' +
                         '    ' + ejemplo)
                if not auto:
                    avisar_atencion(self, 'Falta qué buscar', aviso)
                self.lbl_status.setText(
                    'Escribe también lo que sí quieres encontrar — ej.: ' + ejemplo)
                return
                
            # V2.3.1: la traza llevaba solo término, orígenes y años. Cuando una
            # búsqueda vuelve vacía y no se sabe por qué, lo que hace falta es
            # ver TODOS los filtros que iban puestos — también en el informe que
            # manda un compañero con "Copiar para enviar".
            logger.info(
                "Ejecutando búsqueda auto=%s | Term: %s | Comp: %d | Años: %d | "
                "Clientes: %d | Proyectos: %d | Carpetas: %d | Tipos: %d",
                auto, termino, len(comp_sel), len(años_sel),
                len(self.get_selected_items(self.list_clientes)),
                len(self.get_selected_items(self.list_proyectos)),
                len(self.get_selected_items(self.list_carpetas)),
                len(self.get_selected_tipos()))
            self.lbl_status.setText("Buscando...")

            # V2.0.3: vaciar la rejilla AL LANZAR — con la búsqueda asíncrona,
            # dejar los resultados anteriores visibles durante el "Buscando…"
            # llevaba a leerlos como si fueran la respuesta del filtro nuevo.
            self.tabla.setSortingEnabled(False)
            self.tabla.setRowCount(0)
            self.galeria.blockSignals(True)
            self.galeria.clear()
            self.galeria.blockSignals(False)
            self._galeria_items = {}
            self.lbl_count.setText("…")
            self._res_base = []
            self._refinados = []
            self._termino_base = None
            self.input_refinar.clear()
            self._actualizar_barra_refinar()
            QApplication.processEvents()
            
            # Obtener filtros (V1.0.0: Filtros Jerárquicos)
            carpetas_sel = self.get_selected_items(self.list_carpetas)
            tipos_sel = self.get_selected_tipos()
            clientes_sel = self.get_selected_items(self.list_clientes)
            proyectos_sel = [item.split(' - ')[0] for item in self.get_selected_items(self.list_proyectos)]
            
            # Recopilar todas las extensiones de los tipos seleccionados
            extensiones = []
            for t in tipos_sel:
                exts_map = FILTRO_EXTENSIONES.get(t)
                if exts_map:
                    extensiones.extend(exts_map)
            
            if not extensiones and tipos_sel:
                extensiones = None

            props_fabricacion = {
                'laser': self.chk_laser.isChecked(),
                'torno': self.chk_torno.isChecked(),
                'fresa': self.chk_fresa.isChecked(),
                'soldadura': self.chk_soldadura.isChecked(),
                'pintura': self.chk_pintura.isChecked(),
                'montaje': self.chk_montaje.isChecked()
            }
            props_bandas = {
                'cierres': self.get_selected_items(self.list_cierres) or None,
                'filo_guiado': self.chk_filo_guiado.isChecked(),
                'onda': self.chk_onda.isChecked(),
                'cangilon': self.chk_cangilon.isChecked(),
                'runer': self.chk_runer.isChecked()
            }
            
            # Recoger filtros de propiedades (listas multi-selección)
            materiales_sel = self.get_selected_items(self.list_materiales) or None
            tratamientos_sel = self.get_selected_items(self.list_tratamientos) or None
            espesores_sel = self.get_selected_items(self.list_espesores) or None

            # V2.0.3: la consulta corre en un SearchWorker (hilo aparte) — la UI
            # no se congela nunca. Generación para descartar respuestas viejas
            # si se encadenan búsquedas/filtros.
            self._gen_busqueda = getattr(self, '_gen_busqueda', 0) + 1
            gen = self._gen_busqueda
            if not hasattr(self, '_busquedas_ctx'):
                self._busquedas_ctx = {}
            self._busquedas_ctx[gen] = {'termino': termino, 'auto': auto, 't0': time.time()}

            args = (termino, comp_sel, años_sel, extensiones, carpetas_sel,
                    clientes_sel, proyectos_sel, None, props_fabricacion,
                    props_bandas, materiales_sel, tratamientos_sel, espesores_sel)
            worker = SearchWorker(
                gen, self.controller, args,
                {'solo_placa_ce': self.btn_placa_ce.isChecked()},
                modo=getattr(self, 'modo_busqueda', 'nombre'),
                db=self.db,
                contiene_kwargs={
                    'termino': termino,
                    'compañeros': comp_sel,
                    'años': años_sel,
                    'carpetas': carpetas_sel,
                    'clientes': clientes_sel,
                    'proyectos': proyectos_sel,
                    'solo_placa_ce': self.btn_placa_ce.isChecked(),
                    'profundo': self.btn_profundo.isChecked(),  # V2.0.3
                })
            worker.listo.connect(self._on_resultados_busqueda)
            worker.fallo.connect(self._on_error_busqueda)
            if not hasattr(self, '_search_workers'):
                self._search_workers = []
            self._search_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._limpiar_search_worker(w))
            logger.info(f"Búsqueda gen={gen} lanzada (placaCE={self.btn_placa_ce.isChecked()})")
            worker.start()

            # V2.0.3: latido visible mientras se busca ('Buscando… Ns') y
            # watchdog — si en 90s no hay respuesta, avisar en vez de quedar
            # mudo con la rejilla vacía (reportado con Placa CE).
            if not hasattr(self, 'timer_busqueda_tick'):
                self.timer_busqueda_tick = QTimer(self)
                self.timer_busqueda_tick.setInterval(1000)
                self.timer_busqueda_tick.timeout.connect(self._tick_busqueda)
            self._tick_gen = gen
            self._tick_t0 = time.time()
            self.timer_busqueda_tick.start()

        except Exception as e:
            self.lbl_status.setText("❌ Error en la búsqueda")
            self.tabla.setRowCount(0)
            import traceback as _tb
            mostrar_error(
                "Error de búsqueda",
                "Se ha producido un error al realizar la búsqueda.\n\n"
                "Si el error persiste, intenta actualizar el índice.",
                "%s\n%s" % (e, _tb.format_exc()), self)

    def _limpiar_search_worker(self, worker):
        try:
            self._search_workers.remove(worker)
        except (ValueError, AttributeError):
            pass

    def _tick_busqueda(self):
        """Latido del 'Buscando…' + watchdog de 90s (V2.0.3)."""
        try:
            # ¿sigue vigente esta búsqueda y sin respuesta?
            if getattr(self, '_tick_gen', -1) != getattr(self, '_gen_busqueda', 0) \
                    or self._tick_gen not in getattr(self, '_busquedas_ctx', {}):
                self.timer_busqueda_tick.stop()
                return
            transcurrido = int(time.time() - self._tick_t0)
            if transcurrido >= 90:
                self.timer_busqueda_tick.stop()
                logger.error(f"Watchdog: búsqueda gen={self._tick_gen} sin respuesta en 90s")
                self._busquedas_ctx.pop(self._tick_gen, None)
                self.lbl_status.setText(
                    "⚠ La búsqueda no responde (¿red/BD saturada?) — vuelve a intentarlo")
            elif transcurrido >= 3:
                self.lbl_status.setText(f"Buscando… ({transcurrido} s)")
        except Exception:
            pass

    def _on_error_busqueda(self, gen, mensaje):
        if gen != getattr(self, '_gen_busqueda', 0):
            return  # búsqueda superada por otra más reciente
        self._busquedas_ctx.pop(gen, None)
        self.lbl_status.setText("❌ Error en la búsqueda")
        self.tabla.setRowCount(0)
        mostrar_error(
            "Error de búsqueda",
            "Se ha producido un error al realizar la búsqueda.\n\n"
            "Si el error persiste, intenta actualizar el índice.",
            mensaje, self)

    def _on_resultados_busqueda(self, gen, resultados):
        """Llega la respuesta del SearchWorker: pintar por TRAMOS para que la
        UI siga viva aunque haya 5000 filas (V2.0.3)."""
        if gen != getattr(self, '_gen_busqueda', 0):
            logger.info(f"Búsqueda gen={gen} descartada (vigente: {getattr(self, '_gen_busqueda', 0)})")
            self._busquedas_ctx.pop(gen, None)
            return  # obsoleta: hay una búsqueda más nueva en curso
        ctx = self._busquedas_ctx.pop(gen, {})
        logger.info(f"Búsqueda gen={gen} completada: {len(resultados)} filas "
                    f"en {time.time() - ctx.get('t0', time.time()):.1f}s")

        # V2.0.3: nueva búsqueda base — resetea la pila de refinados
        self._res_base = resultados
        self._refinados = []
        # V2.1.1: se guarda el término que ha producido esta base, para saber
        # si el cuadro de búsqueda ha cambiado desde entonces.
        self._termino_base = ctx.get('termino', '')
        try:
            self._pintar_resultados(resultados, ctx)
        except Exception as e:
            # Nunca dejar la app muda en 'Buscando…' por un fallo de pintado
            logger.error(f"Error pintando resultados gen={gen}: {e}")
            self.lbl_status.setText("❌ Error mostrando resultados — reintenta la búsqueda")

        # V2.1.1: el usuario escribió en el cuadro principal y aplicó el
        # refinado sin pulsar Enter. Se lanzó la general primero y el refinado
        # quedó en espera; ahora que hay base, se aplica.
        pendiente = getattr(self, '_refinado_pendiente', None)
        # V2.3.1: solo lo consume LA búsqueda que lo dejó en espera. Antes se lo
        # llevaba cualquier respuesta que llegase, incluida la de una búsqueda
        # anterior aún en vuelo, y el refinado se perdía.
        esperada = getattr(self, '_gen_refinado_pendiente', None)
        if pendiente and esperada is not None and gen != esperada:
            pendiente = None
        if pendiente:
            self._refinado_pendiente = None
            self._gen_refinado_pendiente = None
            if resultados:
                self._refinados = [pendiente]
                self._aplicar_refinados()
            else:
                self.lbl_status.setText(
                    "La búsqueda no ha dado resultados: no hay nada que refinar")

    def _pintar_resultados(self, resultados, ctx):
        """Arranca el pintado por tramos de un conjunto de resultados (búsqueda
        base o refinada). Reutilizado por el refinado (V2.0.3)."""
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(resultados))

        # Precarga de miniaturas de BD en UNA consulta (sin parpadeo). Cap para
        # no cargar el hilo de UI; el resto las trae el ThumbnailWorker.
        minis_bd = {}
        if len(resultados) <= 300:
            try:
                minis_bd = self.db.obtener_miniaturas_lote(
                    [d[10] for d in resultados if d[10]])
            except Exception as e:
                logger.debug(f"Precarga de miniaturas falló: {e}")

        self._fill = {'gen': getattr(self, '_gen_busqueda', 0), 'res': resultados,
                      'i': 0, 'vistas': [], 'minis': minis_bd, 'ctx': ctx}
        self._llenar_tramo_tabla()

    _TRAMO_FILAS = 600  # filas por tanda de pintado

    def _llenar_tramo_tabla(self):
        """Pinta un tramo de filas y cede el control al event loop (V2.0.3)."""
        st = getattr(self, '_fill', None)
        if not st or st['gen'] != getattr(self, '_gen_busqueda', 0):
            return  # una búsqueda más nueva ha tomado el relevo
        resultados = st['res']
        minis_bd = st['minis']
        vistas_pendientes = st['vistas']
        ini = st['i']
        fin = min(ini + self._TRAMO_FILAS, len(resultados))

        self.tabla.setUpdatesEnabled(False)
        try:
            for row in range(ini, fin):
                data = resultados[row]
                # [nombre, comp, año, cliente, proy, tipo, codProy, nomProy, codOrd, nomOrd, ruta]
                ruta = data[10]
                self.tabla.setItem(row, 0, QTableWidgetItem(ruta))
                self.tabla.setItem(row, 1, QTableWidgetItem(str(row).zfill(6)))
                self.tabla.setItem(row, 2, QTableWidgetItem(str(data[6]) if data[6] else ""))
                self.tabla.setItem(row, 3, QTableWidgetItem(str(data[7]) if data[7] else ""))

                # Columna 4: Vista — miniatura de BD directa o badge + pendiente
                thumb_item = QTableWidgetItem()
                thumb_item.setData(Qt.UserRole, ruta)
                thumb_item.setTextAlignment(Qt.AlignCenter)
                puesta = False
                data_bd = minis_bd.get(ruta)
                if data_bd:
                    img = QImage.fromData(data_bd)
                    if not img.isNull():
                        # V2.0.3: resolución nativa (tope 320px). QIcon NUNCA
                        # amplía: guardarla a 160 hacía que en galería XL/zoom
                        # la imagen no creciera (solo se separaban las tarjetas).
                        pm = QPixmap.fromImage(img)
                        if pm.width() > 320 or pm.height() > 320:
                            pm = pm.scaled(320, 320, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation)
                        thumb_item.setIcon(QIcon(pm))
                        self.cache_miniaturas[(ruta, 256)] = pm
                        puesta = True
                if not puesta:
                    ext_badge = Path(str(data[0])).suffix.lower()
                    if ext_badge not in self._badge_cache:
                        self._badge_cache[ext_badge] = QIcon(pixmap_badge_extension(ext_badge, size=48))
                    thumb_item.setIcon(self._badge_cache[ext_badge])
                    vistas_pendientes.append((row, ruta))
                self.tabla.setItem(row, 4, thumb_item)

                map_cols = {
                    0: 5, 1: 6, 2: 7, 3: 8, 4: 9, 5: 20,
                    11: 11, 12: 12, 13: 13, 14: 14, 15: 15,
                    16: 16, 17: 17, 18: 18, 19: 19,
                }
                for i_data, i_tabla in map_cols.items():
                    val = data[i_data]
                    texto = str(val) if val else ""
                    if i_tabla in (6, 9) and texto:
                        texto = etiqueta_origen(texto)
                    self.tabla.setItem(row, i_tabla, QTableWidgetItem(texto))

                cod_ord = str(data[8]) if data[8] else ""
                nom_ord = str(data[9]) if data[9] else ""
                self.tabla.setItem(row, 10, QTableWidgetItem(f"{cod_ord} {nom_ord}".strip()))

                # V2.0.8: peso y superficie, como NUMERO para que ordene bien
                for i_data, i_col, dec in ((20, 21, 3), (21, 22, 4)):
                    it_n = QTableWidgetItem()
                    val = data[i_data] if len(data) > i_data else None
                    if val:
                        it_n.setData(Qt.DisplayRole, round(float(val), dec))
                    else:
                        it_n.setText("")
                    it_n.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.tabla.setItem(row, i_col, it_n)
        finally:
            self.tabla.setUpdatesEnabled(True)

        st['i'] = fin
        if fin < len(resultados):
            self.lbl_status.setText(f"Cargando resultados… {fin}/{len(resultados)}")
            QTimer.singleShot(0, self._llenar_tramo_tabla_seguro)
        else:
            self._finalizar_busqueda()

    def _llenar_tramo_tabla_seguro(self):
        """Envoltorio de los tramos por QTimer: si un tramo revienta, cerrar la
        búsqueda con mensaje en vez de dejar 'Cargando…' congelado (V2.0.3)."""
        try:
            self._llenar_tramo_tabla()
        except Exception as e:
            logger.error(f"Error en tramo de tabla: {e}")
            try:
                self.tabla.setSortingEnabled(True)
                self.lbl_status.setText("❌ Error mostrando resultados — reintenta la búsqueda")
            except Exception:
                pass

    def _finalizar_busqueda(self):
        """Cierre de la búsqueda: miniaturas pendientes, galería, contadores."""
        st = getattr(self, '_fill', None)
        if not st or st['gen'] != getattr(self, '_gen_busqueda', 0):
            return
        resultados = st['res']
        ctx = st['ctx']
        termino = ctx.get('termino', '')
        auto = ctx.get('auto', False)
        t0_busqueda = ctx.get('t0', time.time())

        self._swap_thumb_worker(st['vistas'])
        self.tabla.setSortingEnabled(True)

        # Refrescar galería si es la vista activa (también por tramos)
        if self.stack_vistas.currentIndex() == 1:
            self._sincronizar_galeria()

        n_fmt = f"{len(resultados):,}".replace(",", ".")
        if ctx.get('refino') is not None:
            # V2.0.3: cierre de un REFINADO — contador X → Y
            base_fmt = f"{ctx['refino']:,}".replace(",", ".")
            self.lbl_status.setText(
                f"Refinado: {n_fmt} de {base_fmt} resultados"
                + ("" if resultados else " — sin coincidencias (Esc para deshacer)"))
            self.lbl_count.setText(f"{n_fmt} de {base_fmt} · refinado")
        else:
            if len(resultados) >= 5000:
                self.lbl_status.setText("⚠ Mostrando 5000 de 5000+ resultados. Refina tu búsqueda.")
            else:
                self.lbl_status.setText("Listo")
            dt_txt = f"{time.time() - t0_busqueda:.2f}".replace(".", ",")
            self.lbl_count.setText(f"{n_fmt} resultados · {dt_txt} s")
            if not resultados and termino:
                if self.btn_placa_ce.isChecked():
                    # V2.0.3: con el filtro CE activo, decirlo claro
                    self.lbl_status.setText(
                        f"0 máquinas con placa CE para '{termino}' con estos filtros "
                        f"— prueba a desactivar 'Placa CE' o ampliar años")
                else:
                    self.lbl_status.setText(f"No se encontraron resultados para '{termino}'")
            if not auto and termino and resultados:
                self._push_reciente(termino)

        self._actualizar_chips_contexto()
        self._actualizar_barra_refinar()

    # ═══════════════════════════════════════════
    # REFINADO DE RESULTADOS (V2.0.3)
    # ═══════════════════════════════════════════
    def _casa_termino_local(self, nombre, termino):
        """Matcher en cliente con la MISMA sintaxis del buscador:
        espacio=frase exacta, ';'=Y, ','=O, '-palabra'=fuera (V2.1.4).
        Sin acentos y sin distinguir mayúsculas. Comparte gramática con la
        consulta del servidor (IndexManager.parsear_termino) para que el
        refinado por nombre y la búsqueda no puedan discrepar."""
        norm = self.db.normalizar_texto
        n = norm(nombre)
        incluidas, excluidas, modo_and = self.db.parsear_termino(termino)
        if any(norm(x) in n for x in excluidas):
            return False
        if not incluidas:
            # solo exclusiones: pasa todo lo que no lleve esas palabras
            return True
        if modo_and:
            return all(norm(k) in n for k in incluidas)
        return any(norm(k) in n for k in incluidas)

    def _pintar_estilo_refinar(self):
        """Estilos de la barra: input con focus naranja y borde de la barra
        encendido cuando hay refinados activos (V2.0.3)."""
        activo = bool(getattr(self, '_refinados', []))
        borde = "#E66C32" if activo else "#333333"
        self.barra_refinar.setStyleSheet(
            f"#BarraRefinar {{ background: #1D1D1D; border: 1px solid {borde}; "
            f"border-radius: 8px; }}"
            "#InputRefinar { background: #242424; border: 1px solid #3A3A3A; "
            "border-radius: 6px; padding: 4px 8px; color: #EAEAEA; }"
            "#InputRefinar:focus { border: 1px solid #E66C32; }")
        self.btn_ref_limpiar.setStyleSheet(
            "QPushButton { background: transparent; color: #999999; border: 1px solid "
            "#3A3A3A; border-radius: 6px; padding: 3px 10px; }"
            "QPushButton:hover { color: #E66C32; border-color: #E66C32; }")
        # Botón de profundidad: encendido = naranja sólido
        if self.btn_profundo.isChecked():
            self.btn_profundo.setStyleSheet(
                "QPushButton { background: #E66C32; color: #141414; font-weight: 700; "
                "border: 1px solid #E66C32; border-radius: 6px; padding: 3px 10px; }")
        else:
            self.btn_profundo.setStyleSheet(
                "QPushButton { background: transparent; color: #999999; border: 1px solid "
                "#3A3A3A; border-radius: 6px; padding: 3px 10px; }"
                "QPushButton:hover { color: #E66C32; border-color: #E66C32; }")
        # V2.0.8: el texto de ayuda depende del modo (SI/NO), asi que lo pone
        # _pintar_modo_refinar en vez de fijarlo aqui y pisarlo
        self._pintar_modo_refinar()

    def _on_profundo_toggled(self, activo):
        """Cambia entre componentes directos y cualquier nivel (V2.0.3).
        Afecta al refinado y al modo 'conjuntos que lo lleven'."""
        self._pintar_estilo_refinar()
        self.qsettings.setValue("busqueda_profunda", 1 if activo else 0)
        if activo:
            self.toast.show_message(
                "Buscando también dentro de los subconjuntos\n(puede tardar unos segundos más)", 3000)
        if getattr(self, '_refinados', []):
            self._aplicar_refinados()          # recalcular niveles con la nueva profundidad
        elif getattr(self, 'modo_busqueda', 'nombre') == 'contiene' and self.input_buscar.text().strip():
            self.ejecutar_busqueda(auto=True)  # relanzar la búsqueda de conjuntos

    def _pintar_modo_refinar(self):
        """Marca visualmente el modo activo (V2.0.8). El QSS de la app no
        distingue lo bastante un QPushButton checkable, y el usuario no sabia
        cual estaba activo: aqui el activo va relleno y el otro apagado."""
        try:
            negativo = self.btn_ref_no.isChecked()
            for btn, activo, color in (
                    (self.btn_ref_si, not negativo, "#E66C32"),
                    (self.btn_ref_no, negativo, "#5B9BD5")):
                if activo:
                    btn.setStyleSheet(
                        f"QPushButton {{ background: {color}; color: #141414; "
                        f"border: 1px solid {color}; border-radius: 10px; "
                        f"padding: 4px 12px; font-weight: 800; }}")
                else:
                    btn.setStyleSheet(
                        "QPushButton { background: transparent; color: #777777; "
                        "border: 1px solid #4A4A4A; border-radius: 10px; "
                        "padding: 4px 12px; font-weight: 600; }"
                        f"QPushButton:hover {{ color: {color}; border-color: {color}; }}")
            self.input_refinar.setPlaceholderText(
                "ej. MOTOR REM 0.37KW   (Enter aplica)" if not negativo
                else "ej. MOTOR REM 0.37KW   (se quitaran los que lo lleven)")
        except Exception as e:
            logger.debug(f"Pintando modo de refinado: {e}")

    def _agregar_refinado(self, negativo=False):
        """Enter en la barra de refinado: apila un nivel (chip) y aplica.
        V2.0.8: negativo=True apila 'que NO contengan' (botón NO). También se
        acepta escribir el término con un '-' delante."""
        term = self.input_refinar.text().strip()
        # El modo lo manda el selector SI/NO de la barra; el '-' delante sigue
        # valiendo como atajo para quien escribe rapido
        if not negativo and getattr(self, 'btn_ref_no', None) is not None:
            negativo = self.btn_ref_no.isChecked()
        if term.startswith('-') and len(term) > 1:
            negativo = True
            term = term[1:].strip()
        if not term:
            return

        # V2.1.1 - COORDINACION CON LA BUSQUEDA GENERAL.
        # Antes habia que pulsar Enter arriba y LUEGO refinar: si escribias un
        # termino nuevo en el cuadro principal y aplicabas el refinado, este se
        # aplicaba sobre los resultados de la busqueda ANTERIOR (o sobre nada),
        # y parecia que "no busca bien". Ahora, si el cuadro principal no
        # corresponde a la base actual, se lanza primero la busqueda general y
        # el refinado se aplica solo en cuanto llegan los resultados.
        termino_arriba = self.input_buscar.text().strip()
        base = getattr(self, '_res_base', None)
        desfasado = bool(termino_arriba) and termino_arriba != getattr(
            self, '_termino_base', None)
        if not base or desfasado:
            if not termino_arriba:
                self.lbl_status.setText(
                    "Escribe primero qué buscar en el cuadro de arriba")
                self.toast.show_message(
                    "Escribe primero qué buscar arriba y luego refina")
                return
            logger.info("Refinado '%s' en espera: se lanza antes la busqueda "
                        "general de '%s'", term, termino_arriba)
            self._refinado_pendiente = ('no_contiene' if negativo else 'contiene', term)
            self.input_refinar.clear()
            self.lbl_status.setText("Buscando «%s» para poder refinar…" % termino_arriba)
            antes = getattr(self, '_gen_busqueda', 0)
            # V2.3.1: el refinado queda atado a SU búsqueda, y hay que atarlo
            # ANTES de lanzarla: dentro de ejecutar_busqueda hay un
            # processEvents, y por ahí puede entrar la respuesta de una
            # búsqueda anterior aún en vuelo. Si llega con el refinado suelto,
            # se lo lleva, lo aplica sobre la base equivocada, y la búsqueda
            # buena lo borra al llegar. La generación que tendrá es la
            # siguiente, porque ejecutar_busqueda la incrementa en uno.
            self._gen_refinado_pendiente = antes + 1
            self.ejecutar_busqueda()
            if getattr(self, '_gen_busqueda', 0) == antes:
                # La busqueda no llego a lanzarse (p.ej. sin ningun origen
                # marcado). Se descarta el refinado pendiente: dejarlo colgado
                # haria que se aplicase solo en una busqueda posterior.
                self._refinado_pendiente = None
                self.input_refinar.setText(term)
                logger.warning("Refinado '%s' descartado: la busqueda general "
                               "no se lanzo", term)
            return

        if not hasattr(self, '_refinados'):
            self._refinados = []
        self._refinados.append(('no_contiene' if negativo else 'contiene', term))
        self.input_refinar.clear()
        self._aplicar_refinados()

    def _agregar_refinado_negativo(self):
        self._agregar_refinado(negativo=True)

    def _limpiar_refinados(self):
        """Quita todos los niveles: vuelve a la búsqueda base."""
        self._refinados = []
        self.input_refinar.clear()
        self._aplicar_refinados()

    def _quitar_refinado(self, idx=None):
        """Quita el último nivel (Esc) o uno concreto (✕ de su chip).
        Devuelve True si había algo que quitar."""
        refs = getattr(self, '_refinados', [])
        if not refs:
            return False
        if idx is None:
            refs.pop()
        elif 0 <= idx < len(refs):
            refs.pop(idx)
        self._aplicar_refinados()
        return True

    def _aplicar_refinados(self):
        """Recalcula desde la base aplicando la pila de refinados en orden
        (+ el borrador en vivo del modo Nombre) y repinta con el pipeline
        por tramos de la búsqueda."""
        base = getattr(self, '_res_base', []) or []
        res = base
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            for modo, term in getattr(self, '_refinados', []):
                if not res:
                    break
                if modo == 'nombre':
                    res = [d for d in res if self._casa_termino_local(d[0], term)]
                else:
                    # V2.0.8: el negativo es el COMPLEMENTO del mismo conjunto.
                    # Un PDF o una pieza no llevan componentes indexados, así
                    # que "no lo contienen" y se quedan: es lo que literalmente
                    # se ha pedido, y el chip lo dice para que no sorprenda.
                    keep = self.db.filtrar_por_componente(
                        [d[10] for d in res], term,
                        profundo=self.btn_profundo.isChecked())
                    if modo == 'no_contiene':
                        res = [d for d in res if d[10] not in keep]
                    else:
                        res = [d for d in res if d[10] in keep]
        except Exception as e:
            logger.error(f"Error aplicando refinados: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        # invalidar cualquier pintado en curso y repintar el subconjunto
        self._gen_busqueda = getattr(self, '_gen_busqueda', 0) + 1
        ctx = {'termino': '', 'auto': True, 't0': time.time(), 'refino': len(base)}
        if not getattr(self, '_refinados', []):
            ctx.pop('refino')  # sin niveles: vuelve al estado de búsqueda normal
        self._pintar_resultados(res, ctx)

    def _actualizar_barra_refinar(self):
        """Visibilidad de la barra, chips por nivel, botón Limpiar, contador
        X → Y y borde activo (V2.0.3)."""
        try:
            base = getattr(self, '_res_base', []) or []
            refs = getattr(self, '_refinados', [])
            activo = bool(refs)
            self.barra_refinar.setVisible(bool(base))
            # reconstruir chips (solo niveles fijados; el borrador vive en el input)
            while self.chips_refinar.count():
                w = self.chips_refinar.takeAt(0).widget()
                if w:
                    w.deleteLater()
            for i, (modo, term) in enumerate(refs):
                negativo = (modo == 'no_contiene')
                icono = "≡" if modo == 'nombre' else ("⊘" if negativo else "⚙")
                etiqueta = term if len(term) <= 22 else term[:20] + "…"
                prefijo = "NO " if negativo else ""
                chip = QPushButton(f"{i+1}· {icono} {prefijo}{etiqueta}  ✕")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip(
                    ("Nivel %d — En el nombre: " if modo == 'nombre'
                     else ("Nivel %d — NO contiene la pieza: " if negativo
                           else "Nivel %d — Contiene la pieza: ")) % (i + 1)
                    + term + "\nClic para quitar este nivel")
                # V2.0.8: el nivel negativo en azul apagado, para no confundirlo
                # de un vistazo con los que SÍ exigen la pieza
                col = "#5B9BD5" if negativo else "#E66C32"
                fondo = "#12202A" if negativo else "#2A1B12"
                chip.setStyleSheet(
                    f"QPushButton {{ background: {fondo}; color: {col}; "
                    f"border: 1px solid {col}; border-radius: 10px; "
                    f"padding: 2px 10px; font-size: 11px; font-weight: 600; }}"
                    f"QPushButton:hover {{ background: {col}; color: #141414; }}")
                chip.clicked.connect(lambda _, k=i: self._quitar_refinado(k))
                self.chips_refinar.addWidget(chip)
            self.btn_ref_limpiar.setVisible(activo)
            if activo:
                n_fmt = f"{self.tabla.rowCount():,}".replace(",", ".")
                b_fmt = f"{len(base):,}".replace(",", ".")
                self.lbl_refinar_count.setText(f"{b_fmt} → {n_fmt}")
            else:
                self.lbl_refinar_count.setText("")
            self._pintar_estilo_refinar()
        except Exception as e:
            logger.debug(f"Error actualizando barra de refinado: {e}")

    # ═══════════════════════════════════════════
    # INDEXACIÓN (Cambio 2: modal selectivo + cancelar)
    # ═══════════════════════════════════════════
    def confirmar_indexacion(self):
        """Abre el diálogo de indexación para el NAS nuevo (v1.0.7)"""
        dialog = DialogIndexacion(RUTAS_NAS, self)
        dialog.setWindowTitle("Configurar Indexación NAS")
        if dialog.exec_() == QDialog.Accepted:
            origenes = dialog.get_companeros_seleccionados()
            anos = dialog.get_años_seleccionados()
            if origenes:
                self.iniciar_indexacion(origenes, anos)
            else:
                avisar_atencion(self, "Atención", "No has seleccionado ningún origen.")

    def iniciar_indexacion(self, origenes_sel, anos_sel):
        """Inicia la indexación del NAS nuevo (v1.0.7)"""
        self.btn_indexar.setEnabled(False)
        self.btn_cancelar.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminado
        
        self.lbl_status.setText(f"Iniciando indexación de {len(origenes_sel)} orígenes...")
        
        self.thread = IndexadorThread(self.db, RUTAS_NAS, origenes_sel, anos_sel)
        self.thread.status.connect(self.lbl_status.setText)
        self.thread.progress.connect(lambda n: self.lbl_count.setText(f"{n} archivos indexados"))
        self.thread.comp_finished.connect(self.on_comp_indexado)
        self.thread.finished.connect(self.finalizar_indexacion)
        self.thread.error.connect(
            lambda e: mostrar_error("Error de indexación",
                                    "La indexación del NAS ha fallado.", e, self))
        self.thread.start()

    def cancelar_indexacion(self):
        if hasattr(self, 'thread') and self.thread and self.thread.isRunning():
            self.thread.cancelar()
            self.lbl_status.setText("⏹ Cancelando... esperando a que termine el origen actual")
            self.btn_cancelar.setEnabled(False)

    def on_comp_indexado(self, comp, count):
        self.lbl_status.setText(f"✅ {comp}: {count} archivos indexados")

    def finalizar_indexacion(self, total, tiempo):
        self.progress_bar.setVisible(False)
        self.btn_indexar.setEnabled(True)
        self.btn_cancelar.setVisible(False)
        self.btn_cancelar.setEnabled(True)
        self._actualizar_estado_indice()  # V2.0.0: refrescar "● Índice hace X"
        self.lbl_status.setText("Indexación completada")
        self.lbl_count.setText(f"{total} archivos en total")
        
        QMessageBox.information(self, "Éxito", f"Se han indexado {total} archivos en {tiempo:.1f} segundos.")
        self.lbl_status.setText(f"Última indexación: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        self.refrescar_filtros_jerarquicos()
        # V2.3.0: el índice ha cambiado — recalcular la cascada de propiedades
        self._props_ctx_kwargs = None
        self._refrescar_props_contexto()

    # ═══════════════════════════════════════════
    # PREVISUALIZACIÓN (Cambio 4)
    # ═══════════════════════════════════════════


    @staticmethod
    def _preview_embebido_dwg(ruta):
        """Extrae la miniatura embebida en la cabecera de un DWG (V2.0.3).
        Formato: offset 0x0D = puntero a la sección de preview (sentinel 16B +
        tamaño 4B + nº imágenes 1B + entradas [código 1B, inicio 4B, tamaño 4B]).
        Código 2 = BMP sin BITMAPFILEHEADER (se antepone), código 6 = PNG.
        Devuelve QImage o None. Python puro: no necesita AutoCAD."""
        import struct
        try:
            with open(ruta, 'rb') as f:
                head = f.read(0x11)
                if len(head) < 0x11 or head[:2] != b'AC':
                    return None
                pos = struct.unpack('<I', head[0x0D:0x11])[0]
                if pos <= 0:
                    return None
                f.seek(pos + 16)  # saltar sentinel
                f.read(4)         # tamaño total de la sección
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
                            img = QImage.fromData(data)
                            return img if not img.isNull() else None
                        # BMP crudo: anteponer BITMAPFILEHEADER
                        dib = struct.unpack('<I', data[0:4])[0]
                        bpp = struct.unpack('<H', data[14:16])[0]
                        paleta = 0
                        if bpp <= 8:
                            ncol = struct.unpack('<I', data[32:36])[0] or (1 << bpp)
                            paleta = ncol * 4
                        offset = 14 + dib + paleta
                        fh = b'BM' + struct.pack('<IHHI', 14 + len(data), 0, 0, offset)
                        img = QImage.fromData(fh + data, 'BMP')
                        return img if not img.isNull() else None
        except Exception:
            pass
        return None

    def _swap_thumb_worker(self, vistas_pendientes):
        """Reemplaza el worker de miniaturas SIN bloquear el hilo de UI (V2.0.3).
        Antes se hacía thumb_worker.wait(500), que congelaba la app al encadenar
        búsquedas/filtros si el worker estaba leyendo un archivo lento del NAS.
        Ahora el worker viejo se cancela y se deja morir solo (referenciado en
        una lista hasta que emite finished, para no destruirlo en pleno vuelo)."""
        old = getattr(self, 'thumb_worker', None)
        if old is not None:
            try:
                old.thumbnail_ready.disconnect(self.on_thumbnail_ready)
            except (TypeError, RuntimeError):
                pass
            old.cancelar()
            if old.isRunning():
                if not hasattr(self, '_workers_muriendo'):
                    self._workers_muriendo = []
                self._workers_muriendo.append(old)
                old.finished.connect(lambda o=old: self._limpiar_worker_muerto(o))
        self.thumb_worker = ThumbnailWorker(vistas_pendientes, self.extraer_miniatura_raw,
                                            db=self.db)  # V2.0.3: lotes de BD
        self.thumb_worker.thumbnail_ready.connect(self.on_thumbnail_ready)
        self.thumb_worker.start()

    def _limpiar_worker_muerto(self, worker):
        try:
            self._workers_muriendo.remove(worker)
        except (ValueError, AttributeError):
            pass

    # Extensiones cuya miniatura se cachea en BD (pase nocturno)
    _EXT_CACHEABLE = ('.sldprt', '.sldasm', '.slddrw', '.pdf', '.dwg',
                      '.step', '.stp', '.iges', '.igs')

    def extraer_miniatura_raw(self, ruta, size=256):
        """Devuelve (QImage, hbitmap) permitiendo su uso seguro en QThreads (V1.0.3)"""
        try:
            ruta_canonica = ruta  # clave de la caché de BD (tal cual se indexó)
            ext = Path(ruta).suffix.lower()

            # 0a. TAMAÑO MINIATURA (tabla/galería): caché de BD PRIMERO, sin
            # tocar el NAS (V2.0.3). Antes se probaba el shell de Windows —que
            # lee el archivo del NAS— en cada búsqueda, y además se hacía un
            # os.path.exists por cada fila: lento y causa de los cuelgues.
            # El preview grande (size>256) sigue renderizando en local para
            # máxima calidad más abajo.
            if size <= 256 and ext in self._EXT_CACHEABLE:
                try:
                    data = self.db.obtener_miniatura(ruta_canonica)
                    if data:
                        image = QImage.fromData(data)
                        if not image.isNull():
                            return image, 0
                except Exception as e:
                    logger.debug(f"Miniatura BD falló para {ruta_canonica}: {e}")

            # A partir de aquí sí hace falta el archivo real (miss de caché o
            # preview grande): resolvemos host y comprobamos existencia.
            ruta = ruta_accesible(ruta)  # V2.0.1: host accesible (IP/NASCENTRAL)
            if not ruta or not os.path.exists(ruta):
                return None, 0

            # 0. PDF: renderizar la primera página SIEMPRE con PyMuPDF (V2.0.3).
            # El proveedor de miniaturas de Adobe registra su ICONO como si fuera
            # una miniatura válida (incluso con THUMBNAILONLY, según la caché del
            # shell), así que el shell no es fiable para PDF.
            if ext == '.pdf':
                try:
                    import fitz
                    doc = fitz.open(ruta)
                    if doc.page_count > 0:
                        page = doc[0]
                        mat = fitz.Matrix(2, 2) if size <= 256 else fitz.Matrix(4, 4)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        image = QImage(pix.samples, pix.width, pix.height,
                                       pix.stride, QImage.Format_RGB888).copy()
                        doc.close()
                        if not image.isNull():
                            return image, 0
                    else:
                        doc.close()
                except Exception as e:
                    logger.debug(f"PyMuPDF falló para PDF: {e}")

            # 0b. DWG: miniatura embebida en la cabecera del archivo (V2.0.3).
            # Igual que Adobe, el proveedor de AutoCAD mete su icono en la caché
            # del shell — la extracción directa es determinista y sin AutoCAD.
            if ext == '.dwg':
                img = self._preview_embebido_dwg(ruta)
                if img is not None:
                    return img, 0

            # 1. PRIORIZAR IShellItemImageFactory (Calidad Explorador de Windows).
            # Con THUMBNAILONLY: falla limpio si no hay proveedor real (equipos
            # sin SolidWorks) y se pasa a los fallbacks de abajo (V2.0.3).
            try:
                hbitmap = self._thumbnail_via_shell_factory(ruta, size)
                if hbitmap and hbitmap != 0:
                    return None, hbitmap
            except Exception as e:
                logger.debug(f"IShellItemImageFactory falló: {e}")

            # 2. FALLBACK A EXTRACTORES ESPECÍFICOS
            # SolidWorks: archivos antiguos son OLE con PreviewPNG embebido
            if ext in ('.sldprt', '.sldasm', '.slddrw'):
                try:
                    import olefile
                    if olefile.isOleFile(ruta):
                        with olefile.OleFileIO(ruta) as ole:
                            if ole.exists('PreviewPNG'):
                                data = ole.openstream('PreviewPNG').read()
                                image = QImage.fromData(data)
                                if not image.isNull():
                                    return image, 0
                except Exception:
                    logger.debug(f"OLE fallback para: {ruta}")

            # V2.0.3: caché central de miniaturas en BD.
            # - SW: para equipos sin SolidWorks (los modernos no son OLE y el
            #   shell no tiene proveedor allí).
            # - STEP/IGES: no llevan preview embebido; se renderizan de noche
            #   en el indexador (gmsh) y todos los equipos las leen de aquí.
            if ext in ('.sldprt', '.sldasm', '.slddrw', '.step', '.stp', '.iges', '.igs'):
                try:
                    data = self.db.obtener_miniatura(ruta_canonica)
                    if data:
                        image = QImage.fromData(data)
                        if not image.isNull():
                            return image, 0
                except Exception as e:
                    logger.debug(f"Miniatura BD falló para {ruta_canonica}: {e}")

        except Exception as e:
            logger.debug(f"Error en extraer_miniatura_raw: {e}")
        
        return None, 0

    def extraer_miniatura(self, ruta, size=256):
        """Extrae miniatura (QPixmap) para el hilo principal (Compatible hacia atrás)"""
        # V2.0.3: NO reescribir aquí — extraer_miniatura_raw necesita la ruta
        # canónica original como clave de la caché de miniaturas en BD (y ya
        # hace su propio ruta_accesible internamente).
        ruta_local = ruta_accesible(ruta)  # V2.0.1: host accesible (IP/NASCENTRAL)
        if not ruta_local or not os.path.exists(ruta_local):
            return None

        # V2.0.3: clave (ruta, size) — el preview grande pide 1024 y la tabla 256
        clave = (ruta, size)
        if clave in self.cache_miniaturas:
            return self.cache_miniaturas[clave]

        if len(self.cache_miniaturas) > 100:
            self.cache_miniaturas.clear()

        image, hbitmap = self.extraer_miniatura_raw(ruta, size)
        pixmap = None
        
        if hbitmap != 0:
            pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapPremultipliedAlpha)
            if pixmap.isNull():
                pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapNoAlpha)
            import ctypes
            ctypes.windll.gdi32.DeleteObject(hbitmap)
        elif image is not None and not image.isNull():
            pixmap = QPixmap.fromImage(image)

        if not pixmap:
            # 4. Fallback: icono del sistema (SHGetFileInfo)
            try:
                res = shell.SHGetFileInfo(ruta_local, 0, shellcon.SHGFI_ICON | shellcon.SHGFI_LARGEICON)
                hicon = res[0]
                if hicon:
                    pixmap = QtWin.fromHICON(hicon)
                    import ctypes
                    from ctypes import c_void_p
                    ctypes.windll.user32.DestroyIcon.argtypes = [c_void_p]
                    ctypes.windll.user32.DestroyIcon(hicon)
            except Exception:
                pass

        if pixmap and not pixmap.isNull():
            self.cache_miniaturas[clave] = pixmap
            return pixmap

        return None

    def _thumbnail_via_shell_factory(self, ruta, size=256):
        """Usa IShellItemImageFactory via COM para thumbnails de calidad Explorador"""
        import ctypes
        from ctypes import POINTER, byref, c_void_p, c_int, c_long, c_ulong
        
        class GUID(ctypes.Structure):
            _fields_ = [
                ('Data1', c_ulong),
                ('Data2', ctypes.c_ushort),
                ('Data3', ctypes.c_ushort),
                ('Data4', ctypes.c_ubyte * 8),
            ]
        
        class SIZE(ctypes.Structure):
            _fields_ = [('cx', c_long), ('cy', c_long)]
        
        # IID de IShellItemImageFactory: {bcc18b79-ba16-442f-80c4-8a59c30c463b}
        IID = GUID(0xbcc18b79, 0xba16, 0x442f,
                   (ctypes.c_ubyte * 8)(0x80, 0xc4, 0x8a, 0x59, 0xc3, 0x0c, 0x46, 0x3b))
        
        # Eliminado CoInitialize explícito aquí para evitar conflictos de hilos (V1.0.3 Repaired)
        try:
            ppv = c_void_p()
            hr = ctypes.windll.shell32.SHCreateItemFromParsingName(
                ctypes.c_wchar_p(ruta), None, byref(IID), byref(ppv))
            
            if hr != 0 or not ppv.value:
                logger.debug(f"SHCreateItemFromParsingName falló: hr=0x{hr & 0xFFFFFFFF:08X}")
                return None
            
            try:
                # Acceder a vtable COM: IUnknown(0,1,2) + GetImage(3)
                vtable_pp = ctypes.cast(ppv, POINTER(POINTER(c_void_p)))
                vtable = vtable_pp[0]
                
                # GetImage(this, SIZE size, SIIGBF flags, HBITMAP* phbm)
                GetImageFunc = ctypes.WINFUNCTYPE(c_long, c_void_p, SIZE, c_int, POINTER(c_void_p))
                get_image = GetImageFunc(vtable[3])
                
                sz = SIZE(size, size)
                # V2.0.3: THUMBNAILONLY — sin él, el shell devuelve el ICONO del
                # tipo de archivo como si fuera miniatura (Adobe para PDF, genérico
                # para SW en equipos sin SolidWorks) y cortocircuitaba los fallbacks
                # buenos (render PDF con PyMuPDF, caché de miniaturas en BD).
                SIIGBF_BIGGERSIZEOK = 0x01
                SIIGBF_THUMBNAILONLY = 0x04
                hbitmap = c_void_p()

                hr = get_image(ppv, sz, SIIGBF_BIGGERSIZEOK | SIIGBF_THUMBNAILONLY,
                               byref(hbitmap))
                
                if hr == 0 and hbitmap.value:
                    return int(hbitmap.value)
                else:
                    logger.debug(f"GetImage falló: hr=0x{hr & 0xFFFFFFFF:08X}")
            finally:
                # Release COM (índice 2 del vtable)
                vtable_pp2 = ctypes.cast(ppv, POINTER(POINTER(c_void_p)))
                vtable2 = vtable_pp2[0]
                ReleaseFunc = ctypes.WINFUNCTYPE(c_ulong, c_void_p)
                release = ReleaseFunc(vtable2[2])
                release(ppv)
        except Exception as e:
            logger.debug(f"Error en ThumbnailFactory COM: {e}")
        
        return None

    def actualizar_preview(self, current, previous=None):
        """
        Actualiza inmediatamente el texto (feedback instantáneo) y lanza timer para recursos pesados (V1.0.05)
        """
        try:
            if not current or not hasattr(current, 'row'):
                return
                
            row = current.row()
            if row < 0 or row >= self.tabla.rowCount():
                return
                
            def get_text(col):
                try:
                    item = self.tabla.item(row, col)
                    return item.text() if item else ""
                except: return ""

            # Mapeo según nuevo orden V1.0.6: 
            # 0:Ruta, 1:Orden, 2:CodProy, 3:NomProy, 4:Vista, 5:Nombre, 
            # 6:Desc, 7:Comp, 8:Año, 9:Cliente, 10:Proy, 11:CodOrd, 12:NomOrd, ... 22:Tipo
            nombre = get_text(5)
            comp = get_text(6)
            año = get_text(7)
            cliente = get_text(8)
            proyecto = get_text(9)
            tipo = get_text(20)
            cod_proy = get_text(2)
            nom_proy = get_text(3)
            orden_completa = get_text(10)
            ruta = get_text(0)
            
            if not nombre or not ruta:
                self.btn_abrir_carpeta.setEnabled(False)
                self.btn_copiar_ruta.setEnabled(False)
                self.btn_copiar_nombre.setEnabled(False)
                return

            self.btn_abrir_carpeta.setEnabled(True)
            self.btn_copiar_ruta.setEnabled(True)
            self.btn_copiar_nombre.setEnabled(True)

            # 1. ACTUALIZACIÓN INSTANTÁNEA (Solo Texto) — V2.0.1: filas clave-valor
            self.lbl_preview_nombre.setText(nombre)
            ext = Path(nombre).suffix.lower()
            tipo_desc = DESCRIPCIONES_EXTENSION.get(ext, 'Archivo')

            # Píldora de tipo (reutiliza colores de PillDelegate)
            tipo_pill = {'.sldprt': ('Pieza', '#E66C32'), '.sldasm': ('Ensamblaje', '#3BA55D'),
                         '.slddrw': ('Plano', '#5B8DD9'), '.dwg': ('Plano', '#5B8DD9'),
                         '.pdf': ('PDF', '#C75450')}.get(ext, (tipo_desc, '#999999'))
            self.lbl_preview_pill.setText(tipo_pill[0])
            self.lbl_preview_pill.setStyleSheet(
                f"background-color: {tipo_pill[1]}33; color: {tipo_pill[1]}; "
                f"border: 1px solid {tipo_pill[1]}; border-radius: 9px; "
                f"padding: 2px 10px; font-size: 11px; font-weight: 700;")
            self.lbl_preview_pill.setVisible(True)

            proy_str = f"{cod_proy} {nom_proy}" if cod_proy else (nom_proy if nom_proy else proyecto)
            proy_str = etiqueta_origen(proy_str)  # V2.0.0: unificar ALSI_ESTANDAR etc.
            self._meta_vals['origen'].setText(comp or "—")
            self._meta_vals['anio'].setText(str(año) if año else "—")
            self._meta_vals['cliente'].setText(cliente or "—")
            self._meta_vals['proyecto'].setText(proy_str or "—")
            self._meta_vals['orden'].setText(orden_completa or "—")
            self._meta_vals['tamano'].setText("Cargando…")
            self.meta_widget.setVisible(True)
            self.lbl_preview_ruta.setText(ruta)

            # Mostrar miniatura cacheada inmediatamente o placeholder (V1.0.4 Fix)
            # V2.0.3: caché en memoria → caché de BD (2-5ms) → badge.
            # La versión en alta calidad la trae el PreviewWorker justo después.
            pm_cache = (self.cache_miniaturas.get((ruta, 1024))
                        or self.cache_miniaturas.get((ruta, 256)))
            # V2.1.3: la miniatura del PROPIO archivo (la misma que pinta la
            # galería) se guarda como REFERENCIA. Sirve para reconocer después
            # si lo que devuelve el shell es el render de verdad o el icono
            # genérico, y no dejar que este último tape al bueno.
            pm_referencia = None
            if ext in self._EXT_CACHEABLE:
                try:
                    data_bd = self.db.obtener_miniatura(ruta)
                    if data_bd:
                        img_bd = QImage.fromData(data_bd)
                        if not img_bd.isNull():
                            pm_referencia = QPixmap.fromImage(img_bd)
                except Exception as e:
                    logger.debug(f"Miniatura BD (preview instantáneo) falló: {e}")
            self._preview_referencia = (ruta, pm_referencia)
            if pm_cache is None:
                pm_cache = pm_referencia
            # V2.0.8: si no hay nada en caché, aprovechar el icono que la TABLA
            # ya tiene cargado para esa fila. La tabla puede obtener la miniatura
            # por vías que el panel no usa (el generador del shell sobre el NAS),
            # y de ahí venía que se viera en la lista pero no en el panel.
            if pm_cache is None:
                try:
                    it_vista = self.tabla.item(row, 4)
                    if it_vista and not it_vista.icon().isNull():
                        pm_tabla = it_vista.icon().pixmap(QSize(512, 512))
                        if not pm_tabla.isNull() and pm_tabla.width() > 32:
                            pm_cache = pm_tabla
                except Exception as e:
                    logger.debug(f"Icono de tabla como preview: {e}")

            if pm_cache:
                self._set_preview_imagen(pm_cache)
                self.lbl_preview_icon.setText("")
                self.preview_opacity.setOpacity(1.0)
            else:
                # V2.0.0: badge de extensión en vez de emoji
                self.lbl_preview_icon.setText("")
                self._set_preview_imagen(pixmap_badge_extension(ext, size=96))
                self.preview_opacity.setOpacity(0.5)
            
            # 2. DIFERIR RECURSOS PESADOS (Miniatura, os.path.exists, etc.)
            self.current_preview_data = {
                'ruta': ruta, 'tipo': tipo, 'ext': ext
            }
            self.timer_preview.start(100) # (V1.0.05) Esperar 100ms antes de cargar la ruta

        except Exception as e:
            logger.debug(f"Error actualizando preview inicial: {e}")

    def set_cell_thumbnail(self, ruta, pixmap):
        """Helper para poner el pixmap como icono del QTableWidgetItem de la celda Vista (V1.0.4 Fix).
        Busca la fila por el UserRole(ruta) almacenado en la columna 0."""
        try:
            scaled = pixmap.scaled(50, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon = QIcon(scaled)
            for r in range(self.tabla.rowCount()):
                item_ruta = self.tabla.item(r, 0)
                if item_ruta and item_ruta.text() == ruta:
                    # Aplicamos el icono en la columna VISTA (4)
                    item_vista = self.tabla.item(r, 4)
                    if item_vista:
                        item_vista.setIcon(icon)
                    return
        except Exception as e:
            logger.debug(f"Error set_cell_thumbnail: {e}")

    def on_thumbnail_ready(self, row, ruta, image, hbitmap):
        """Callback ejecutado en el hilo UI cuando el ThumbnailWorker extrae una miniatura (V1.0.4 Fix).
        Usa la ruta para encontrar la fila correcta, independiente del orden de la tabla."""
        try:
            pixmap = None
            if hbitmap and hbitmap != 0:
                pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapPremultipliedAlpha)
                if not pixmap or pixmap.isNull():
                    pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapNoAlpha)
                
                import ctypes
                from ctypes import c_void_p
                ctypes.windll.gdi32.DeleteObject.argtypes = [c_void_p]
                ctypes.windll.gdi32.DeleteObject(hbitmap)
                
            elif image is not None and not image.isNull():
                pixmap = QPixmap.fromImage(image)

            if pixmap and not pixmap.isNull():
                # V2.0.3: guardar a 320px — suficiente para la galería XL/zoom
                # (antes 160px: QIcon no amplía y en XL la imagen no crecía) y
                # con memoria acotada (la caché limita a ~100 entradas).
                if pixmap.width() > 320 or pixmap.height() > 320:
                    pixmap = pixmap.scaled(320, 320, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation)
                if len(self.cache_miniaturas) > 100:
                    self.cache_miniaturas.clear()
                self.cache_miniaturas[(ruta, 256)] = pixmap

                # Poner miniatura en la celda correcta (busca por ruta, no por row)
                self.set_cell_thumbnail(ruta, pixmap)

                # V2.0.0: actualizar también la tarjeta de la galería si existe
                try:
                    card = self._galeria_items.get(ruta)
                    if card:
                        card.setIcon(QIcon(self._pixmap_para_galeria(pixmap)))
                except RuntimeError:
                    pass
                
                # Si la fila seleccionada tiene esta ruta, actualizar el panel derecho
                try:
                    current_row = self.tabla.currentRow()
                    if current_row >= 0:
                        current_item = self.tabla.item(current_row, 4)
                        if current_item and current_item.data(Qt.UserRole) == ruta:
                            self._set_preview_imagen(pixmap)
                            self.lbl_preview_icon.setText("")
                except RuntimeError:
                    pass  # Widget eliminado durante búsqueda rápida
                    
        except Exception as e:
            logger.debug(f"Error renderizando miniatura remota fila {row}: {e}")

    # ═══════════════════════════════════════════
    # ORDENACIÓN 3-STATES
    # ═══════════════════════════════════════════
    def on_header_clicked(self, logicalIndex):
        header = self.tabla.horizontalHeader()
        
        # Ignorar clics en columnas técnicas ocultas (0, 1, 2, 3)
        if logicalIndex < 4: return

        if self._sort_state["col"] == logicalIndex:
            if self._sort_state["order"] == Qt.AscendingOrder:
                self._sort_state["order"] = Qt.DescendingOrder
                header.setSortIndicator(logicalIndex, Qt.DescendingOrder)
                self.tabla.sortItems(logicalIndex, Qt.DescendingOrder)
            else:
                self._sort_state["col"] = -1
                header.setSortIndicatorShown(False)
                # Ordenar por nuestra columna oculta de Orden_Orig (1)
                self.tabla.sortItems(1, Qt.AscendingOrder)
        else:
            self._sort_state["col"] = logicalIndex
            self._sort_state["order"] = Qt.AscendingOrder
            header.setSortIndicatorShown(True)
            header.setSortIndicator(logicalIndex, Qt.AscendingOrder)
            self.tabla.sortItems(logicalIndex, Qt.AscendingOrder)

    def _actualizar_info_documental(self, ruta_canonica):
        """V2.0.3: filas 'Plano' y 'Componentes' del preview + botón similares.
        Consultas indexadas (~ms) sobre datos ya en BD."""
        ext = Path(ruta_canonica).suffix.lower()
        nombre = os.path.basename(ruta_canonica)
        fila_plano = fila_comps = False
        similares = False
        try:
            if ext in ('.sldprt', '.sldasm'):
                codigo = self.db._codigo_de_nombre(nombre)
                if codigo:
                    docs = self.db.buscar_documentacion_de(nombre)
                    partes = []
                    for d_ext, d_ruta in docs:
                        etq = "plano" if d_ext == '.slddrw' else d_ext.lstrip('.').upper()
                        partes.append(f'✓ {etq} <a href="{d_ruta}" style="color:#E66C32;">abrir</a>')
                    if partes:
                        self._meta_vals['plano'].setText(" · ".join(partes))
                    else:
                        self._meta_vals['plano'].setText(
                            '<span style="color:#C7A23F;">✗ sin plano ni PDF</span>')
                    fila_plano = True
                similares = (ext == '.sldprt')
            if ext == '.sldasm':
                total, rotos = self.db.resumen_componentes(ruta_canonica)
                if total:
                    if rotos:
                        self._meta_vals['comps'].setText(
                            f'{total} · <span style="color:#C7A23F;">⚠ {rotos} no indexado(s)</span>')
                    else:
                        self._meta_vals['comps'].setText(str(total))
                    fila_comps = True
        except Exception as e:
            logger.debug(f"Error en info documental de {ruta_canonica}: {e}")
        # V2.0.8: peso y superficie del archivo seleccionado. Se ocultan las
        # filas si no hay dato, en vez de enseñar un "—" que no dice nada.
        hay_peso = False
        try:
            fis = self.db.propiedades_fisicas(ruta_canonica)
            if fis and fis[0]:
                self._meta_vals['peso'].setText(
                    f"<b>{fis[0]:,.2f} kg</b>".replace(",", "."))
                self._meta_vals['peso'].setTextFormat(Qt.RichText)
                hay_peso = True
        except Exception as e:
            logger.debug(f"Propiedades físicas de {ruta_canonica}: {e}")
        self._meta_keys['peso'].setVisible(hay_peso)
        self._meta_vals['peso'].setVisible(hay_peso)

        self._meta_keys['plano'].setVisible(fila_plano)
        self._meta_vals['plano'].setVisible(fila_plano)
        self._meta_keys['comps'].setVisible(fila_comps)
        self._meta_vals['comps'].setVisible(fila_comps)
        self.btn_similares.setVisible(similares)

    def _actualizar_preview_recursos_pesados(self):
        """Ejecutado por el timer_preview tras 100ms de inactividad (V1.0.5).
        V2.0.3: lo pesado (NAS + render 1024) va a un PreviewWorker — el clic
        en una pieza ya no congela la interfaz."""
        try:
            data = self.current_preview_data
            ruta = data.get('ruta')
            if not ruta: return
            self._actualizar_info_documental(ruta)  # consultas BD (~ms)

            self._gen_preview = getattr(self, '_gen_preview', 0) + 1
            worker = PreviewWorker(self._gen_preview, ruta, self.extraer_miniatura_raw)
            worker.resultado.connect(self._on_preview_pesado)
            if not hasattr(self, '_preview_workers'):
                self._preview_workers = []
            self._preview_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._limpiar_preview_worker(w))
            worker.start()
        except Exception as e:
            logger.debug(f"Error en recursos diferidos: {e}")

    def _limpiar_preview_worker(self, worker):
        try:
            self._preview_workers.remove(worker)
        except (ValueError, AttributeError):
            pass

    # V2.1.3 - Umbral de parecido entre la miniatura del archivo (la que se ve
    # en la galería) y lo que devuelve el shell de Windows. Medido sobre
    # ensamblajes reales: cuando el shell renderiza de verdad el parecido es
    # 99,6-99,8 %; cuando devuelve el icono genérico de SolidWorks (el cubo
    # amarillo y azul) cae a 35-36 %. 85 % queda lejos de los dos grupos.
    UMBRAL_PREVIEW_PARECIDO = 0.85

    @staticmethod
    def _grises_reducidos(pixmap, lado=32):
        """La imagen reducida a lado x lado en escala de grises."""
        img = pixmap.toImage().convertToFormat(QImage.Format_RGB32).scaled(
            lado, lado, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        from PyQt5.QtGui import qRed, qGreen, qBlue
        datos = []
        for y in range(lado):
            for x in range(lado):
                p = img.pixel(x, y)
                datos.append((qRed(p) * 3 + qGreen(p) * 6 + qBlue(p)) // 10)
        return datos

    @classmethod
    def _huella_imagen(cls, pixmap):
        """Huella de la imagen. Dos archivos DISTINTOS no pueden tener la misma
        vista previa pixel a pixel: si se repite, es un icono genérico."""
        import hashlib
        try:
            return hashlib.md5(
                bytes(bytearray(cls._grises_reducidos(pixmap)))).hexdigest()
        except Exception:
            return None

    @classmethod
    def _parecido_imagenes(cls, a, b):
        """0..1 — cuánto se parecen dos imágenes (1 = idénticas)."""
        try:
            ga, gb = cls._grises_reducidos(a), cls._grises_reducidos(b)
            dif = sum(abs(x - y) for x, y in zip(ga, gb)) / float(len(ga))
            return max(0.0, 1.0 - dif / 255.0)
        except Exception:
            return 1.0      # ante la duda, no se descarta nada

    def _on_preview_pesado(self, gen, ruta, tam_txt, image, hbitmap):
        """Aplica el resultado del PreviewWorker si sigue siendo el vigente."""
        try:
            if gen != getattr(self, '_gen_preview', 0):
                # obsoleto: liberar el HBITMAP si venía uno
                if hbitmap:
                    import ctypes
                    from ctypes import c_void_p
                    ctypes.windll.gdi32.DeleteObject.argtypes = [c_void_p]
                    ctypes.windll.gdi32.DeleteObject(hbitmap)
                return
            self.lbl_preview_tamaño.setText(tam_txt)

            pixmap = None
            if hbitmap:
                pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapPremultipliedAlpha)
                if pixmap.isNull():
                    pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapNoAlpha)
                import ctypes
                from ctypes import c_void_p
                ctypes.windll.gdi32.DeleteObject.argtypes = [c_void_p]
                ctypes.windll.gdi32.DeleteObject(hbitmap)
            elif image is not None and not image.isNull():
                pixmap = QPixmap.fromImage(image)

            if pixmap and not pixmap.isNull():
                # V2.1.3 - EL ICONO GENERICO NO DEBE TAPAR LA MINIATURA BUENA.
                # El shell de Windows, cuando no sabe renderizar un ensamblaje,
                # devuelve el icono genérico de SolidWorks (el cubo amarillo y
                # azul) — el MISMO para archivos distintos, comprobado. Antes se
                # aplicaba sin mirar y machacaba la miniatura real que ya estaba
                # puesta: en la galería se veía la pieza y en el panel derecho
                # ese cubo. Si lo que llega no se parece a la miniatura del
                # propio archivo, se descarta y se conserva la buena.
                ref = getattr(self, '_preview_referencia', None)
                if ref and ref[0] == ruta and ref[1] is not None:
                    parecido = self._parecido_imagenes(ref[1], pixmap)
                    if parecido < self.UMBRAL_PREVIEW_PARECIDO:
                        logger.info(
                            "Vista previa del shell descartada (parecido %.0f%% "
                            "con la miniatura del archivo): %s",
                            parecido * 100, os.path.basename(ruta))
                        return          # se conserva la miniatura del archivo

                # Segundo criterio, este exacto: si el shell devuelve la MISMA
                # imagen para dos archivos distintos, es un icono genérico, se
                # parezca o no a la miniatura. Cubre tambien el icono de Adobe
                # en los PDF. El coste de equivocarse es nulo: se conserva la
                # miniatura del archivo, que tambien es correcta.
                huella = self._huella_imagen(pixmap)
                if huella:
                    if not hasattr(self, '_huellas_shell'):
                        self._huellas_shell = {}
                        self._huellas_genericas = set()
                    if huella in self._huellas_genericas:
                        return
                    duena = self._huellas_shell.get(huella)
                    if duena is not None and duena != ruta:
                        self._huellas_genericas.add(huella)
                        logger.info(
                            "Vista previa del shell descartada (icono genérico: "
                            "misma imagen que %s): %s",
                            os.path.basename(duena), os.path.basename(ruta))
                        return
                    if len(self._huellas_shell) > 500:
                        self._huellas_shell.clear()
                    self._huellas_shell[huella] = ruta
                if len(self.cache_miniaturas) > 100:
                    self.cache_miniaturas.clear()
                self.cache_miniaturas[(ruta, 1024)] = pixmap
                self._set_preview_imagen(pixmap)
                self.lbl_preview_icon.setText("")
                self.preview_opacity.setOpacity(1.0)
        except Exception as e:
            logger.debug(f"Error aplicando preview pesado: {e}")

    # ═══════════════════════════════════════════
    # ACCIONES
    # ═══════════════════════════════════════════
    def abrir_carpeta_seleccionada(self):
        row = self.tabla.currentRow()
        if row >= 0:
            item = self.tabla.item(row, 0)
            self._abrir_en_explorador(item.text() if item else "")

    def _abrir_en_explorador(self, ruta_canonica):
        """Abre el Explorador con el archivo seleccionado (V2.0.9).
        Reintenta con todos los hosts del NAS y, si falla, dice POR QUÉ en vez
        de culpar siempre al servidor."""
        ruta, motivo = resolver_para_abrir(ruta_canonica)
        if motivo == 'ok':
            subprocess.Popen(f'explorer /select,"{ruta}"')
            return True
        logger.warning(f"No se pudo abrir ({motivo}): {ruta_canonica}")
        if motivo == 'archivo_no_esta':
            # la carpeta sí existe: se abre igualmente, es más útil que un error
            carpeta = os.path.dirname(ruta)
            QMessageBox.information(self, "El archivo ha cambiado de sitio",
                                    MENSAJES_RUTA[motivo])
            try:
                os.startfile(carpeta)
            except Exception:
                pass
            return False
        QMessageBox.warning(
            self, "No se puede abrir",
            MENSAJES_RUTA.get(motivo, "Ruta no accesible.")
            + chr(10) + chr(10) + "Ruta:" + chr(10) + ruta_canonica)
        return False

    def copiar_ruta_seleccionada(self):
        row = self.tabla.currentRow()
        if row >= 0:
            ruta = ruta_accesible(self.tabla.item(row, 0).text())  # V2.0.1: host accesible
            QApplication.clipboard().setText(ruta)
            self.lbl_status.setText("✅ Ruta copiada al portapapeles")
            self.toast.show_message(f"✅ Ruta copiada:\n{os.path.basename(ruta)}")

    def toggle_preview_panel(self):
        is_visible = self.panel_preview.isVisible()
        self.panel_preview.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_preview.setText("Mostrar Previsualizador")
            self.btn_toggle_preview.setIcon(svg_icon("expandir-panel"))
        else:
            self.btn_toggle_preview.setText("Ocultar Previsualizador")
            self.btn_toggle_preview.setIcon(svg_icon("contraer-panel"))
            sizes = self.splitter.sizes()
            if len(sizes) > 1 and sizes[1] == 0:
                sizes[1] = 250
                self.splitter.setSizes(sizes)

    def cambiar_densidad_tabla(self, index):
        # V2.0.0: Cómoda fila 64/miniatura 56 · Compacta fila 40/miniatura 36
        if index == 0:  # Cómoda
            self.tabla.verticalHeader().setDefaultSectionSize(64)
            self.tabla.setIconSize(QSize(56, 56))
        else:           # Compacta
            self.tabla.verticalHeader().setDefaultSectionSize(40)
            self.tabla.setIconSize(QSize(36, 36))

    def _export_to_csv(self, rows):
        if not rows: return
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Exportar a Excel (CSV)", "Listado_Piezas.csv", "Archivos CSV (*.csv)")
        if not path: return
        
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                headers = []
                for j in range(5, self.tabla.columnCount()):
                    h_item = self.tabla.horizontalHeaderItem(j)
                    # V2.0.0: las columnas abreviadas (L/T/F/S/P/M) guardan el nombre completo en el tooltip
                    headers.append(h_item.toolTip() or h_item.text())
                writer.writerow(headers)
                
                for r in rows:
                    row_data = []
                    for j in range(5, self.tabla.columnCount()):
                        item = self.tabla.item(r, j)
                        row_data.append(item.text() if item else "")
                    writer.writerow(row_data)
            self.toast.show_message("✅ Exportado con éxito")
        except Exception as e:
            mostrar_error("Error al exportar",
                          "No se ha podido guardar el archivo.", e, self)

    def exportar_excel_completo(self):
        rows = list(range(self.tabla.rowCount()))
        self._export_to_csv(rows)
        
    def exportar_excel_seleccion(self):
        rows = sorted(list(set(item.row() for item in self.tabla.selectedItems())))
        self._export_to_csv(rows)

    def keyPressEvent(self, event):
        # Keyboard First Navigation (V2.0.0: el buscador es self.input_buscar)
        if event.key() == Qt.Key_F and event.modifiers() == Qt.ControlModifier:
            self.input_buscar.setFocus()
            self.input_buscar.selectAll()
            event.accept()
        elif event.key() == Qt.Key_R and event.modifiers() == Qt.ControlModifier:
            # V2.0.3: Ctrl+R → saltar a la barra de refinado
            if self.barra_refinar.isVisible():
                self.input_refinar.setFocus()
                self.input_refinar.selectAll()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            # V2.0.3: Esc deshace el refinado nivel a nivel hasta la búsqueda base
            if self.input_refinar.text():
                self.input_refinar.clear()  # limpia el borrador en vivo
            elif getattr(self, '_refinados', []):
                self._quitar_refinado()
            elif self.input_buscar.hasFocus():
                self.input_buscar.clear()
            elif self.panel_preview.isVisible():
                # Usar el toggle para que el botón del footer quede coherente
                self.toggle_preview_panel()
            event.accept()
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.tabla.hasFocus():
                self.abrir_carpeta_seleccionada()
                event.accept()
        elif event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
            self.copiar_nombre_seleccionado()
            event.accept()
        elif event.key() == Qt.Key_C and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier):
            self.copiar_ruta_seleccionada()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mostrar_menu_contextual(self, pos, origen_widget=None):
        # V2.0.0: origen_widget permite invocarlo desde la galería (posición correcta del popup)
        widget_menu = origen_widget if origen_widget is not None else self.tabla
        if self.tabla.currentRow() >= 0:
            menu = QMenu()
            # V2.0.0: estilo oscuro heredado del QSS global (QSS_EXTRAS)
            action_open = QAction(svg_icon("carpeta"), "Abrir Carpeta", self)
            action_open.triggered.connect(self.abrir_carpeta_seleccionada)
            action_copy = QAction(svg_icon("copiar-ruta"), "Copiar Ruta", self)
            action_copy.triggered.connect(self.copiar_ruta_seleccionada)
            action_copy_name = QAction(svg_icon("copiar-nombre-lapiz"), "Copiar Nombre", self)
            action_copy_name.triggered.connect(self.copiar_nombre_seleccionado)
            
            menu.addAction(action_open)
            menu.addAction(action_copy)
            menu.addAction(action_copy_name)

            # Columna 0 = Ruta Completa (V2.0.1: host accesible IP/NASCENTRAL)
            item_ruta = self.tabla.item(self.tabla.currentRow(), 0)
            ruta_canonica = item_ruta.text() if item_ruta else ""

            # V2.0.2: ¿en qué ensamblajes se usa esta pieza? (piezas y subensamblajes)
            nombre_sel = self.tabla.item(self.tabla.currentRow(), 5)
            ext_sel = Path(nombre_sel.text()).suffix.lower() if nombre_sel else ""
            if ext_sel in ('.sldprt', '.sldasm'):
                menu.addSeparator()
                act_donde = QAction(svg_icon("proyectos-maletin"), "¿En qué ensamblajes se usa?", self)
                act_donde.triggered.connect(lambda: self.mostrar_donde_se_usa(ruta_canonica))
                menu.addAction(act_donde)

            # V2.0.2: despiece del ensamblaje (misma tabla 'componentes')
            if ext_sel == '.sldasm':
                act_bom = QAction(svg_icon("ensamblaje-cubo"), "Ver componentes (despiece)", self)
                act_bom.triggered.connect(lambda: self.mostrar_despiece(ruta_canonica))
                menu.addAction(act_bom)
                # V2.0.3: ensamblajes que comparten un alto % de piezas
                act_sim_ens = QAction(svg_icon("comparar-balanza"), "Ensamblajes similares (piezas compartidas)", self)
                act_sim_ens.triggered.connect(lambda: self.mostrar_ensamblajes_similares(ruta_canonica))
                menu.addAction(act_sim_ens)

            # V2.0.3: posibles duplicados geométricos (misma vista previa)
            if ext_sel in ('.sldprt', '.sldasm'):
                act_dup = QAction(svg_icon("copiar-nombre-lapiz"), "Buscar piezas idénticas (duplicados)", self)
                act_dup.triggered.connect(lambda: self.mostrar_piezas_identicas(ruta_canonica))
                menu.addAction(act_dup)

            # V2.0.2: comparar componentes de 2 ensamblajes seleccionados
            filas_sel = sorted({it.row() for it in self.tabla.selectedItems()})
            if len(filas_sel) == 2:
                extensiones = []
                rutas_sel = []
                for r in filas_sel:
                    it_n = self.tabla.item(r, 5)
                    it_r = self.tabla.item(r, 0)
                    extensiones.append(Path(it_n.text()).suffix.lower() if it_n else "")
                    rutas_sel.append(it_r.text() if it_r else "")
                if extensiones == ['.sldasm', '.sldasm'] and all(rutas_sel):
                    act_cmp = QAction(svg_icon("comparar-balanza"), "Comparar componentes de los 2 ensamblajes", self)
                    act_cmp.triggered.connect(
                        lambda _, a=rutas_sel[0], b=rutas_sel[1]: self.comparar_ensamblajes(a, b))
                    menu.addAction(act_cmp)

            ruta = ruta_accesible(ruta_canonica)
            if ruta and os.path.exists(ruta):
                menu.addSeparator()
                # OJO: triggered pasa 'checked' (bool) como 1er argumento — hay que
                # absorberlo o os.startfile recibiría True (bug reportado V2.0.2)
                menu.addAction(svg_icon("arrastrar-solidworks"), "Abrir/Insertar en SolidWorks").triggered.connect(
                    lambda checked=False, r=ruta: os.startfile(r)
                )
                # V2.1.2: abrir directamente el PDF del plano
                menu.addAction(svg_icon("carpeta"), "Abrir PDF").triggered.connect(
                    lambda checked=False, r=ruta_canonica: self.abrir_pdf_de(r)
                )

            # Export selection option
            if len(self.tabla.selectedItems()) > self.tabla.columnCount(): # Si hay más de 1 fila seleccionada
                menu.addSeparator()
                action_export_sel = QAction(svg_icon("exportar-descargar"), "Exportar Selección a Excel", self)
                action_export_sel.triggered.connect(self.exportar_excel_seleccion)
                menu.addAction(action_export_sel)

            menu.exec_(widget_menu.mapToGlobal(pos))

    def _hover_tabla(self, tabla, col_ruta=0, por_texto=False):
        """Vista previa flotante al pasar el ratón (V2.0.6). En la rejilla
        principal la ruta es el TEXTO de la columna 0; en los diálogos viaja
        en Qt.UserRole de la columna de la miniatura."""
        def ruta_de(idx):
            it = tabla.item(idx.row(), col_ruta)
            if not it:
                return None
            return it.text() if por_texto else it.data(Qt.UserRole)
        return HoverPreview(tabla, ruta_de, self.db)

    def _hover_lista(self, lista):
        def ruta_de(idx):
            it = lista.item(idx.row())
            return it.data(Qt.UserRole) if it else None
        return HoverPreview(lista, ruta_de, self.db)

    def _abrir_en_solidworks(self, rutas):
        """Abre en SolidWorks los archivos indicados (V2.0.5).

        Se usa desde los diálogos de listas para no tener que volver a la
        rejilla principal. Con varios seleccionados pide confirmación, que
        abrir diez ensamblajes de golpe deja el equipo inservible un rato."""
        rutas = [r for r in (rutas or []) if r]
        if not rutas:
            return
        accesibles, faltan = [], []
        for r in rutas:
            ra = ruta_accesible(r)
            if ra and os.path.exists(ra):
                accesibles.append(ra)
            else:
                faltan.append(os.path.basename(r))
        if not accesibles:
            QMessageBox.warning(
                self, "No se encuentra el archivo",
                "No se ha podido acceder a:\n\n" + "\n".join(faltan[:8]))
            return
        if len(accesibles) > 3:
            if QMessageBox.question(
                    self, "Abrir varios en SolidWorks",
                    f"Se van a abrir {len(accesibles)} archivos en SolidWorks.\n"
                    "Puede tardar y consumir bastante memoria. ¿Continuar?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        abiertos = 0
        for ra in accesibles:
            try:
                os.startfile(ra)   # SolidWorks es el programa asociado a .sldasm/.sldprt
                abiertos += 1
            except Exception as e:
                logger.error(f"No se pudo abrir en SolidWorks {ra}: {e}")
                faltan.append(os.path.basename(ra))
        if abiertos:
            self.toast.show_message(
                f"✅ Abriendo en SolidWorks{'' if abiertos == 1 else f' ({abiertos})'}")
        if faltan:
            QMessageBox.warning(
                self, "Algunos archivos no se han abierto",
                "No se ha podido abrir:\n\n" + "\n".join(faltan[:8]))

    def _menu_archivos(self, widget, rutas, pos_global):
        """Menú contextual de los diálogos de resultados (V2.0.6).

        Ofrece LAS MISMAS acciones que la rejilla principal: los diálogos son
        búsquedas dentro de la búsqueda, así que no tiene sentido que sean de
        segunda clase. Las opciones se habilitan según la extensión, igual que
        en la rejilla."""
        rutas = [r for r in (rutas or []) if r]
        if not rutas:
            return
        principal = rutas[0]
        ext = Path(principal).suffix.lower()
        varias = len(rutas) > 1
        menu = QMenu(widget)

        act_sw = menu.addAction(
            svg_icon("arrastrar-solidworks"),
            "Abrir/Insertar en SolidWorks" + (f" ({len(rutas)})" if varias else ""))
        act_sw.triggered.connect(lambda _=False, rr=list(rutas): self._abrir_en_solidworks(rr))

        # V2.1.2: abrir el PDF del plano sin tener que buscarlo aparte
        act_pdf = menu.addAction(svg_icon("carpeta"), "Abrir PDF")
        act_pdf.triggered.connect(lambda _=False, r=principal: self.abrir_pdf_de(r))
        act_pdf.setToolTip("Abre el PDF que comparte código con este archivo")

        menu.addSeparator()
        menu.addAction(svg_icon("carpeta"), "Abrir Carpeta").triggered.connect(
            lambda _=False, r=principal: self._abrir_carpeta_de(r))
        menu.addAction(svg_icon("copiar-ruta"), "Copiar Ruta").triggered.connect(
            lambda _=False, r=principal: self._copiar_al_portapapeles(
                ruta_accesible(r), "Ruta copiada"))
        menu.addAction(svg_icon("copiar-nombre-lapiz"), "Copiar Nombre").triggered.connect(
            lambda _=False, r=principal: self._copiar_al_portapapeles(
                Path(r).stem, "Nombre copiado"))

        # Análisis: idénticas condiciones que en mostrar_menu_contextual
        if ext in ('.sldprt', '.sldasm'):
            menu.addSeparator()
            menu.addAction(svg_icon("proyectos-maletin"),
                           "¿En qué ensamblajes se usa?").triggered.connect(
                lambda _=False, r=principal: self.mostrar_donde_se_usa(r))
        if ext == '.sldasm':
            menu.addAction(svg_icon("ensamblaje-cubo"),
                           "Ver componentes (despiece)").triggered.connect(
                lambda _=False, r=principal: self.mostrar_despiece(r))
            menu.addAction(svg_icon("comparar-balanza"),
                           "Ensamblajes similares (piezas compartidas)").triggered.connect(
                lambda _=False, r=principal: self.mostrar_ensamblajes_similares(r))
        if ext in ('.sldprt', '.sldasm'):
            menu.addAction(svg_icon("copiar-nombre-lapiz"),
                           "Buscar piezas idénticas (duplicados)").triggered.connect(
                lambda _=False, r=principal: self.mostrar_piezas_identicas(r))
        if len(rutas) == 2 and all(Path(r).suffix.lower() == '.sldasm' for r in rutas):
            menu.addAction(svg_icon("comparar-balanza"),
                           "Comparar componentes de los 2 ensamblajes").triggered.connect(
                lambda _=False, a=rutas[0], b=rutas[1]: self.comparar_ensamblajes(a, b))

        menu.exec_(pos_global)

    def _menu_lista_archivos(self, lista, pos):
        """Menú del botón derecho sobre una ListaArrastrable de un diálogo."""
        it = lista.itemAt(pos)
        if it is not None and not it.isSelected():
            lista.setCurrentItem(it)   # clic derecho fuera de la selección: manda ese
        self._menu_archivos(lista, lista.rutas_seleccionadas(),
                            lista.viewport().mapToGlobal(pos))

    def _menu_tabla_archivos(self, tabla, pos, col_ruta=0):
        """Menú del botón derecho sobre las tablas de los diálogos. La ruta
        viaja en Qt.UserRole de la columna indicada."""
        it = tabla.itemAt(pos)
        if it is not None and not it.isSelected():
            tabla.setCurrentCell(it.row(), 0)
        self._menu_archivos(tabla, self._rutas_sel_tabla(tabla, col_ruta),
                            tabla.viewport().mapToGlobal(pos))

    @staticmethod
    def _rutas_sel_tabla(tabla, col_ruta=0):
        """Rutas de las filas seleccionadas de una tabla de diálogo."""
        vistas, rutas = set(), []
        for f in sorted({i.row() for i in tabla.selectedItems()}):
            it = tabla.item(f, col_ruta)
            r = it.data(Qt.UserRole) if it else None
            if r and r not in vistas:
                vistas.add(r)
                rutas.append(r)
        return rutas

    def _anadir_filtro_tabla(self, lay, tabla, etiqueta_vacio="filas"):
        """Cuadro para buscar DENTRO de la tabla de un diálogo (V2.1.2).

        Un despiece puede tener cientos de componentes; sin esto habia que
        recorrerlos a ojo. Filtra en vivo sobre TODAS las columnas de texto:
        se escriben varias palabras y deben aparecer todas (sin importar
        mayusculas ni acentos), en cualquier columna.
        """
        fila = QHBoxLayout()
        fila.setSpacing(8)
        caja = QLineEdit()
        caja.setPlaceholderText(
            "Buscar dentro de esta lista…  (varias palabras: deben aparecer todas)")
        caja.setClearButtonEnabled(True)
        fila.addWidget(caja, stretch=1)
        lbl = QLabel("")
        lbl.setObjectName("StatusDim")
        fila.addWidget(lbl)
        lay.addLayout(fila)

        def normalizar(t):
            try:
                return self.db.normalizar_texto(t)
            except Exception:
                return (t or "").upper()

        # Se cachea el texto de cada fila: filtrar no debe recorrer celdas en
        # cada pulsacion con cientos de componentes.
        cache = []
        for f in range(tabla.rowCount()):
            trozos = []
            for c in range(tabla.columnCount()):
                it = tabla.item(f, c)
                if it and it.text():
                    trozos.append(it.text())
            cache.append(normalizar(" ".join(trozos)))

        def aplicar(texto):
            palabras = [p for p in normalizar(texto).split() if p]
            visibles = 0
            for f in range(tabla.rowCount()):
                heno = cache[f] if f < len(cache) else ""
                casa = all(p in heno for p in palabras)
                tabla.setRowHidden(f, not casa)
                visibles += 1 if casa else 0
            total = tabla.rowCount()
            if palabras:
                lbl.setText("%d de %d %s" % (visibles, total, etiqueta_vacio))
                caja.setStyleSheet(
                    "border: 1.5px solid #E66C32;" if visibles else
                    "border: 1.5px solid #8C2F2F;")
            else:
                lbl.setText("%d %s" % (total, etiqueta_vacio))
                caja.setStyleSheet("")

        caja.textChanged.connect(aplicar)
        aplicar("")
        return caja

    def _anadir_filtro_lista(self, lay, lista, etiqueta_vacio="resultados"):
        """Igual que _anadir_filtro_tabla pero para los diálogos de lista
        (¿en qué ensamblajes se usa?). Filtra por el texto de cada fila."""
        fila = QHBoxLayout()
        fila.setSpacing(8)
        caja = QLineEdit()
        caja.setPlaceholderText(
            "Buscar dentro de esta lista…  (varias palabras: deben aparecer todas)")
        caja.setClearButtonEnabled(True)
        fila.addWidget(caja, stretch=1)
        lbl = QLabel("")
        lbl.setObjectName("StatusDim")
        fila.addWidget(lbl)
        lay.addLayout(fila)

        def normalizar(t):
            try:
                return self.db.normalizar_texto(t)
            except Exception:
                return (t or "").upper()

        cache = [normalizar(lista.item(i).text()) for i in range(lista.count())]

        def aplicar(texto):
            palabras = [p for p in normalizar(texto).split() if p]
            visibles = 0
            for i in range(lista.count()):
                casa = all(p in cache[i] for p in palabras)
                lista.item(i).setHidden(not casa)
                visibles += 1 if casa else 0
            total = lista.count()
            if palabras:
                lbl.setText("%d de %d %s" % (visibles, total, etiqueta_vacio))
                caja.setStyleSheet("border: 1.5px solid #E66C32;" if visibles
                                   else "border: 1.5px solid #8C2F2F;")
            else:
                lbl.setText("%d %s" % (total, etiqueta_vacio))
                caja.setStyleSheet("")

        caja.textChanged.connect(aplicar)
        aplicar("")
        return caja

    def pdfs_de(self, ruta):
        """PDFs asociados a un archivo (V2.1.2).

        Si el archivo YA es un PDF, es el suyo propio. Si es una pieza, un
        ensamblaje o un plano, se buscan los PDF que comparten codigo (mismo
        primer token del nombre: 24120.P027, CTS.E164...)."""
        if not ruta:
            return []
        if Path(ruta).suffix.lower() == '.pdf':
            return [ruta]
        try:
            docs = self.db.buscar_documentacion_de(os.path.basename(ruta))
        except Exception as e:
            logger.warning("No se ha podido buscar el PDF de %s: %s", ruta, e)
            return []
        return [r for ext, r in docs if ext == '.pdf' and r]

    def abrir_pdf_de(self, ruta):
        """Abre el PDF del plano (V2.1.2). Si hay varios, deja elegir."""
        pdfs = self.pdfs_de(ruta)
        if not pdfs:
            codigo = None
            try:
                codigo = self.db._codigo_de_nombre(os.path.basename(ruta))
            except Exception:
                pass
            self.toast.show_message(
                "No hay ningún PDF para %s" % (codigo or os.path.basename(ruta)))
            self.lbl_status.setText(
                "Sin PDF: no hay ningún PDF con el código %s en el índice"
                % (codigo or "de esta pieza"))
            return
        elegido = pdfs[0]
        if len(pdfs) > 1:
            from PyQt5.QtWidgets import QInputDialog
            nombres = [os.path.basename(p) for p in pdfs]
            nombre, ok = QInputDialog.getItem(
                self, "Varios PDF con este código",
                "Hay %d PDF para esta pieza. ¿Cuál abro?" % len(pdfs),
                nombres, 0, False)
            if not ok:
                return
            elegido = pdfs[nombres.index(nombre)]
        ruta_ok, motivo = resolver_para_abrir(elegido)
        if motivo == 'ok' and ruta_ok:
            try:
                os.startfile(ruta_ok)
                self.toast.show_message("Abriendo %s" % os.path.basename(elegido))
                return
            except Exception as e:
                logger.error("No se ha podido abrir el PDF %s: %s", elegido, e)
        mostrar_error("No se ha podido abrir el PDF",
                      "El PDF está en el índice pero no se ha podido abrir.",
                      "%s\nMotivo: %s" % (elegido, motivo), self)

    def _abrir_carpeta_de(self, ruta):
        """V2.0.9: mismo camino robusto que la rejilla (antes fallaba mudo)."""
        self._abrir_en_explorador(ruta)

    def _copiar_al_portapapeles(self, texto, aviso):
        if texto:
            QApplication.clipboard().setText(texto)
            self.toast.show_message(f"✅ {aviso}:\n{texto if len(texto) < 60 else os.path.basename(texto)}")

    def mostrar_donde_se_usa(self, ruta_pieza):
        """Diálogo: ensamblajes que contienen la pieza/subensamblaje (V2.0.2).
        Consulta indexada e instantánea contra la tabla 'componentes'."""
        try:
            nombre = os.path.basename(ruta_pieza)
            resultados = self.db.buscar_ensamblajes_de(ruta_pieza)

            dlg = QDialog(self)
            dlg.setWindowTitle("¿En qué ensamblajes se usa?")
            dlg.resize(680, 460)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(10)

            cab = QLabel(f'Ensamblajes que usan <span style="color:#E66C32;">{nombre}</span>')
            cab.setTextFormat(Qt.RichText)
            cab.setStyleSheet(
                f'font-family: "{FUENTES["h2"]}"; font-size: 14px; font-weight: 800; '
                f'color: #F5F5F5; background: transparent;')
            cab.setWordWrap(True)
            lay.addWidget(cab)

            lbl_n = QLabel(f"{len(resultados)} ensamblaje(s) encontrados")
            lbl_n.setObjectName("StatusDim")
            lay.addWidget(lbl_n)

            # V2.0.5: lista arrastrable — se pueden soltar los ensamblajes
            # directamente sobre SolidWorks para insertarlos, igual que desde
            # la rejilla principal
            lista = ListaArrastrable()
            lista.setAlternatingRowColors(False)
            # V2.0.3: miniaturas a la izquierda (caché de BD, una consulta)
            lista.setIconSize(QSize(48, 48))
            minis = {}
            try:
                minis = self.db.obtener_miniaturas_lote([r[5] for r in resultados if r[5]])
            except Exception as e:
                logger.debug(f"Miniaturas de 'dónde se usa' fallaron: {e}")
            for r in resultados:
                nom, origen, anio, cliente, proyecto, ruta_ens = r
                if nom:
                    meta = " · ".join(str(x) for x in [cliente, etiqueta_origen(proyecto or ""), anio] if x)
                    texto = f"{nom}\n   {meta}"
                else:
                    # El ensamblaje está en componentes pero no en archivos (raro)
                    texto = os.path.basename(ruta_ens)
                it = QListWidgetItem(texto)
                it.setData(Qt.UserRole, ruta_ens)
                icono_ok = False
                data_img = minis.get(ruta_ens)
                if data_img:
                    img = QImage.fromData(data_img)
                    if not img.isNull():
                        it.setIcon(QIcon(QPixmap.fromImage(img)))
                        icono_ok = True
                if not icono_ok:
                    it.setIcon(QIcon(pixmap_badge_extension('.sldasm', size=44)))
                lista.addItem(it)
            self._anadir_filtro_lista(lay, lista, 'ensamblajes')
            lay.addWidget(lista, stretch=1)

            if not resultados:
                aviso = QLabel(
                    "No se ha encontrado ningún ensamblaje que la contenga.\n\n"
                    "Nota: la relación de componentes se genera al reindexar el NAS. "
                    "Si esta función es nueva, ejecuta 'Reindexar NAS' para poblarla.")
                aviso.setStyleSheet("color: #999999; font-style: italic; background: transparent;")
                aviso.setWordWrap(True)
                lay.addWidget(aviso)

            def abrir_sel():
                it = lista.currentItem()
                if it:
                    self._abrir_carpeta_de(it.data(Qt.UserRole))
            lista.itemDoubleClicked.connect(lambda _: abrir_sel())

            # V2.0.5: abrir en SolidWorks desde aquí (botón, menú del botón
            # derecho y arrastre) sin volver a la rejilla principal
            def abrir_sw():
                rutas = lista.rutas_seleccionadas()
                if not rutas and lista.currentItem():
                    rutas = [lista.currentItem().data(Qt.UserRole)]
                self._abrir_en_solidworks(rutas)
            lista.setContextMenuPolicy(Qt.CustomContextMenu)
            lista.customContextMenuRequested.connect(
                lambda p: self._menu_lista_archivos(lista, p))
            self._hover_lista(lista)   # V2.0.6: vista previa grande al pasar el ratón

            ayuda = QLabel("Arrastra un ensamblaje sobre SolidWorks para insertarlo · "
                           "botón derecho para más opciones")
            ayuda.setObjectName("StatusDim")
            ayuda.setWordWrap(True)
            lay.addWidget(ayuda)

            footer = QHBoxLayout()
            footer.addStretch()
            btn_sw = QPushButton("Abrir en SolidWorks")
            btn_sw.setIcon(svg_icon("arrastrar-solidworks", size=15))
            btn_sw.setCursor(Qt.PointingHandCursor)
            btn_sw.clicked.connect(abrir_sw)
            btn_abrir = QPushButton("Abrir carpeta")
            btn_abrir.setIcon(svg_icon("carpeta", size=15))
            btn_abrir.setCursor(Qt.PointingHandCursor)
            btn_abrir.clicked.connect(abrir_sel)
            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.clicked.connect(dlg.accept)
            footer.addWidget(btn_sw)
            footer.addWidget(btn_abrir)
            footer.addWidget(btn_cerrar)
            lay.addLayout(footer)

            # Sin nada seleccionado los botones no hacen nada útil: se marca
            # la primera fila para que "Abrir en SolidWorks" funcione al vuelo
            if lista.count():
                lista.setCurrentRow(0)

            dlg.exec_()
        except Exception as e:
            logger.error(f"Error en 'dónde se usa' para {ruta_pieza}: {e}")

    # ═══════════════════════════════════════════
    # DESPIECE Y COMPARACIÓN DE ENSAMBLAJES (V2.0.2)
    # ═══════════════════════════════════════════
    def _export_csv_generico(self, headers, filas, nombre_defecto):
        """Exporta una lista de tuplas a CSV (mismo formato que la tabla: ';' + BOM)."""
        if not filas:
            return
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel (CSV)", nombre_defecto, "Archivos CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(headers)
                writer.writerows(filas)
            self.toast.show_message("✅ Exportado con éxito")
        except Exception as e:
            mostrar_error("Error al exportar",
                          "No se ha podido guardar el archivo.", e, self)

    @staticmethod
    def _abrir_en_explorer(ruta_canonica):
        """Abre el Explorador seleccionando el archivo (host accesible)."""
        if not ruta_canonica:
            return
        rr = ruta_accesible(ruta_canonica)
        if rr and os.path.exists(rr):
            subprocess.Popen(f'explorer /select,"{rr}"')

    def mostrar_despiece(self, ruta_ens):
        """Despiece (BOM) del ensamblaje: lista sus componentes desde la tabla
        'componentes', cruzados con el índice para traer metadatos (V2.0.2)."""
        try:
            nombre = os.path.basename(ruta_ens)
            filas = self.db.obtener_componentes_de(ruta_ens)

            dlg = QDialog(self)
            dlg.setWindowTitle("Componentes del ensamblaje")
            dlg.resize(820, 540)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(10)

            cab = QLabel(f'Componentes de <span style="color:#E66C32;">{nombre}</span>')
            cab.setTextFormat(Qt.RichText)
            cab.setStyleSheet(
                f'font-family: "{FUENTES["h2"]}"; font-size: 14px; font-weight: 800; '
                f'color: #F5F5F5; background: transparent;')
            cab.setWordWrap(True)
            lay.addWidget(cab)

            sin_indexar = sum(1 for f in filas if not f[1])
            texto_n = f"{len(filas)} componente(s)"
            if sin_indexar:
                texto_n += f" · {sin_indexar} sin indexar (referencia rota o carpeta excluida)"
            lbl_n = QLabel(texto_n)
            lbl_n.setObjectName("StatusDim")
            lay.addWidget(lbl_n)

            # V2.0.8: PESO TOTAL y SUPERFICIE A PINTAR del conjunto. Se suma lo
            # que hay; si falta el dato de algún componente se dice cuántos,
            # porque un total incompleto presentado como definitivo es peor que
            # no dar ninguno (con esto se manda a pintura un nº de m²).
            masas = [float(f[7]) for f in filas if f[7]]
            areas = [float(f[8]) for f in filas if f[8]]
            n_comp_reales = len(filas)
            faltan_masa = n_comp_reales - len(masas)
            if masas or areas:
                partes = []
                if masas:
                    total_kg = sum(masas)
                    partes.append(f'<b>Peso total: {total_kg:,.1f} kg</b>'
                                  .replace(",", "."))
                if areas:
                    total_m2 = sum(areas)
                    # Se dice "superficie total", no "a pintar": la app no sabe
                    # si la pieza va pintada, y afirmarlo sería inventárselo
                    partes.append(f'<b>Superficie total: {total_m2:,.2f} m²</b>'
                                  .replace(",", "."))
                aviso_falta = ""
                if faltan_masa:
                    aviso_falta = (f'<span style="color:#E0A030;"> · ojo: '
                                   f'{faltan_masa} de {n_comp_reales} componentes '
                                   f'sin datos, el total es parcial</span>')
                lbl_tot = QLabel("   ·   ".join(partes) + aviso_falta)
                lbl_tot.setTextFormat(Qt.RichText)
                lbl_tot.setWordWrap(True)
                lbl_tot.setStyleSheet(
                    "background: #33291F; border: 1px solid #E66C32; "
                    "border-radius: 8px; padding: 8px 12px; color: #F5F5F5; "
                    "font-size: 13px;")
                lay.addWidget(lbl_tot)
            else:
                lbl_tot = QLabel(
                    "Sin datos de peso todavía: se calculan en el pase nocturno. "
                    "Si el conjunto es reciente, mañana estarán.")
                lbl_tot.setObjectName("StatusDim")
                lbl_tot.setWordWrap(True)
                lay.addWidget(lbl_tot)

            # V2.0.6: arrastrable a SolidWorks + menú completo del botón derecho
            tabla = TablaDialogoArrastrable()
            tabla.setColumnCount(8)
            tabla.setHorizontalHeaderLabels(
                ["Vista", "Componente", "Peso (kg)", "Sup. (m²)",
                 "Cliente", "Proyecto", "Año", "Origen"])
            tabla.setRowCount(len(filas))
            tabla.setEditTriggers(QTableWidget.NoEditTriggers)
            tabla.setSelectionBehavior(QTableWidget.SelectRows)
            tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
            tabla.setContextMenuPolicy(Qt.CustomContextMenu)
            tabla.customContextMenuRequested.connect(
                lambda p: self._menu_tabla_archivos(tabla, p))
            self._hover_tabla(tabla)   # V2.0.6: vista previa grande al pasar el ratón
            tabla.verticalHeader().setVisible(False)
            tabla.setIconSize(QSize(48, 48))
            tabla.verticalHeader().setDefaultSectionSize(54)
            # V2.0.3: miniaturas desde la caché de BD (un solo query para todos)
            minis = self.db.obtener_miniaturas_lote([f[6] for f in filas if f[6]])
            for i, (comp, nom_a, origen, anio, cliente, proyecto, ruta_c, masa_c, area_c) in enumerate(filas):
                it_vista = QTableWidgetItem()
                it_vista.setData(Qt.UserRole, ruta_c or "")
                data_img = minis.get(ruta_c)
                if data_img:
                    img = QImage.fromData(data_img)
                    if not img.isNull():
                        it_vista.setIcon(QIcon(QPixmap.fromImage(img)))
                else:
                    ext = os.path.splitext(comp)[1].lower()
                    it_vista.setIcon(QIcon(pixmap_badge_extension(ext, size=44)))
                it1 = QTableWidgetItem(comp)
                it1.setData(Qt.UserRole, ruta_c or "")
                # V2.0.8: peso y superficie, ordenables como numeros (no texto)
                it_masa = QTableWidgetItem()
                if masa_c:
                    it_masa.setData(Qt.DisplayRole, round(float(masa_c), 3))
                else:
                    it_masa.setText("—")
                it_masa.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_area = QTableWidgetItem()
                if area_c:
                    it_area.setData(Qt.DisplayRole, round(float(area_c), 4))
                else:
                    it_area.setText("—")
                it_area.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                celdas = [
                    it_vista, it1, it_masa, it_area,
                    QTableWidgetItem(cliente or ("—" if nom_a else "no indexado")),
                    QTableWidgetItem(etiqueta_origen(proyecto or "") if proyecto else "—"),
                    QTableWidgetItem(str(anio) if anio else "—"),
                    QTableWidgetItem(etiqueta_origen(origen or "") if origen else "—"),
                ]
                for j, it in enumerate(celdas):
                    if not nom_a and j >= 1:  # componente no encontrado en el índice
                        it.setForeground(QColor("#888888"))
                    tabla.setItem(i, j, it)
            tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            for j in (2, 3, 4, 5, 6, 7):
                tabla.horizontalHeader().setSectionResizeMode(j, QHeaderView.ResizeToContents)
            tabla.setSortingEnabled(True)
            self._anadir_filtro_tabla(lay, tabla, 'componentes')
            lay.addWidget(tabla, stretch=1)

            if not filas:
                aviso = QLabel(
                    "No hay componentes registrados para este ensamblaje.\n\n"
                    "Nota: la relación de componentes se genera al reindexar el NAS. "
                    "Si el ensamblaje es reciente, se completará con la próxima indexación.")
                aviso.setStyleSheet("color: #999999; font-style: italic; background: transparent;")
                aviso.setWordWrap(True)
                lay.addWidget(aviso)

            def abrir_sel():
                it = tabla.item(tabla.currentRow(), 0) if tabla.currentRow() >= 0 else None
                if it:
                    self._abrir_en_explorer(it.data(Qt.UserRole))
            tabla.itemDoubleClicked.connect(lambda _: abrir_sel())

            footer = QHBoxLayout()
            btn_export = QPushButton("Exportar CSV")
            btn_export.setIcon(svg_icon("exportar-descargar", size=15))
            btn_export.setCursor(Qt.PointingHandCursor)
            btn_export.clicked.connect(lambda: self._export_csv_generico(
                ["Componente", "Peso (kg)", "Superficie (m2)", "Cliente",
                 "Proyecto", "Año", "Origen", "Ruta"],
                [(f[0], round(float(f[7]), 3) if f[7] else "",
                  round(float(f[8]), 4) if f[8] else "",
                  f[4] or "", etiqueta_origen(f[5] or "") if f[5] else "",
                  f[3] or "", etiqueta_origen(f[2] or "") if f[2] else "", f[6] or "")
                 for f in filas],
                f"Despiece_{os.path.splitext(nombre)[0]}.csv"))
            footer.addWidget(btn_export)
            footer.addStretch()
            btn_sw = QPushButton("Abrir en SolidWorks")
            btn_sw.setIcon(svg_icon("arrastrar-solidworks", size=15))
            btn_sw.setCursor(Qt.PointingHandCursor)
            btn_sw.clicked.connect(
                lambda: self._abrir_en_solidworks(tabla.rutas_seleccionadas()))
            btn_abrir = QPushButton("Abrir carpeta")
            btn_abrir.setIcon(svg_icon("carpeta", size=15))
            btn_abrir.setCursor(Qt.PointingHandCursor)
            btn_abrir.clicked.connect(abrir_sel)
            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.clicked.connect(dlg.accept)
            footer.addWidget(btn_sw)
            footer.addWidget(btn_abrir)
            footer.addWidget(btn_cerrar)
            lay.addLayout(footer)
            if tabla.rowCount():
                tabla.selectRow(0)

            dlg.exec_()
        except Exception as e:
            logger.error(f"Error en despiece de {ruta_ens}: {e}")

    def comparar_ensamblajes(self, ruta_a, ruta_b):
        """Diff de componentes entre dos ensamblajes: qué tiene cada uno y qué
        comparten (V2.0.2). Útil para ver qué cambió entre dos versiones."""
        try:
            nom_a = os.path.basename(ruta_a)
            nom_b = os.path.basename(ruta_b)
            comp_a = {f[0]: f for f in self.db.obtener_componentes_de(ruta_a)}
            comp_b = {f[0]: f for f in self.db.obtener_componentes_de(ruta_b)}
            solo_a = sorted(set(comp_a) - set(comp_b))
            solo_b = sorted(set(comp_b) - set(comp_a))
            comunes = sorted(set(comp_a) & set(comp_b))

            COL_A, COL_B, COL_COMUN = "#E66C32", "#5B8DD9", "#3BA55D"

            dlg = QDialog(self)
            dlg.setWindowTitle("Comparar componentes")
            dlg.resize(820, 560)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(10)

            cab = QLabel(
                f'<span style="color:{COL_A};">A · {nom_a}</span>'
                f'<span style="color:#777777;">  vs  </span>'
                f'<span style="color:{COL_B};">B · {nom_b}</span>')
            cab.setTextFormat(Qt.RichText)
            cab.setStyleSheet(
                f'font-family: "{FUENTES["h2"]}"; font-size: 14px; font-weight: 800; '
                f'color: #F5F5F5; background: transparent;')
            cab.setWordWrap(True)
            lay.addWidget(cab)

            lbl_n = QLabel(
                f"Solo en A: {len(solo_a)}   ·   Solo en B: {len(solo_b)}   ·   "
                f"En ambos: {len(comunes)}")
            lbl_n.setObjectName("StatusDim")
            lay.addWidget(lbl_n)

            # V2.0.3: columna "Vista" con miniaturas (caché de BD, una consulta),
            # igual que en el despiece
            # V2.0.6: arrastrable a SolidWorks + menú completo del botón derecho
            tabla = TablaDialogoArrastrable()
            tabla.setColumnCount(3)
            tabla.setHorizontalHeaderLabels(["Vista", "Componente", "Estado"])
            tabla.setEditTriggers(QTableWidget.NoEditTriggers)
            tabla.setSelectionBehavior(QTableWidget.SelectRows)
            tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
            tabla.setContextMenuPolicy(Qt.CustomContextMenu)
            tabla.customContextMenuRequested.connect(
                lambda p: self._menu_tabla_archivos(tabla, p))
            self._hover_tabla(tabla)   # V2.0.6: vista previa grande al pasar el ratón
            tabla.verticalHeader().setVisible(False)
            tabla.setIconSize(QSize(48, 48))
            tabla.verticalHeader().setDefaultSectionSize(54)
            datos = ([(c, "Solo en A", COL_A, comp_a[c][6]) for c in solo_a] +
                     [(c, "Solo en B", COL_B, comp_b[c][6]) for c in solo_b] +
                     [(c, "En ambos", COL_COMUN, comp_a[c][6]) for c in comunes])
            minis = {}
            try:
                minis = self.db.obtener_miniaturas_lote([d[3] for d in datos if d[3]])
            except Exception as e:
                logger.debug(f"Miniaturas de comparación fallaron: {e}")
            tabla.setRowCount(len(datos))
            for i, (comp, estado, color, ruta_c) in enumerate(datos):
                it_v = QTableWidgetItem()
                it_v.setData(Qt.UserRole, ruta_c or "")
                icono_ok = False
                data_img = minis.get(ruta_c)
                if data_img:
                    img = QImage.fromData(data_img)
                    if not img.isNull():
                        it_v.setIcon(QIcon(QPixmap.fromImage(img)))
                        icono_ok = True
                if not icono_ok:
                    ext_b = os.path.splitext(comp)[1].lower()
                    it_v.setIcon(QIcon(pixmap_badge_extension(ext_b, size=44)))
                it0 = QTableWidgetItem(comp)
                it0.setData(Qt.UserRole, ruta_c or "")
                it1 = QTableWidgetItem(estado)
                it1.setForeground(QColor(color))
                tabla.setItem(i, 0, it_v)
                tabla.setItem(i, 1, it0)
                tabla.setItem(i, 2, it1)
            tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self._anadir_filtro_tabla(lay, tabla, 'componentes')
            lay.addWidget(tabla, stretch=1)

            if not comp_a or not comp_b:
                vacios = " y ".join(n for n, c in ((nom_a, comp_a), (nom_b, comp_b)) if not c)
                aviso = QLabel(
                    f"Sin componentes registrados para: {vacios}.\n"
                    "La relación de componentes se genera al reindexar el NAS.")
                aviso.setStyleSheet("color: #999999; font-style: italic; background: transparent;")
                aviso.setWordWrap(True)
                lay.addWidget(aviso)

            def abrir_sel():
                it = tabla.item(tabla.currentRow(), 0) if tabla.currentRow() >= 0 else None
                if it:
                    self._abrir_en_explorer(it.data(Qt.UserRole))
            tabla.itemDoubleClicked.connect(lambda _: abrir_sel())

            footer = QHBoxLayout()
            btn_export = QPushButton("Exportar CSV")
            btn_export.setIcon(svg_icon("exportar-descargar", size=15))
            btn_export.setCursor(Qt.PointingHandCursor)
            btn_export.clicked.connect(lambda: self._export_csv_generico(
                ["Componente", "Estado", f"A: {nom_a}", f"B: {nom_b}"],
                [(c, e, "X" if e != "Solo en B" else "", "X" if e != "Solo en A" else "")
                 for c, e, _, _ in datos],
                f"Comparacion_{os.path.splitext(nom_a)[0]}_vs_{os.path.splitext(nom_b)[0]}.csv"))
            footer.addWidget(btn_export)
            footer.addStretch()
            btn_sw = QPushButton("Abrir en SolidWorks")
            btn_sw.setIcon(svg_icon("arrastrar-solidworks", size=15))
            btn_sw.setCursor(Qt.PointingHandCursor)
            btn_sw.clicked.connect(
                lambda: self._abrir_en_solidworks(tabla.rutas_seleccionadas()))
            btn_abrir = QPushButton("Abrir carpeta")
            btn_abrir.setIcon(svg_icon("carpeta", size=15))
            btn_abrir.setCursor(Qt.PointingHandCursor)
            btn_abrir.clicked.connect(abrir_sel)
            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.clicked.connect(dlg.accept)
            footer.addWidget(btn_sw)
            footer.addWidget(btn_abrir)
            footer.addWidget(btn_cerrar)
            lay.addLayout(footer)

            dlg.exec_()
        except Exception as e:
            logger.error(f"Error comparando {ruta_a} vs {ruta_b}: {e}")

    def _dialogo_tabla(self, titulo, cab_html, subtexto, columnas, filas_datos,
                       nombre_csv, col_ruta_userrole=0):
        """Diálogo genérico de resultados tabulares (V2.0.3): tabla ordenable,
        doble clic abre carpeta (UserRole de la col indicada), Exportar CSV.
        filas_datos: lista de tuplas; el último elemento de cada tupla es la
        ruta para abrir (no se muestra como columna)."""
        dlg = QDialog(self)
        dlg.setWindowTitle(titulo)
        dlg.resize(840, 560)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        cab = QLabel(cab_html)
        cab.setTextFormat(Qt.RichText)
        cab.setStyleSheet(
            f'font-family: "{FUENTES["h2"]}"; font-size: 14px; font-weight: 800; '
            f'color: #F5F5F5; background: transparent;')
        cab.setWordWrap(True)
        lay.addWidget(cab)

        lbl_n = QLabel(subtexto)
        lbl_n.setObjectName("StatusDim")
        lay.addWidget(lbl_n)

        # V2.0.3: columna "Vista" con la miniatura de cada fila (caché de BD,
        # una sola consulta) — igual que en el despiece, en TODOS los diálogos.
        # V2.0.6: arrastrable a SolidWorks y con el menú completo del botón
        # derecho, como la rejilla principal.
        tabla = TablaDialogoArrastrable()
        tabla.setColumnCount(len(columnas) + 1)
        tabla.setHorizontalHeaderLabels(["Vista"] + columnas)
        tabla.setRowCount(len(filas_datos))
        tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        tabla.setSelectionBehavior(QTableWidget.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        tabla.customContextMenuRequested.connect(
            lambda p: self._menu_tabla_archivos(tabla, p))
        self._hover_tabla(tabla)   # V2.0.6: vista previa grande al pasar el ratón
        tabla.verticalHeader().setVisible(False)
        tabla.setIconSize(QSize(48, 48))
        tabla.verticalHeader().setDefaultSectionSize(54)
        minis = {}
        try:
            minis = self.db.obtener_miniaturas_lote([f[-1] for f in filas_datos if f[-1]])
        except Exception as e:
            logger.debug(f"Miniaturas de diálogo fallaron: {e}")
        for i, fila in enumerate(filas_datos):
            ruta_abrir = fila[-1]
            it_v = QTableWidgetItem()
            it_v.setData(Qt.UserRole, ruta_abrir or "")
            data_img = minis.get(ruta_abrir)
            icono_ok = False
            if data_img:
                img = QImage.fromData(data_img)
                if not img.isNull():
                    it_v.setIcon(QIcon(QPixmap.fromImage(img)))
                    icono_ok = True
            if not icono_ok:
                ext_b = os.path.splitext(str(ruta_abrir or fila[0]))[1].lower()
                it_v.setIcon(QIcon(pixmap_badge_extension(ext_b, size=44)))
            tabla.setItem(i, 0, it_v)
            for j, val in enumerate(fila[:-1]):
                it = QTableWidgetItem()
                if isinstance(val, int):
                    it.setData(Qt.DisplayRole, val)  # ordena numéricamente
                else:
                    it.setText(str(val) if val else "—")
                tabla.setItem(i, j + 1, it)
        tabla.setSortingEnabled(True)
        tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for j in range(2, len(columnas) + 1):
            tabla.horizontalHeader().setSectionResizeMode(j, QHeaderView.ResizeToContents)
        self._anadir_filtro_tabla(lay, tabla, 'filas')
        lay.addWidget(tabla, stretch=1)

        def abrir_sel():
            it = tabla.item(tabla.currentRow(), 0) if tabla.currentRow() >= 0 else None
            if it and it.data(Qt.UserRole):
                self._abrir_en_explorer(it.data(Qt.UserRole))
        tabla.itemDoubleClicked.connect(lambda _: abrir_sel())

        ayuda = QLabel("Arrastra una fila sobre SolidWorks para insertarla · "
                       "botón derecho para más opciones")
        ayuda.setObjectName("StatusDim")
        ayuda.setWordWrap(True)
        lay.addWidget(ayuda)

        footer = QHBoxLayout()
        btn_export = QPushButton("Exportar CSV")
        btn_export.setIcon(svg_icon("exportar-descargar", size=15))
        btn_export.setCursor(Qt.PointingHandCursor)
        btn_export.clicked.connect(lambda: self._export_csv_generico(
            columnas + ["Ruta"], [tuple(f[:-1]) + (f[-1] or "",) for f in filas_datos], nombre_csv))
        footer.addWidget(btn_export)
        footer.addStretch()
        btn_sw = QPushButton("Abrir en SolidWorks")
        btn_sw.setIcon(svg_icon("arrastrar-solidworks", size=15))
        btn_sw.setCursor(Qt.PointingHandCursor)
        btn_sw.clicked.connect(
            lambda: self._abrir_en_solidworks(tabla.rutas_seleccionadas()))
        btn_abrir = QPushButton("Abrir carpeta")
        btn_abrir.setIcon(svg_icon("carpeta", size=15))
        btn_abrir.setCursor(Qt.PointingHandCursor)
        btn_abrir.clicked.connect(abrir_sel)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.clicked.connect(dlg.accept)
        footer.addWidget(btn_sw)
        footer.addWidget(btn_abrir)
        footer.addWidget(btn_cerrar)
        lay.addLayout(footer)
        if tabla.rowCount():
            tabla.selectRow(0)
        dlg.exec_()

    def mostrar_similares(self):
        """V2.0.3: piezas con el mismo material + espesor + procesos que la
        seleccionada. Evita rediseñar lo que ya existe."""
        try:
            row = self.tabla.currentRow()
            if row < 0:
                return
            ruta = self.tabla.item(row, 0).text()
            nombre = os.path.basename(ruta)
            filas = self.db.buscar_similares(ruta)
            if filas is None:
                self.toast.show_message("La pieza no tiene material indexado:\nno hay base para comparar.")
                return
            datos = [(nom, anio or 0, cli or "", etiqueta_origen(pro or "") if pro else "", rr)
                     for nom, anio, cli, pro, rr in filas]
            self._dialogo_tabla(
                "Piezas similares",
                f'Similares a <span style="color:#E66C32;">{nombre}</span>'
                f'<br><span style="font-size:11px; color:#999999;">mismo material, espesor y procesos de fabricación</span>',
                f"{len(datos)} pieza(s) encontradas",
                ["Pieza", "Año", "Cliente", "Proyecto"],
                datos,
                f"Similares_{os.path.splitext(nombre)[0]}.csv")
        except Exception as e:
            logger.error(f"Error en similares: {e}")

    def mostrar_ensamblajes_similares(self, ruta_ens):
        """V2.0.3: ensamblajes que comparten un alto % de piezas con el dado
        (ignorando tornillería ultra-común). Para encontrar máquinas parecidas."""
        try:
            nombre = os.path.basename(ruta_ens)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                filas = self.db.ensamblajes_similares(ruta_ens)
            finally:
                QApplication.restoreOverrideCursor()
            datos = [(nom or os.path.basename(ruta), f"{pct}%", com,
                      cli or "", etiqueta_origen(pro or "") if pro else "", anio or 0, ruta)
                     for nom, pct, com, ns, nm, cli, pro, anio, ruta in filas]
            self._dialogo_tabla(
                "Ensamblajes similares",
                f'Ensamblajes que comparten piezas con <span style="color:#E66C32;">{nombre}</span>'
                f'<br><span style="font-size:11px; color:#999999;">% sobre el ensamblaje mayor · '
                f'sin contar piezas ultra-comunes (tornillería)</span>',
                f"{len(datos)} ensamblaje(s) con piezas en común",
                ["Ensamblaje", "% común", "Piezas comunes", "Cliente", "Proyecto", "Año"],
                datos,
                f"Similares_{os.path.splitext(nombre)[0]}.csv")
        except Exception as e:
            logger.error(f"Error en ensamblajes similares: {e}")

    def mostrar_piezas_identicas(self, ruta_pieza):
        """V2.0.3: posibles duplicados geométricos — misma vista previa embebida
        bit a bit ('copia exacta' si además coincide el tamaño de archivo)."""
        try:
            nombre = os.path.basename(ruta_pieza)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                filas = self.db.piezas_identicas(ruta_pieza)
            finally:
                QApplication.restoreOverrideCursor()
            if not filas:
                self.toast.show_message(
                    "Sin duplicados detectados.\n(Se compara la vista previa del archivo;\n"
                    "si la pieza aún no tiene miniatura en caché, prueba mañana.)")
                return
            datos = [(nom, tipo, anio or 0, cli or "",
                      etiqueta_origen(pro or "") if pro else "", ruta)
                     for nom, tipo, anio, cli, pro, ruta in filas]
            self._dialogo_tabla(
                "Piezas idénticas (posibles duplicados)",
                f'Duplicados de <span style="color:#E66C32;">{nombre}</span>'
                f'<br><span style="font-size:11px; color:#999999;">misma vista previa embebida; '
                f'"copia exacta" = también el mismo tamaño de archivo</span>',
                f"{len(datos)} posible(s) duplicado(s)",
                ["Pieza", "Coincidencia", "Año", "Cliente", "Proyecto"],
                datos,
                f"Duplicados_{os.path.splitext(nombre)[0]}.csv")
        except Exception as e:
            logger.error(f"Error en piezas idénticas: {e}")

    def mostrar_reutilizadas(self):
        """V2.0.3: ranking de piezas usadas en más proyectos que NO están en
        biblioteca/estándar — candidatas a estandarizar."""
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                filas = self.db.piezas_mas_reutilizadas(50)
            finally:
                QApplication.restoreOverrideCursor()
            datos = [(nom, n_proy, n_ens, ruta or "") for nom, n_proy, n_ens, ruta in filas]
            self._dialogo_tabla(
                "Candidatas a biblioteca",
                'Piezas más reutilizadas <span style="color:#E66C32;">fuera de la biblioteca</span>',
                f"Top {len(datos)} piezas presentes en 2+ proyectos y que no están en "
                f"ALSI ESTANDAR ni BIBLIOTECA 3D — candidatas a estandarizar",
                ["Pieza", "Proyectos", "Ensamblajes"],
                datos,
                "Candidatas_a_biblioteca.csv")
        except Exception as e:
            logger.error(f"Error en reutilizadas: {e}")

    def mostrar_sin_vista_previa(self):
        """V2.2.0: conjuntos ordenados por cuántas de sus piezas han perdido la
        vista previa de Windows. Se abren desde aquí con el botón derecho
        ('Abrir en SolidWorks'), se reconstruye con Ctrl+Q y se guarda todo:
        una sola pasada recupera todas las miniaturas del conjunto."""
        try:
            self.lbl_status.setText("Buscando conjuntos con piezas sin vista previa…")
            QApplication.processEvents()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                filas = self.db.ensamblajes_sin_vista_previa(50)
            finally:
                QApplication.restoreOverrideCursor()
            if not filas:
                self.lbl_status.setText("No hay conjuntos con piezas sin vista previa.")
                avisar_usuario("Vistas previas",
                               "Ningún conjunto del índice tiene piezas sin vista previa.")
                return
            datos = [(nom, f"{sin_v} de {total}", anio or 0, cli or "",
                      etiqueta_origen(pro or "") if pro else "", ruta)
                     for nom, cli, pro, anio, sin_v, total, ruta in filas]
            self._dialogo_tabla(
                "Conjuntos con piezas sin vista previa",
                'Conjuntos que más vistas previas recuperan '
                '<span style="color:#E66C32;">de una sola pasada</span>',
                f"Top {len(datos)} · ábrelo en SolidWorks (botón derecho), reconstruye "
                f"con Ctrl+Q y guarda todo: se regeneran las miniaturas de sus piezas. "
                f"Una pieza cuenta si ninguna copia suya del índice tiene vista previa.",
                ["Conjunto", "Piezas sin vista", "Año", "Cliente", "Proyecto"],
                datos,
                "Conjuntos_sin_vista_previa.csv")
            self.lbl_status.setText(f"{len(datos)} conjuntos con piezas sin vista previa.")
        except Exception as e:
            logger.error(f"Error en conjuntos sin vista previa: {e}")
            mostrar_error("No se ha podido calcular el informe de vistas previas",
                          "El servidor no ha respondido a la consulta.",
                          detalle=str(e), parent=self)

    def copiar_nombre_seleccionado(self):
        """Acción proactiva: copiar el nombre del archivo SIN extensión
        (V2.0.3: 'código + descripción' listo para pegar en correos/ERP)"""
        row = self.tabla.currentRow()
        if row >= 0:
            nombre = self.tabla.item(row, 5).text() # Columna 5 = Nombre
            limpio = os.path.splitext(nombre)[0].strip()
            QApplication.clipboard().setText(limpio)
            self.lbl_status.setText(f"✅ Nombre copiado: {limpio}")
            self.toast.show_message(f"✅ Nombre copiado:\n{limpio}")

    # ═══════════════════════════════════════════
    # AYUDA E INFORMACIÓN (V1.0)
    # ═══════════════════════════════════════════
    def mostrar_ayuda(self):
        """Muestra la Guía Rápida en un diálogo"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Guía Rápida - Buscador ALSI")
            dialog.resize(760, 560)
            layout_v = QVBoxLayout(dialog)
            layout_v.setContentsMargins(12, 12, 12, 12)
            layout_v.setSpacing(8)

            # Estilo HTML compartido de las secciones (tema oscuro V2.0.0)
            style = """
            <style>
                h1 { color: #E66C32; font-size: 16px; margin-bottom: 5px;
                     border-bottom: 2px solid #E66C32; padding-bottom: 2px; }
                h2 { color: #F5F5F5; font-size: 13px; margin-top: 10px;
                     margin-bottom: 5px; font-weight: bold; }
                h3 { color: #F0A377; font-size: 12px; margin-top: 8px;
                     margin-bottom: 3px; font-weight: bold; }
                p, li, body { font-size: 11px; line-height: 1.5; color: #DFDFDF; }
                blockquote { border-left: 3px solid #E66C32; background-color: #3A2C21;
                             padding: 5px; margin: 5px 0; color: #F0A377; font-style: italic; }
                pre { background: #262626; padding: 10px; }
            </style>
            """

            def md_a_html(texto_md):
                lines = texto_md.split('\n')
                for i, line in enumerate(lines):
                    line_s = line.strip()
                    if line_s.startswith('# 🚀'):
                        lines[i] = f"<h1>{line_s[4:]}</h1>"
                    elif line_s.startswith('# '):
                        lines[i] = f"<h1>{line_s[2:]}</h1>"
                    elif line_s.startswith('### '):
                        # V2.1.4: el '###' salia literal en pantalla
                        lines[i] = f"<h3>{line_s[4:]}</h3>"
                    elif line_s.startswith('## '):
                        lines[i] = f"<h2>{line_s[3:]}</h2>"
                    elif line_s.startswith('*   ') or line_s.startswith('* '):
                        lines[i] = f"<li>{line_s[2:].strip()}</li>"
                    elif line_s.startswith('> '):
                        lines[i] = f"<blockquote>{line_s[2:]}</blockquote>"
                html = '<br>'.join(lines)
                html = html.replace("```markdown", "<pre>").replace("```", "</pre>")
                # V2.1.2: las negritas se cerraban mal. Se sustituia CADA '**'
                # por '<b>', asi que la primera negrita dejaba el resto de la
                # seccion en negrita (se veia en la guia: los pasos 2 y 3 en
                # negrita entera). Ahora se cierran por pares.
                for marca in ("**", "__"):
                    trozos = html.split(marca)
                    if len(trozos) > 1:
                        html = trozos[0]
                        for i, trozo in enumerate(trozos[1:]):
                            html += ("<b>" if i % 2 == 0 else "</b>") + trozo
                        if len(trozos) % 2 == 0:      # marca sin pareja
                            html += "</b>"
                # `codigo` -> monoespaciado, para la sintaxis de busqueda
                trozos = html.split("`")
                if len(trozos) > 1:
                    html = trozos[0]
                    for i, trozo in enumerate(trozos[1:]):
                        etq = ('<code style="background:#262626; color:#F0A377; '
                               'padding:1px 4px;">' if i % 2 == 0 else "</code>")
                        html += etq + trozo
                    if len(trozos) % 2 == 0:
                        html += "</code>"
                return style + html

            # Contenido: dividir el MD en secciones por '## ' para el índice lateral
            cuerpo = QHBoxLayout()
            cuerpo.setSpacing(10)
            toc = QListWidget()
            toc.setObjectName("TocList")
            toc.setFixedWidth(190)
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)

            secciones = []  # (titulo, contenido_md)
            path_md = resource_path(os.path.join("docs", "GUIA_RAPIDA.md"))
            if os.path.exists(path_md):
                with open(path_md, "r", encoding="utf-8") as f:
                    text = f.read()
                actual_titulo = "Introducción"
                actual_lineas = []
                for line in text.split('\n'):
                    if line.strip().startswith('## '):
                        if actual_lineas:
                            secciones.append((actual_titulo, '\n'.join(actual_lineas)))
                        actual_titulo = line.strip()[3:].strip()
                        actual_lineas = [line]
                    else:
                        actual_lineas.append(line)
                if actual_lineas:
                    secciones.append((actual_titulo, '\n'.join(actual_lineas)))

            if secciones:
                for titulo, _ in secciones:
                    toc.addItem(titulo)

                def mostrar_seccion(idx):
                    if 0 <= idx < len(secciones):
                        browser.setHtml(md_a_html(secciones[idx][1]))

                toc.currentRowChanged.connect(mostrar_seccion)
                toc.setCurrentRow(0)
            else:
                toc.setVisible(False)
                browser.setText("No se encontró el archivo de ayuda.")

            cuerpo.addWidget(toc)
            cuerpo.addWidget(browser, stretch=1)
            layout_v.addLayout(cuerpo, stretch=1)

            # Footer con atajos siempre visibles
            footer = QFrame()
            footer.setObjectName("DialogFooter")
            f_lay = QHBoxLayout(footer)
            f_lay.setContentsMargins(8, 6, 8, 6)
            lbl_atajos = QLabel("Enter Buscar   ·   Ctrl+C Copiar nombre   ·   Doble clic Abrir carpeta   ·   Arrastrar → SolidWorks")
            lbl_atajos.setStyleSheet("color: #999999; font-size: 11px; background: transparent;")
            f_lay.addWidget(lbl_atajos)
            f_lay.addStretch()
            btn_close = QPushButton("Cerrar")
            btn_close.setCursor(Qt.PointingHandCursor)
            btn_close.clicked.connect(dialog.accept)
            f_lay.addWidget(btn_close)
            layout_v.addWidget(footer)

            dialog.exec_()
        except Exception as e:
            logger.error(f"Error mostrando ayuda: {e}")

    def mostrar_info(self):
        """Muestra créditos y versión (V2.0.0 - rediseño 3c)"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Acerca de - Buscador ALSI")
            dialog.setFixedSize(440, 520)
            layout = QVBoxLayout(dialog)
            layout.setSpacing(10)
            layout.setContentsMargins(0, 0, 0, 16)

            # Cabecera con degradado de marca + isotipo
            header = QFrame()
            header.setStyleSheet(
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                "stop:0 #E66C32, stop:1 #BF5320); border: none;")
            header.setFixedHeight(120)
            h_lay = QVBoxLayout(header)
            h_lay.setContentsMargins(16, 14, 16, 14)
            h_lay.setSpacing(4)
            lbl_iso = QLabel()
            if os.path.exists(LOGO_ISOTIPO):
                lbl_iso.setPixmap(QPixmap(LOGO_ISOTIPO).scaled(
                    40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lbl_iso.setStyleSheet("background: transparent;")
            lbl_iso.setAlignment(Qt.AlignCenter)
            h_lay.addWidget(lbl_iso)
            lbl_title = QLabel("BUSCADOR DE PIEZAS")
            lbl_title.setStyleSheet(
                f'font-family: "{FUENTES["h1"]}"; font-size: 19px; font-weight: 800; '
                f'color: #FFFFFF; background: transparent;')
            lbl_title.setAlignment(Qt.AlignCenter)
            h_lay.addWidget(lbl_title)
            lbl_ver = QLabel(f"Versión {APP_VERSION} · Rediseño UI ALSI")
            # (APP_VERSION es la fuente única de la versión mostrada)
            lbl_ver.setStyleSheet("font-size: 12px; color: #FFE3D2; font-weight: 600; background: transparent;")
            lbl_ver.setAlignment(Qt.AlignCenter)
            h_lay.addWidget(lbl_ver)
            layout.addWidget(header)

            # Datos clave-valor
            datos = QFrame()
            d_lay = QVBoxLayout(datos)
            d_lay.setContentsMargins(20, 4, 20, 4)
            d_lay.setSpacing(6)
            for clave, valor in [
                ("Desarrollador", "Francisco Fernández Rodríguez"),
                ("Departamento", "Oficina Técnica · ALSI"),
                ("Base de datos", "PostgreSQL · NAS 192.168.1.10"),
            ]:
                fila = QHBoxLayout()
                lbl_k = QLabel(clave)
                lbl_k.setObjectName("MetaKey")
                lbl_v = QLabel(valor)
                lbl_v.setObjectName("MetaVal")
                lbl_v.setAlignment(Qt.AlignRight)
                fila.addWidget(lbl_k)
                fila.addStretch()
                fila.addWidget(lbl_v)
                d_lay.addLayout(fila)
            layout.addWidget(datos)

            # Notas de versión (dinámicas desde CHANGELOG.md)
            lbl_updates = QLabel("NOTAS DE VERSIÓN")
            lbl_updates.setObjectName("PanelTitle")
            lbl_updates.setContentsMargins(20, 4, 20, 0)
            layout.addWidget(lbl_updates)

            browser = QTextBrowser()
            browser.setHtml(self._obtener_changelog_html())
            browser.setMaximumHeight(160)
            cont_browser = QHBoxLayout()
            cont_browser.setContentsMargins(20, 0, 20, 0)
            cont_browser.addWidget(browser)
            layout.addLayout(cont_browser)

            layout.addStretch()

            btn_close = QPushButton("Cerrar")
            btn_close.setCursor(Qt.PointingHandCursor)
            btn_close.setFixedSize(110, 36)
            btn_close.clicked.connect(dialog.accept)
            layout.addWidget(btn_close, alignment=Qt.AlignCenter)

            dialog.exec_()
        except Exception as e:
            logger.error(f"Error mostrando info: {e}")

    def _obtener_changelog_html(self):
        """Lee el archivo CHANGELOG.md y lo convierte en HTML básico (V1.0.5 Dynamic)"""
        try:
            path_changelog = resource_path("CHANGELOG.md")
            if not os.path.exists(path_changelog):
                return "<i>No se encontraron notas de versión.</i>"
            
            with open(path_changelog, "r", encoding="utf-8") as f:
                content = f.read()
            
            lines = content.split('\n')
            html_lines = []
            for line in lines:
                l = line.strip()
                if l.startswith('## ['):
                    html_lines.append(f"<h3 style='color:#E66C32;'>{l.replace('#', '').strip()}</h3>")
                elif l.startswith('- '):
                    # Manejar negritas básicas
                    processed = l[2:].replace('**', '<b>').replace('**', '</b>')
                    html_lines.append(f"• {processed}<br>")
                elif l.startswith('    - '):
                    processed = l[6:].replace('**', '<b>').replace('**', '</b>')
                    html_lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;◦ {processed}<br>")
                elif not l:
                    html_lines.append("<br>")
            
            return "".join(html_lines)
        except Exception as e:
            logger.error(f"Error parseando changelog: {e}")
            return "<i>Error al cargar las notas de versión.</i>"

    # Eliminadas funciones duplicadas y closeEvent que sobreescribía el original.

    # Eliminadas funciones duplicadas y closeEvent que sobreescribía el original.

def aplicar_barra_titulo_oscura(hwnd):
    """Pone la barra de título nativa de Windows en modo oscuro (V2.0.3).
    Usa DWMWA_USE_IMMERSIVE_DARK_MODE (attr 20 en Win10 2004+/Win11, 19 en
    versiones anteriores). Silencioso si no está disponible."""
    try:
        import ctypes
        from ctypes import wintypes
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                              ctypes.c_void_p, wintypes.DWORD]
        valor = ctypes.c_int(1)
        for attr in (20, 19):
            hr = dwm.DwmSetWindowAttribute(wintypes.HWND(int(hwnd)), attr,
                                           ctypes.byref(valor), ctypes.sizeof(valor))
            if hr == 0:
                break
    except Exception:
        pass


class _TemaBarraTitulo(QObject):
    """Filtro de eventos: aplica la barra de título oscura a CADA ventana de la
    app (principal, diálogos, QMessageBox, menús desplegables) al mostrarse."""
    def eventFilter(self, obj, event):
        try:
            if event.type() in (QEvent.Show, QEvent.WinIdChange) \
                    and isinstance(obj, QWidget) and obj.isWindow():
                aplicar_barra_titulo_oscura(obj.winId())
        except Exception:
            pass
        return False


def _arrancar():
    """Arranque de la aplicacion (V2.1.0).

    Todo el arranque va dentro de un try: si algo falla aqui -- fuentes, hoja de
    estilo, base de datos, cualquier cosa -- el usuario VE un mensaje con la
    causa y la ruta del log, en vez de un icono que parpadea y nada mas. Esa era
    la peor parte de la incidencia: la app moria sin dejar rastro visible."""
    from PyQt5.QtCore import qInstallMessageHandler, QLockFile

    def _qt_msg_handler(mode, ctx, msg):
        logger.warning("Qt: %s", msg)
    qInstallMessageHandler(_qt_msg_handler)

    t_inicio = time.time()
    logger.info("===== Arranque v%s . PID %s =====", APP_VERSION, os.getpid())

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # --- Modo diagnostico: BuscadorPiezas.exe --diagnostico -----------------
    if "--diagnostico" in sys.argv:
        informe = generar_diagnostico()
        try:
            destino = os.path.join(LOG_DIR, "diagnostico.txt")
            with open(destino, "w", encoding="utf-8") as f:
                f.write(informe)
        except Exception:
            destino = "(no se ha podido guardar)"
        avisar_usuario("Diagnostico ALSI",
                       informe + "\n\nGuardado en:\n" + destino)
        return 0

    # --- Instancia unica ----------------------------------------------------
    # Sin esto, cuando la app tardaba en abrir el usuario volvia a pulsar y se
    # acumulaban procesos invisibles peleandose por el mismo pool de conexiones.
    # QLockFile detecta y limpia el candado huerfano de un proceso ya muerto.
    bloqueo = None
    try:
        if os.environ.get("ALSI_SIN_CANDADO"):
            raise RuntimeError("candado desactivado a proposito (pruebas)")
        bloqueo = QLockFile(os.path.join(LOG_DIR, "buscador.lock"))
        bloqueo.setStaleLockTime(30000)
        if not bloqueo.tryLock(200):
            hay_info, pid, host, nombre = bloqueo.getLockInfo()
            # Valvula de seguridad: si el proceso que puso el candado ya no
            # existe, se retira. Un candado huerfano dejando a alguien sin
            # poder abrir la app seria el mismo problema que vinimos a
            # arreglar, solo que causado por el arreglo.
            if hay_info and pid and not proceso_vivo(pid):
                logger.warning("Candado huerfano del PID %s: se retira", pid)
                bloqueo.removeStaleLockFile()
                bloqueo.tryLock(200)
        if bloqueo is not None and not bloqueo.isLocked():
            hay_info, pid, host, nombre = bloqueo.getLockInfo()
            logger.warning("Ya hay otra instancia (PID %s); no se abre otra", pid)
            avisar_usuario(
                "El Buscador ya esta abierto",
                "Ya tienes el Buscador de Piezas abierto en este equipo "
                "(proceso %s).\n\nBuscalo en la barra de tareas.\n\n"
                "Si no aparece por ningun lado, cierralo desde el Administrador "
                "de tareas (Ctrl+Mayus+Esc) y vuelve a abrirlo." % pid)
            return 0
    except Exception as e:
        logger.warning("No se ha podido crear el candado de instancia: %s", e)

    # V2.0.3: barra de titulo oscura en todas las ventanas
    _tema_barra = _TemaBarraTitulo()
    app.installEventFilter(_tema_barra)

    # V2.0.0 - Fuentes de marca + tema oscuro ALSI
    with Fase("cargar fuentes y estilo"):
        cargar_fuentes_marca()
        app.setFont(QFont(FUENTES['body'], 10))
        qss_marca = cargar_qss_marca()
        if qss_marca:
            app.setStyleSheet(qss_marca)
        else:
            # Fallback al tema claro V1.0.5 si falta alsi_buscador.qss
            app.setFont(QFont("Segoe UI", 9))
            app.setStyleSheet(MODERN_QSS)

    window = BuscadorPiezas()
    aplicar_barra_titulo_oscura(window.winId())  # V2.0.3: sin parpadeo blanco inicial
    window.show()
    logger.info("[arranque] ventana visible en %.1fs", time.time() - t_inicio)
    codigo = app.exec_()
    logger.info("===== Cierre normal (codigo %s) =====", codigo)
    if bloqueo is not None:
        try:
            bloqueo.unlock()
        except Exception:
            pass
    return codigo


if __name__ == "__main__":
    try:
        sys.exit(_arrancar())
    except SystemExit:
        raise
    except BaseException as e:
        logger.critical("Fallo fatal en el arranque", exc_info=True)
        mostrar_error(
            "El Buscador no ha podido arrancar",
            "El Buscador de Piezas no ha podido abrirse.\n\n"
            "Motivo: %s: %s\n\n"
            "El detalle completo esta en:\n%s\n\n"
            "Manda ese archivo y lo miramos." % (type(e).__name__, e, RUTA_LOG))
        sys.exit(1)