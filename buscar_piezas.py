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
                             QStyledItemDelegate, QStyleOptionViewItem, QStyle, QButtonGroup, QStackedWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QPoint, QMimeData, QUrl, QTimer, QPropertyAnimation, QEvent, QSettings, QRect
from PyQt5.QtGui import QIcon, QFont, QColor, QPixmap, QDrag, QImage, QPainter, QPen, QPalette
from PyQt5.QtWidgets import QFileIconProvider
import pythoncom
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "app.log"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BuscadorALSI")

def exception_hook(exctype, value, traceback):
    """Captura cualquier excepción no gestionada para que la app no se cierre"""
    logger.error("Excepción no capturada", exc_info=(exctype, value, traceback))
    # V2.0.0: las carreras benignas de cierre (señal llega a un widget ya
    # destruido) se registran en el log pero no molestan al usuario con un popup
    if exctype is RuntimeError and "has been deleted" in str(value):
        return
    msg = f"Se ha producido un error inesperado:\n\n{value}\n\nLa aplicación intentará seguir funcionando."
    QMessageBox.critical(None, "Error Inesperado", msg)

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
from models import IndexManager
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


def detectar_nas_host():
    """Detecta por cuál host es accesible el NAS en este equipo (V2.0.1).
    Prueba IP primero y, si no llega, el nombre NASCENTRAL."""
    global NAS_HOST_ACTIVO
    for host in NAS_HOSTS:
        try:
            if os.path.exists(r"\\%s\Oficina Tecnica" % host):
                NAS_HOST_ACTIVO = host
                logger.info(f"NAS accesible por: {host}")
                return host
        except Exception:
            continue
    NAS_HOST_ACTIVO = NAS_HOSTS[0]
    logger.warning(f"Ningún host del NAS respondió; se usará {NAS_HOST_ACTIVO}")
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
APP_VERSION = "2.0.2"

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
        # escalar a caber en el rect, pero nunca ampliar por encima del original
        destino = self._pm.size().scaled(r.size(), Qt.KeepAspectRatio)
        destino.setWidth(min(destino.width(), self._pm.width()))
        destino.setHeight(min(destino.height(), self._pm.height()))
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
    
    def __init__(self, vistas_pendientes, method_extractor):
        super().__init__()
        self.vistas_pendientes = vistas_pendientes # list of (row, ruta)
        self.method_extractor = method_extractor
        self._cancelar = False
        
    def cancelar(self):
        self._cancelar = True
        
    def run(self):
        # Inicializa COM en este hilo para IShellItemImageFactory
        pythoncom.CoInitialize()
        try:
            for row, ruta in self.vistas_pendientes:
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
class BuscadorPiezas(QMainWindow):
    def __init__(self):
        super().__init__()
        try:
            pythoncom.CoInitialize() # Inicialización COM Hilo Principal (V1.0.3)
        except:
            pass
        # V2.0.1: detectar por qué host llega al NAS (IP o NASCENTRAL) antes de
        # tocar ningún archivo, para reescribir las rutas al que funcione aquí
        detectar_nas_host()
        self.db = IndexManager()
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
        Mantiene el arranque fluido aunque la BD esté lenta."""
        try:
            self.lbl_status.setText("Cargando filtros…")
            QApplication.processEvents()
            self.refrescar_filtros_jerarquicos()
            self.cargar_filtros_propiedades()
            self.cargar_preferencias()
            self._actualizar_chips_contexto()
            self.lbl_status.setText("Listo")
        except Exception as e:
            logger.error(f"Error en carga inicial diferida: {e}")
            self.lbl_status.setText("Listo")

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
        """Activa o desactiva todos los checkboxes en un QListWidget"""
        for i in range(list_widget.count()):
            list_widget.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)
    
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
        self.input_buscar.setPlaceholderText("Buscar: travesaño, cama, inox (separar por comas)")
        self.input_buscar.setToolTip("Introduce palabras separadas por comas para una búsqueda inteligente")
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
        # Main Menu
        header_layout.addWidget(self.btn_buscar)

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
        self.list_companeros = QListWidget()
        self.list_companeros.setMinimumHeight(100)
        self.list_companeros.setMaximumHeight(140)
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
        self.list_carpetas = QListWidget()
        self.list_carpetas.setMinimumHeight(140)
        self.list_carpetas.setMaximumHeight(220)
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
        self.list_clientes = QListWidget()
        self.list_clientes.setMinimumHeight(160)
        self.list_clientes.setMaximumHeight(300)
        sec_clientes.lay.addWidget(self.list_clientes)
        self.add_toggle_buttons(sec_clientes.lay, self.list_clientes)

        # 6. PROYECTOS
        sec_proyectos = _acordeon('proyectos', 'PROYECTOS', 'proyectos-maletin')
        self.list_proyectos = QListWidget()
        self.list_proyectos.setMinimumHeight(160)
        self.list_proyectos.setMaximumHeight(300)
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
        self.tabla.setColumnCount(21)
        self.tabla.setHorizontalHeaderLabels([
            "Ruta_Hidden", "Orden_Orig", "Cód. Proy_Hidden", "Nom. Proy_Hidden", "Vista",
            "Nombre", "Origen", "Año", "Cliente", "Proyecto",
            "Orden", "Material", "Tratamiento", "Espesor", "L",
            "T", "F", "S", "P", "M", "Tipo"
        ])
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

        # Segmento S/M/L: tamaño de tarjeta en galería (solo activo en vista Galería)
        self.grupo_tam_galeria, botones_tam = _crear_segmento([("S", None), ("M", None), ("L", None)])
        self.btn_tam_s, self.btn_tam_m, self.btn_tam_l = botones_tam
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
        for col_idx in range(5, 21):
            h_item = self.tabla.horizontalHeaderItem(col_idx)
            nombre_col = h_item.toolTip() or h_item.text()
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

        # Contenedor central: toolbar + stack de vistas (Lista / Galería)
        self.stack_vistas = QStackedWidget()
        self.stack_vistas.addWidget(self.tabla)

        # Vista Galería (V2.0.0)
        self.galeria = GaleriaArrastrable()
        pal_gal = self.galeria.palette()
        for grupo_pal in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            pal_gal.setColor(grupo_pal, QPalette.Highlight, QColor("#3A2C21"))
            pal_gal.setColor(grupo_pal, QPalette.HighlightedText, QColor("#F5F5F5"))
        self.galeria.setPalette(pal_gal)
        self.galeria.setIconSize(QSize(128, 128))
        self.galeria.setGridSize(QSize(180, 210))
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
        self.preview_image_card.setFixedHeight(210)
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
        preview_layout.addWidget(self.preview_image_card)

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
        for fila, (clave, etiqueta) in enumerate([
            ('origen', 'Origen'), ('anio', 'Año'), ('cliente', 'Cliente'),
            ('proyecto', 'Proyecto'), ('orden', 'Orden'), ('tamano', 'Tamaño')]):
            lbl_k = QLabel(etiqueta)
            lbl_k.setObjectName("MetaKey")
            lbl_v = QLabel("—")
            lbl_v.setObjectName("MetaVal")
            lbl_v.setWordWrap(True)
            self.meta_grid.addWidget(lbl_k, fila, 0, Qt.AlignTop)
            self.meta_grid.addWidget(lbl_v, fila, 1, Qt.AlignTop)
            self._meta_vals[clave] = lbl_v
        self.meta_widget = QWidget()
        self.meta_widget.setLayout(self.meta_grid)
        self.meta_widget.setVisible(False)
        preview_layout.addWidget(self.meta_widget)

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

        preview_layout.addStretch()
        
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
        self.list_materiales = QListWidget()
        self.list_materiales.setMinimumHeight(120)
        self.list_materiales.setMaximumHeight(240)
        sec_material.lay.addWidget(self.list_materiales)
        self.add_toggle_buttons(sec_material.lay, self.list_materiales)
        self.list_materiales.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))

        # --- Tratamiento (valores oficiales de template_PZ.prtprp) ---
        sec_tratamiento = _acordeon('tratamiento', 'TRATAMIENTO', 'propiedades-sliders', expandido=False)
        self.list_tratamientos = QListWidget()
        self.list_tratamientos.setMinimumHeight(120)
        self.list_tratamientos.setMaximumHeight(260)
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
        self.list_cierres = QListWidget()
        self.list_cierres.setMinimumHeight(100)
        self.list_cierres.setMaximumHeight(180)
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
        self.list_espesores = QListWidget()
        self.list_espesores.setMinimumHeight(120)
        self.list_espesores.setMaximumHeight(240)
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
            tam = int(self.qsettings.value("galeria_tam", 1))
            [self.btn_tam_s, self.btn_tam_m, self.btn_tam_l][max(0, min(tam, 2))].setChecked(True)
            self._aplicar_tam_galeria(tam)
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
        if index == 1:
            self._sincronizar_galeria()
        self.qsettings.setValue("vista_modo", index)

    TAM_GALERIA = [(96, (150, 175)), (128, (180, 210)), (160, (220, 250))]  # S, M, L

    def _aplicar_tam_galeria(self, index):
        icono, grid = self.TAM_GALERIA[max(0, min(index, 2))]
        self.galeria.setIconSize(QSize(icono, icono))
        self.galeria.setGridSize(QSize(*grid))
        # Forzar recomposición inmediata para que las etiquetas se pinten ya
        # (sin esperar a otra interacción)
        self.galeria.doItemsLayout()
        self.galeria.viewport().update()

    def _cambiar_tam_galeria(self, index):
        self._aplicar_tam_galeria(index)
        self.qsettings.setValue("galeria_tam", index)

    def _sincronizar_galeria(self):
        """Reconstruye las tarjetas de la galería a partir de la tabla (fuente de verdad).
        La miniatura usa la caché si existe; si no, el badge de extensión."""
        try:
            self.galeria.blockSignals(True)
            self.galeria.clear()
            self._galeria_items = {}
            for r in range(self.tabla.rowCount()):
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
                if ruta in self.cache_miniaturas:
                    card.setIcon(QIcon(self.cache_miniaturas[ruta]))
                else:
                    ext = Path(nombre).suffix.lower()
                    if ext not in self._badge_cache:
                        self._badge_cache[ext] = QIcon(pixmap_badge_extension(ext, size=48))
                    card.setIcon(self._badge_cache[ext])
                self.galeria.addItem(card)
                self._galeria_items[ruta] = card
            self.galeria.blockSignals(False)
        except Exception as e:
            self.galeria.blockSignals(False)
            logger.debug(f"Error sincronizando galería: {e}")

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
                self.btn_colapsar_sidebar.setIcon(svg_icon("expandir-panel", size=14))
                self.btn_colapsar_sidebar.setToolTip("Expandir panel de filtros")
            else:
                self.rail_widget.setVisible(False)
                self._scroll_filtros.setVisible(True)
                self._lbl_panel_filtros.setVisible(True)
                self._panel_izquierdo.setMinimumWidth(80)
                self._panel_izquierdo.setMaximumWidth(500)
                sizes = self.main_splitter.sizes()
                if sizes and sizes[0] < 200:
                    sizes[0] = 256
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
        btn.clicked.connect(on_reset)
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

            # Actualizador .bat: da un margen para que la app se cierre sola,
            # FUERZA el cierre de cualquier instancia que quede (evita el bucle
            # infinito si hay otra ventana abierta o un proceso colgado), copia
            # los recursos y reabre.
            bat = os.path.join(os.environ.get("TEMP", local_dir), "alsi_update.bat")
            recursos = ["BuscadorPiezas.exe", "SwPropExtractor.exe",
                        "SolidWorks.Interop.swdocumentmgr.dll", "config.ini",
                        "ALSI_BUSCADOR.ico", "reindexar_diario.py", "reindexar_tarea.bat"]
            lineas = [
                "@echo off",
                "setlocal",
                'set "NET=' + RUTA_DESPLIEGUE_APP + '"',
                'set "LOC=' + local_dir + '"',
                'title Actualizando Buscador de Piezas ALSI...',
                "rem Margen para que la app se cierre por si misma",
                "timeout /t 2 /nobreak >nul",
                "rem Forzar cierre de cualquier instancia restante (extras o colgadas)",
                'taskkill /F /IM BuscadorPiezas.exe >nul 2>&1',
                'taskkill /F /IM SwPropExtractor.exe >nul 2>&1',
                "timeout /t 1 /nobreak >nul",
                'pushd "%NET%"',
            ]
            for r in recursos:
                lineas.append(f'copy /Y "%NET%\\{r}" "%LOC%\\" >nul 2>&1')
            lineas += [
                'popd',
                'start "" "%LOC%\\BuscadorPiezas.exe"',
                'del "%~f0"',
            ]
            with open(bat, "w", encoding="cp850", errors="ignore") as f:
                f.write("\r\n".join(lineas))

            # Lanzar el .bat despegado y cerrar la app
            DETACHED = 0x00000008
            subprocess.Popen(["cmd", "/c", bat], creationflags=DETACHED, close_fds=True)
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
    def cargar_preferencias(self):
        self.input_buscar.setText(self.controller.load_preference("ultimo_termino", ""))
        
        # Restaurar Checkbox Biblioteca (V1.0.0) - ELIMINADO PARA NAS NUEVO

        
        comp_guardados = self.controller.load_preference("companeros_checked", "")
        if comp_guardados:
            comp_list = comp_guardados.split(',')
            for i in range(self.list_companeros.count()):
                item = self.list_companeros.item(i)
                item.setCheckState(Qt.Checked if item.text() in comp_list else Qt.Unchecked)

        # Restaurar Años (V1.2.3)
        años_guardados = self.controller.load_preference("años_checked", "")
        if años_guardados:
            años_list = años_guardados.split(',')
            for i in range(self.list_años.count()):
                item = self.list_años.item(i)
                item.setCheckState(Qt.Checked if item.text() in años_list else Qt.Unchecked)

        # Restaurar Carpetas (V1.2.3)
        carpetas_guardadas = self.controller.load_preference("carpetas_checked", "")
        if carpetas_guardadas:
            c_list = carpetas_guardadas.split(',')
            for i in range(self.list_carpetas.count()):
                item = self.list_carpetas.item(i)
                item.setCheckState(Qt.Checked if item.text() in c_list else Qt.Unchecked)

        # Restaurar Tipos (V1.0.0 - Desde Botón Superior)
        tipos_guardados = self.controller.load_preference("tipos_checked", "")
        if tipos_guardados:
            t_list = tipos_guardados.split(',')
            for tipo, action in self.tipos_actions.items():
                action.setChecked(tipo in t_list)
            self.actualizar_texto_tipos()
        
        geom = self.controller.load_preference("geometria")
        if geom:
            parts = geom.split(',')
            if len(parts) == 4:
                self.setGeometry(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))

        # Restaurar tamaño splitter
        splitter_state = self.controller.load_preference("splitter_sizes", "")
        if splitter_state:
            try:
                sizes = [int(s) for s in splitter_state.split(',')]
                if len(sizes) == 2:
                    self.splitter.setSizes(sizes)
            except ValueError:
                pass

    def save_window_state(self):
        rect = self.geometry()
        val = f"{rect.x()},{rect.y()},{rect.width()},{rect.height()}"
        self.controller.save_preference("geometria", val)
        self.controller.save_preference("ultimo_termino", self.input_buscar.text())
        
        # Guardar Checkbox Biblioteca (V1.0.0) - ELIMINADO PARA NAS NUEVO

        

        comp_checked = ','.join(self.get_selected_items(self.list_companeros))
        self.controller.save_preference("companeros_checked", comp_checked)

        años_checked = ','.join(self.get_selected_items(self.list_años))
        self.controller.save_preference("años_checked", años_checked)

        carpetas_checked = ','.join(self.get_selected_items(self.list_carpetas))
        self.controller.save_preference("carpetas_checked", carpetas_checked)

        tipos_checked = ','.join(self.get_selected_tipos())
        self.controller.save_preference("tipos_checked", tipos_checked)

        # Guardar tamaño splitter
        sizes = self.splitter.sizes()
        self.controller.save_preference("splitter_sizes", f"{sizes[0]},{sizes[1]}")

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
        """Ejecución real de la cascada tras el debouncing"""
        self.refrescar_filtros_jerarquicos()
        # V1.0.1: Disparar búsqueda automática (silenciosa)
        self.ejecutar_busqueda(auto=True)

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

    def refrescar_filtros_jerarquicos(self, solo_proyectos=False, solo_ordenes=False):
        """Puebla las listas de Clientes, Proyectos y Órdenes con lógica de cascada total (V1.0.0)"""
        if self.bloqueo_filtros:
            return
            
        self.bloqueo_filtros = True
        
        # Bloquear señales de las listas para evitar eventos espurios
        self.list_clientes.blockSignals(True)
        self.list_proyectos.blockSignals(True)
        
        try:
            # Selecciones globales
            comp_sel = self.get_selected_items(self.list_companeros)
            años_sel = self.get_selected_items(self.list_años)
            
            # Obtener selecciones actuales para intentar mantenerlas
            clientes_sel = self.get_selected_items(self.list_clientes)
            proyectos_sel = [item.split(' - ')[0] for item in self.get_selected_items(self.list_proyectos)]

            # 1. CLIENTES (Solo si no es una actualización parcial)
            if not solo_proyectos and not solo_ordenes:
                clientes = self.controller.get_all_clients(companions=comp_sel, years=años_sel)
                self.list_clientes.clear()
                for cli in clientes:
                    item = QListWidgetItem(cli)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if cli in clientes_sel else Qt.Unchecked)
                    self.list_clientes.addItem(item)
                # Actualizamos selecciones locales tras el clear
                clientes_sel = self.get_selected_items(self.list_clientes)
            
            # 2. PROYECTOS
            if not solo_ordenes:
                proyectos = self.controller.get_all_projects(
                    clientes=clientes_sel if clientes_sel else None,
                    companions=comp_sel if comp_sel else None,
                    years=años_sel if años_sel else None
                )
                self.list_proyectos.clear()
                for cod, nom in proyectos:
                    item = QListWidgetItem(f"{cod} - {nom}")
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if str(cod) in proyectos_sel else Qt.Unchecked)
                    self.list_proyectos.addItem(item)
                
                # V1.0.1: Eliminado duplicado y añadido proyectos_sel final
                proyectos_sel = [item.text().split(' - ')[0] for item in self.get_selected_items(self.list_proyectos)]
                
        except Exception as e:
            logger.error(f"Error refrescando filtros jerárquicos: {e}")
        finally:
            self.list_clientes.blockSignals(False)
            self.list_proyectos.blockSignals(False)
            self.bloqueo_filtros = False

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
                    QMessageBox.warning(self, "Atención", "Selecciona al menos un origen.")
                return
            
            if not termino:
                if not auto:
                    QMessageBox.warning(self, "Atención", "Introduce un término de búsqueda.")
                return
                
            logger.info(f"Ejecutando búsqueda auto={auto} | Term: {termino} | Comp: {len(comp_sel)} | Años: {len(años_sel)}")
            self.lbl_status.setText("Buscando...")
            QApplication.processEvents()
            
            # Desactivar ordenación visual durante la carga para evitar inconsistencias
            self.tabla.setSortingEnabled(False)
            
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

            t0_busqueda = time.time()  # V2.0.0: cronómetro de búsqueda
            resultados = self.controller.perform_search(
                termino,
                comp_sel,
                años_sel,
                extensiones,
                carpetas_sel,
                clientes_sel,
                proyectos_sel,
                None, # ordenes
                props_fabricacion,
                props_bandas,
                materiales_sel,
                tratamientos_sel,
                espesores_sel,
                solo_placa_ce=self.btn_placa_ce.isChecked()  # V2.1.0
            )
            
            # Prealocar filas de golpe (mucho más rápido que insertRow en bucle)
            self.tabla.setRowCount(len(resultados))
            vistas_pendientes = []
            
            for row, data in enumerate(resultados):
                # V1.0.5 Final Clean Mapping:
                # [nombre, comp, año, cliente, proy, tipo, codProy, nomProy, codOrd, nomOrd, ruta]
                
                # Columna oculta 0: Ruta
                ruta = data[10]
                vistas_pendientes.append((row, ruta))
                self.tabla.setItem(row, 0, QTableWidgetItem(ruta))
                
                # Columna oculta 1: Orden Original
                self.tabla.setItem(row, 1, QTableWidgetItem(str(row).zfill(6)))
                
                # Columna oculta 2: Cod Proy
                self.tabla.setItem(row, 2, QTableWidgetItem(str(data[6]) if data[6] else ""))
                
                # Columna oculta 3: Nom Proy
                self.tabla.setItem(row, 3, QTableWidgetItem(str(data[7]) if data[7] else ""))
                
                # Columna 4: Vista (Miniatura, con badge de extensión como placeholder V2.0.0)
                thumb_item = QTableWidgetItem()
                thumb_item.setData(Qt.UserRole, ruta)
                thumb_item.setTextAlignment(Qt.AlignCenter)
                ext_badge = Path(str(data[0])).suffix.lower()
                if ext_badge not in self._badge_cache:
                    self._badge_cache[ext_badge] = QIcon(pixmap_badge_extension(ext_badge, size=48))
                thumb_item.setIcon(self._badge_cache[ext_badge])
                self.tabla.setItem(row, 4, thumb_item)
                
                # Resto de columnas visibles:
                map_cols = {
                    0: 5,  # nombre_archivo -> col 5
                    1: 6,  # compañero -> col 6 (Origen)
                    2: 7,  # año -> col 7
                    3: 8,  # cliente -> col 8
                    4: 9,  # proyecto -> col 9
                    5: 20, # tipo_carpeta -> col 20 (FINAL STRETCH)
                    11: 11, # sw_material -> col 11
                    12: 12, # sw_tratamiento -> col 12
                    13: 13, # sw_espesor -> col 13
                    14: 14, # sw_laser -> col 14
                    15: 15, # sw_torno -> col 15
                    16: 16, # sw_fresa -> col 16
                    17: 17, # sw_soldadura -> col 17
                    18: 18, # sw_pintura -> col 18
                    19: 19, # sw_montaje -> col 19
                }
                for i_data, i_tabla in map_cols.items():
                    val = data[i_data]
                    texto = str(val) if val else ""
                    # V2.0.0: etiquetas unificadas (PROYECTOS / BIBLIOTECA 3D /
                    # ALSI ESTANDAR) en las columnas Origen (6) y Proyecto (9)
                    if i_tabla in (6, 9) and texto:
                        texto = etiqueta_origen(texto)
                    item = QTableWidgetItem(texto)
                    self.tabla.setItem(row, i_tabla, item)
                    
                # Combinar Orden y Nombre Orden en la columna 10
                cod_ord = str(data[8]) if data[8] else ""
                nom_ord = str(data[9]) if data[9] else ""
                orden_completa = f"{cod_ord} {nom_ord}".strip()
                self.tabla.setItem(row, 10, QTableWidgetItem(orden_completa))
            
            # Lanzamos hilo de miniaturas
            if hasattr(self, 'thumb_worker') and self.thumb_worker and self.thumb_worker.isRunning():
                self.thumb_worker.cancelar()
                try:
                    self.thumb_worker.thumbnail_ready.disconnect(self.on_thumbnail_ready)
                except (TypeError, RuntimeError):
                    pass
                self.thumb_worker.wait(500)
            elif hasattr(self, 'thumb_worker') and self.thumb_worker:
                try:
                    self.thumb_worker.thumbnail_ready.disconnect(self.on_thumbnail_ready)
                except (TypeError, RuntimeError):
                    pass
                
            self.thumb_worker = ThumbnailWorker(vistas_pendientes, self.extraer_miniatura_raw)
            self.thumb_worker.thumbnail_ready.connect(self.on_thumbnail_ready)
            self.thumb_worker.start()
            
            # Re-activar ordenación después de cargar datos
            self.tabla.setSortingEnabled(True)

            # V2.0.0: refrescar galería si es la vista activa
            if self.stack_vistas.currentIndex() == 1:
                self._sincronizar_galeria()
            
            if len(resultados) >= 5000:
                self.lbl_status.setText("⚠ Mostrando 5000 de 5000+ resultados. Refina tu búsqueda.")
            else:
                self.lbl_status.setText("Listo")
                
            # V2.0.0: contador con separador de miles + tiempo de búsqueda (toque pro)
            n_fmt = f"{len(resultados):,}".replace(",", ".")
            dt_txt = f"{time.time() - t0_busqueda:.2f}".replace(".", ",")
            self.lbl_count.setText(f"{n_fmt} resultados · {dt_txt} s")
            if not resultados and termino:
                txt = f"No se encontraron resultados para '{termino}'"
                self.lbl_status.setText(txt)

            # V2.0.1: refrescar barra de contexto y recientes
            self._actualizar_chips_contexto()
            if not auto and termino and resultados:
                self._push_reciente(termino)
                
        except Exception as e:
            self.lbl_status.setText("❌ Error en la búsqueda")
            self.tabla.setRowCount(0)
            QMessageBox.critical(self, "Error de Búsqueda", 
                               f"Se ha producido un error al realizar la búsqueda:\n\n{str(e)}\n\n"
                               "Si el error persiste, intenta actualizar el índice.")

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
                QMessageBox.warning(self, "Atención", "No has seleccionado ningún origen.")

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
        self.thread.error.connect(lambda e: QMessageBox.critical(self, "Error", f"Error en indexación: {e}"))
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

    def extraer_miniatura_raw(self, ruta, size=256):
        """Devuelve (QImage, hbitmap) permitiendo su uso seguro en QThreads (V1.0.3)"""
        try:
            ruta_canonica = ruta  # clave de la caché de BD (tal cual se indexó)
            ruta = ruta_accesible(ruta)  # V2.0.1: host accesible (IP/NASCENTRAL)
            if not ruta or not os.path.exists(ruta):
                return None, 0

            ext = Path(ruta).suffix.lower()

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

        if ruta in self.cache_miniaturas:
            return self.cache_miniaturas[ruta]

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
            self.cache_miniaturas[ruta] = pixmap
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
            if ruta in self.cache_miniaturas:
                self._set_preview_imagen(self.cache_miniaturas[ruta])
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
                self.cache_miniaturas[ruta] = pixmap

                # Poner miniatura en la celda correcta (busca por ruta, no por row)
                self.set_cell_thumbnail(ruta, pixmap)

                # V2.0.0: actualizar también la tarjeta de la galería si existe
                try:
                    card = self._galeria_items.get(ruta)
                    if card:
                        card.setIcon(QIcon(pixmap))
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

    def _actualizar_preview_recursos_pesados(self):
        """Ejecutado por el timer_preview tras 100ms de inactividad (V1.0.5)"""
        try:
            data = self.current_preview_data
            ruta = data.get('ruta')
            if not ruta: return
            ruta = ruta_accesible(ruta)  # V2.0.1: host accesible (IP/NASCENTRAL)

            # Verificar existencia (IO Pesado en red)
            if not os.path.exists(ruta):
                 self.lbl_preview_tamaño.setText("No accesible")
                 return

            # Tamaño (V2.0.1: solo el valor, la etiqueta "Tamaño" ya está en el grid)
            size = os.path.getsize(ruta)
            if size < 1024:
                self.lbl_preview_tamaño.setText(f"{size} B")
            elif size < 1024 * 1024:
                self.lbl_preview_tamaño.setText(f"{size / 1024:.1f} KB")
            else:
                self.lbl_preview_tamaño.setText(f"{size / (1024 * 1024):.1f} MB")

            # Miniatura (Heavy IO)
            pixmap = self.extraer_miniatura(ruta)
            if pixmap and not pixmap.isNull():
                self._set_preview_imagen(pixmap)
                self.lbl_preview_icon.setText("")
                self.anim_opacity.stop()
                self.preview_opacity.setOpacity(0.0)
                self.anim_opacity.setStartValue(0.0)
                self.anim_opacity.setEndValue(1.0)
                self.anim_opacity.start()
            else:
                self.preview_opacity.setOpacity(1.0)

        except Exception as e:
            logger.debug(f"Error en recursos diferidos: {e}")

    # ═══════════════════════════════════════════
    # ACCIONES
    # ═══════════════════════════════════════════
    def abrir_carpeta_seleccionada(self):
        row = self.tabla.currentRow()
        if row >= 0:
            ruta = ruta_accesible(self.tabla.item(row, 0).text())  # V2.0.1
            if ruta and os.path.exists(ruta):
                subprocess.Popen(f'explorer /select,"{ruta}"')
            else:
                QMessageBox.critical(self, "Error", "No se puede acceder a la ruta. Puede que el servidor no esté disponible.")

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
            QMessageBox.critical(self, "Error al Exportar", f"No se pudo guardar el archivo:\n{e}")

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
        elif event.key() == Qt.Key_Escape:
            if self.input_buscar.hasFocus():
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
                menu.addAction(svg_icon("arrastrar-solidworks"), "Abrir/Insertar en SolidWorks").triggered.connect(
                    lambda r=ruta: os.startfile(r)
                )

            # Export selection option
            if len(self.tabla.selectedItems()) > self.tabla.columnCount(): # Si hay más de 1 fila seleccionada
                menu.addSeparator()
                action_export_sel = QAction(svg_icon("exportar-descargar"), "Exportar Selección a Excel", self)
                action_export_sel.triggered.connect(self.exportar_excel_seleccion)
                menu.addAction(action_export_sel)

            menu.exec_(widget_menu.mapToGlobal(pos))

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

            lista = QListWidget()
            lista.setAlternatingRowColors(False)
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
                lista.addItem(it)
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
                    rr = ruta_accesible(it.data(Qt.UserRole))
                    if rr and os.path.exists(rr):
                        subprocess.Popen(f'explorer /select,"{rr}"')
            lista.itemDoubleClicked.connect(lambda _: abrir_sel())

            footer = QHBoxLayout()
            footer.addStretch()
            btn_abrir = QPushButton("Abrir carpeta")
            btn_abrir.setIcon(svg_icon("carpeta", size=15))
            btn_abrir.setCursor(Qt.PointingHandCursor)
            btn_abrir.clicked.connect(abrir_sel)
            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.clicked.connect(dlg.accept)
            footer.addWidget(btn_abrir)
            footer.addWidget(btn_cerrar)
            lay.addLayout(footer)

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
            QMessageBox.critical(self, "Error al Exportar", f"No se pudo guardar el archivo:\n{e}")

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

            tabla = QTableWidget()
            tabla.setColumnCount(5)
            tabla.setHorizontalHeaderLabels(["Componente", "Cliente", "Proyecto", "Año", "Origen"])
            tabla.setRowCount(len(filas))
            tabla.setEditTriggers(QTableWidget.NoEditTriggers)
            tabla.setSelectionBehavior(QTableWidget.SelectRows)
            tabla.verticalHeader().setVisible(False)
            tabla.setSortingEnabled(True)
            for i, (comp, nom_a, origen, anio, cliente, proyecto, ruta_c) in enumerate(filas):
                it0 = QTableWidgetItem(comp)
                it0.setData(Qt.UserRole, ruta_c or "")
                celdas = [
                    it0,
                    QTableWidgetItem(cliente or ("—" if nom_a else "no indexado")),
                    QTableWidgetItem(etiqueta_origen(proyecto or "") if proyecto else "—"),
                    QTableWidgetItem(str(anio) if anio else "—"),
                    QTableWidgetItem(etiqueta_origen(origen or "") if origen else "—"),
                ]
                for j, it in enumerate(celdas):
                    if not nom_a:  # componente no encontrado en el índice
                        it.setForeground(QColor("#888888"))
                    tabla.setItem(i, j, it)
            tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            for j in (1, 2, 3, 4):
                tabla.horizontalHeader().setSectionResizeMode(j, QHeaderView.ResizeToContents)
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
                ["Componente", "Cliente", "Proyecto", "Año", "Origen", "Ruta"],
                [(f[0], f[4] or "", etiqueta_origen(f[5] or "") if f[5] else "",
                  f[3] or "", etiqueta_origen(f[2] or "") if f[2] else "", f[6] or "")
                 for f in filas],
                f"Despiece_{os.path.splitext(nombre)[0]}.csv"))
            footer.addWidget(btn_export)
            footer.addStretch()
            btn_abrir = QPushButton("Abrir carpeta")
            btn_abrir.setIcon(svg_icon("carpeta", size=15))
            btn_abrir.setCursor(Qt.PointingHandCursor)
            btn_abrir.clicked.connect(abrir_sel)
            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.clicked.connect(dlg.accept)
            footer.addWidget(btn_abrir)
            footer.addWidget(btn_cerrar)
            lay.addLayout(footer)

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

            tabla = QTableWidget()
            tabla.setColumnCount(2)
            tabla.setHorizontalHeaderLabels(["Componente", "Estado"])
            tabla.setEditTriggers(QTableWidget.NoEditTriggers)
            tabla.setSelectionBehavior(QTableWidget.SelectRows)
            tabla.verticalHeader().setVisible(False)
            datos = ([(c, "Solo en A", COL_A, comp_a[c][6]) for c in solo_a] +
                     [(c, "Solo en B", COL_B, comp_b[c][6]) for c in solo_b] +
                     [(c, "En ambos", COL_COMUN, comp_a[c][6]) for c in comunes])
            tabla.setRowCount(len(datos))
            for i, (comp, estado, color, ruta_c) in enumerate(datos):
                it0 = QTableWidgetItem(comp)
                it0.setData(Qt.UserRole, ruta_c or "")
                it1 = QTableWidgetItem(estado)
                it1.setForeground(QColor(color))
                tabla.setItem(i, 0, it0)
                tabla.setItem(i, 1, it1)
            tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
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
            btn_abrir = QPushButton("Abrir carpeta")
            btn_abrir.setIcon(svg_icon("carpeta", size=15))
            btn_abrir.setCursor(Qt.PointingHandCursor)
            btn_abrir.clicked.connect(abrir_sel)
            btn_cerrar = QPushButton("Cerrar")
            btn_cerrar.setCursor(Qt.PointingHandCursor)
            btn_cerrar.clicked.connect(dlg.accept)
            footer.addWidget(btn_abrir)
            footer.addWidget(btn_cerrar)
            lay.addLayout(footer)

            dlg.exec_()
        except Exception as e:
            logger.error(f"Error comparando {ruta_a} vs {ruta_b}: {e}")

    def copiar_nombre_seleccionado(self):
        """Acción proactiva: copiar solo el nombre del archivo"""
        row = self.tabla.currentRow()
        if row >= 0:
            nombre = self.tabla.item(row, 5).text() # Columna 5 = Nombre
            QApplication.clipboard().setText(nombre)
            self.lbl_status.setText(f"✅ Nombre copiado: {nombre}")
            self.toast.show_message(f"✅ Nombre copiado:\n{nombre}")

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
                    elif line_s.startswith('## '):
                        lines[i] = f"<h2>{line_s[3:]}</h2>"
                    elif line_s.startswith('*   ') or line_s.startswith('* '):
                        lines[i] = f"<li>{line_s[2:].strip()}</li>"
                    elif line_s.startswith('> '):
                        lines[i] = f"<blockquote>{line_s[2:]}</blockquote>"
                html = '<br>'.join(lines)
                html = html.replace("```markdown", "<pre>").replace("```", "</pre>")
                html = html.replace("**", "<b>").replace("__", "<b>")
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

if __name__ == "__main__":
    # V2.0.0: registrar avisos de Qt (p.ej. detalles de parseo QSS) en el log
    from PyQt5.QtCore import qInstallMessageHandler
    def _qt_msg_handler(mode, ctx, msg):
        logger.warning(f"Qt: {msg}")
    qInstallMessageHandler(_qt_msg_handler)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # V2.0.0 - Fuentes de marca + tema oscuro ALSI
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
    window.show()
    sys.exit(app.exec_())
