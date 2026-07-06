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

# v1.0.7 - Rutas NAS nuevo (modelo por origen, sustituye RUTAS_RED por compañero)
RUTAS_NAS = {
    'PROYECTOS':     r'\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS',
    'BIBLIOTECA_3D': r'\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D',
    'ALSI_ESTANDAR': r'\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR',
}

# Etiquetas legibles para la UI
ETIQUETAS_ORIGEN = {
    'PROYECTOS':     'Proyectos',
    'BIBLIOTECA_3D': 'Biblioteca 3D',
    'ALSI_ESTANDAR': 'ALSI Estándar',
}

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

/* Segmented control por dynamic property (un widget solo admite un objectName) */
QPushButton[segmento="true"] {
    background-color: #2E2E2E; border: 1px solid #4A4A4A; border-radius: 0;
    padding: 6px 14px; color: #999999; font-weight: 700; font-size: 12px;
}
QPushButton[segmento="true"]:checked { background-color: #E66C32; color: #FFFFFF; border-color: #E66C32; }
QPushButton[segmento="true"]:hover:!checked { border-color: #E66C32; color: #DFDFDF; }
QPushButton[segPos="first"] { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton[segPos="last"]  { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }

QPushButton#btn_toggle { padding: 2px 6px; font-size: 10px; border-radius: 5px; }
QPushButton#btn_cancelar { background-color: #8C3A32; border: none; color: #FFFFFF; }
QPushButton#btn_cancelar:hover { background-color: #A6443B; }

QFrame#panel_preview { background-color: #2E2E2E; border: 1px solid #3D3D3D; border-radius: 10px; }

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
    qss = qss.replace("url(icons/", f"url({icons_dir}/")
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
    """Modal para elegir qué orígenes y años indexar (v1.0.7 - NAS nuevo)"""
    def __init__(self, rutas_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar Indexación NAS")
        self.setMinimumSize(420, 480)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Título descriptivo
        lbl_titulo = QLabel("Selecciona los orígenes a indexar en el NAS:")
        lbl_titulo.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(lbl_titulo)
        
        # --- Orígenes ---
        group_comp = QGroupBox("Orígenes")
        group_comp.setFont(QFont("Segoe UI", 9))
        comp_layout = QVBoxLayout(group_comp)
        
        self.list_companeros = QListWidget()
        self.list_companeros.setMaximumHeight(160)
        for key in rutas_dict.keys():
            label = ETIQUETAS_ORIGEN.get(key, key)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            item.setToolTip(rutas_dict[key])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_companeros.addItem(item)
        comp_layout.addWidget(self.list_companeros)
        
        btn_comp_layout = QHBoxLayout()
        btn_todos = QPushButton("Todos")
        btn_todos.setCursor(Qt.PointingHandCursor)
        btn_todos.clicked.connect(lambda: self._toggle(self.list_companeros, True))
        btn_ninguno = QPushButton("Ninguno")
        btn_ninguno.setCursor(Qt.PointingHandCursor)
        btn_ninguno.clicked.connect(lambda: self._toggle(self.list_companeros, False))
        btn_comp_layout.addWidget(btn_todos)
        btn_comp_layout.addWidget(btn_ninguno)
        comp_layout.addLayout(btn_comp_layout)
        layout.addWidget(group_comp)
        
        # --- Años (Añadido V1.2.4 para consistencia) ---
        group_años = QGroupBox("Años")
        group_años.setFont(QFont("Segoe UI", 9))
        años_layout = QVBoxLayout(group_años)
        
        self.list_años = QListWidget()
        self.list_años.setMaximumHeight(150)
        años_actuales = [str(a) for a in range(datetime.now().year, 2010, -1)]
        for año in años_actuales:
            item = QListWidgetItem(año)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_años.addItem(item)
        años_layout.addWidget(self.list_años)
        
        btn_años_layout = QHBoxLayout()
        btn_t_años = QPushButton("Todos")
        btn_t_años.clicked.connect(lambda: self._toggle(self.list_años, True))
        btn_n_años = QPushButton("Ninguno")
        btn_n_años.clicked.connect(lambda: self._toggle(self.list_años, False))
        btn_años_layout.addWidget(btn_t_años)
        btn_años_layout.addWidget(btn_n_años)
        años_layout.addLayout(btn_años_layout)
        layout.addWidget(group_años)
        
        # --- Info ---
        lbl_info = QLabel("El proceso puede tardar varios minutos según el tamaño del NAS.\n"
                         "Puedes cancelar en cualquier momento.")
        lbl_info.setStyleSheet("color: #999999; font-style: italic; padding: 4px;")
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)
        
        # --- Botones ---
        button_box = QDialogButtonBox()
        self.btn_ok = QPushButton("Iniciar Indexación")
        self.btn_ok.setIcon(svg_icon("reindexar-refrescar", color="#FFFFFF"))
        self.btn_ok.setObjectName("Primary")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        
        button_box.addButton(self.btn_ok, QDialogButtonBox.AcceptRole)
        button_box.addButton(btn_cancel, QDialogButtonBox.RejectRole)
        layout.addWidget(button_box)
        
        # V2.0.0: el tema oscuro global (alsi_buscador.qss) ya estiliza el diálogo
    
    def _toggle(self, list_widget, state):
        for i in range(list_widget.count()):
            list_widget.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)

    def get_selected_items(self, list_widget):
        sel = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                sel.append(item.text())
        return sel

    def get_companeros_seleccionados(self):
        return self.get_selected_items(self.list_companeros)

    def get_años_seleccionados(self):
        return self.get_selected_items(self.list_años)
    


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
                    # Convertir a file:/// URL
                    url = QUrl.fromLocalFile(ruta)
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
        self.setUniformItemSizes(True)

    def mimeData(self, items):
        """file:/// URLs para arrastrar a SolidWorks (idéntico a TablaArrastrable)."""
        mime = QMimeData()
        urls = []
        for item in items:
            ruta = item.data(Qt.UserRole)
            if ruta:
                urls.append(QUrl.fromLocalFile(ruta))
        if urls:
            mime.setUrls(urls)
        return mime


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
        self.refrescar_filtros_jerarquicos()  # Carga inicial V1.0.0
        self.cargar_filtros_propiedades()
        self.cargar_preferencias()
        
        # Diagnóstico de red (V1.0.7)
        QTimer.singleShot(1000, self.verificar_rutas_red)

    # check_for_updates eliminado en V1.0.7 — El aviso de actualización lo gestiona
    # el administrador directamente con los compañeros.

    def verificar_rutas_red(self):
        """Comprueba si las rutas del NAS nuevo son accesibles (V1.0.7)"""
        error_msg = ""
        for origen, ruta in RUTAS_NAS.items():
            if not os.path.exists(ruta):
                error_msg += f"• {ETIQUETAS_ORIGEN.get(origen, origen)}: {ruta}\n"
        
        if error_msg:
            QMessageBox.warning(self, "Problema de Red", 
                                "Atención: No se puede acceder a las siguientes rutas del NAS:\n\n" + 
                                error_msg + 
                                "\nComprueba la conexión de red con 192.168.1.10.")
            logger.error(f"Rutas NAS no accesibles: {error_msg}")
        else:
            logger.info("Rutas NAS OK: todas accesibles")

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
        """Añade botones de Todos/Ninguno a un layout para un list_widget dado (Optimizado V1.0.0)"""
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.setContentsMargins(0, 5, 0, 5) 
        
        # Estilo para permitir encogimiento máximo (V1.0.0)

        btn_todos = QPushButton("Todos")
        btn_todos.setObjectName("btn_toggle")  # Para que el global CSS no pise el padding
        btn_todos.setCursor(Qt.PointingHandCursor)
        btn_todos.setFixedHeight(28)
        btn_todos.setMinimumWidth(30)
        btn_todos.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_todos.clicked.connect(lambda: self.toggle_checkboxes(list_widget, True))
        
        btn_ninguno = QPushButton("Ninguno")
        btn_ninguno.setObjectName("btn_toggle")  # Para que el global CSS no pise el padding
        btn_ninguno.setCursor(Qt.PointingHandCursor)
        btn_ninguno.setFixedHeight(28)
        btn_ninguno.setMinimumWidth(30)
        btn_ninguno.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_ninguno.clicked.connect(lambda: self.toggle_checkboxes(list_widget, False))
        
        btn_layout.addWidget(btn_todos)
        btn_layout.addWidget(btn_ninguno)
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
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(10)

        # ═══════════════════════════════════════════
        # CABECERA (ISOTIPO + TÍTULO H1 + BARRA DE BÚSQUEDA) - V2.0.0
        # ═══════════════════════════════════════════
        self.header_frame = QFrame()
        self.header_frame.setObjectName("Header")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(14)

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
        self.input_buscar.setMinimumHeight(40)
        self.input_buscar.returnPressed.connect(self.ejecutar_busqueda)
        header_layout.addWidget(self.input_buscar, stretch=1)

        # 4. TIPOS DE ARCHIVO (V1.0.0 - Reubicado a Barra Superior)
        self.btn_tipos = QPushButton("Tipos: TODOS")
        self.btn_tipos.setIcon(svg_icon("capas-tipos"))
        self.btn_tipos.setMinimumHeight(40)
        self.btn_tipos.setCursor(Qt.PointingHandCursor)
        self.btn_tipos.setFixedWidth(150)
        self.btn_tipos.setStyleSheet("""
            QPushButton::menu-indicator { image: none; } 
            QPushButton { padding: 5px; font-weight: bold; }
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

        self.btn_buscar = QPushButton("Buscar")
        self.btn_buscar.setIcon(svg_icon("buscar", color="#FFFFFF"))
        self.btn_buscar.setObjectName("Primary")
        self.btn_buscar.setToolTip("Haz clic para iniciar la búsqueda (o pulsa Enter)")
        self.btn_buscar.setCursor(Qt.PointingHandCursor)
        self.btn_buscar.setMinimumHeight(45)
        self.btn_buscar.setFixedWidth(120)
        self.btn_buscar.clicked.connect(self.ejecutar_busqueda)
        # Main Menu
        header_layout.addWidget(self.btn_buscar)

        main_layout.addWidget(self.header_frame)

        # Banner de Actualización eliminado en V1.0.7

        # ═══════════════════════════════════════════
        # CONTENIDO PRINCIPAL (SPLITTER: SIDEBAR + CONTENT) V1.0.0
        # ═══════════════════════════════════════════
        
        # Splitter Principal (Horizontal) para redimensionar barra lateral
        # (estilos del handle en QSS_EXTRAS)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(4) # Línea sutil

        # --- Panel filtros izquierdo (Scrollable Sidebar) ---
        panel_izquierdo = QFrame()
        panel_izquierdo.setObjectName("Panel")
        panel_izquierdo.setMinimumWidth(80)
        panel_izquierdo.setMaximumWidth(500)
        izq_outer_layout = QVBoxLayout(panel_izquierdo)
        izq_outer_layout.setContentsMargins(10, 10, 10, 10)
        izq_outer_layout.setSpacing(6)

        lbl_panel_filtros = QLabel("FILTROS AVANZADOS")
        aplicar_h2(lbl_panel_filtros)
        izq_outer_layout.addWidget(lbl_panel_filtros)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_widget = QWidget()
        izq_layout = QVBoxLayout(scroll_widget)
        izq_layout.setContentsMargins(4, 4, 4, 4)
        izq_layout.setSpacing(4)
        
        # 1. ORIGEN (v1.0.7 - antes era Compañeros)
        lbl_comp = QLabel("ORIGEN")
        lbl_comp.setObjectName("PanelTitle")
        izq_layout.addWidget(lbl_comp)

        self.list_companeros = QListWidget()
        self.list_companeros.setMinimumHeight(60)
        self.list_companeros.setMaximumHeight(120)
        for key, label in ETIQUETAS_ORIGEN.items():
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)  # Internamente usamos la key
            item.setToolTip(RUTAS_NAS.get(key, ''))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_companeros.addItem(item)
        izq_layout.addWidget(self.list_companeros)
        self.add_toggle_buttons(izq_layout, self.list_companeros)

        # 2. AÑOS
        lbl_años = QLabel("AÑOS DE PROYECTO")
        lbl_años.setObjectName("PanelTitle")
        izq_layout.addWidget(lbl_años)
        self.list_años = QListWidget()
        self.list_años.setMinimumHeight(80)
        self.list_años.setMaximumHeight(200)
        año_actual = datetime.now().year
        for año in range(año_actual + 1, 2012, -1):
            item = QListWidgetItem(str(año))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Marcar por defecto hasta 2022 (o todo)
            item.setCheckState(Qt.Checked if año >= 2022 else Qt.Unchecked)
            self.list_años.addItem(item)
        izq_layout.addWidget(self.list_años)
        self.add_toggle_buttons(izq_layout, self.list_años)

        # 3. CARPETAS (MECANICA, LAYOUT...) - V1.2.3
        lbl_folder = QLabel("CARPETAS")
        lbl_folder.setObjectName("PanelTitle")
        izq_layout.addWidget(lbl_folder)
        self.list_carpetas = QListWidget()
        self.list_carpetas.setMinimumHeight(80)
        self.list_carpetas.setMaximumHeight(180)
        for folder in FILTRO_CARPETAS:
            if folder == 'TODOS': continue
            item = QListWidgetItem(folder)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_carpetas.addItem(item)
        izq_layout.addWidget(self.list_carpetas)
        self.add_toggle_buttons(izq_layout, self.list_carpetas)
        self.list_carpetas.itemChanged.connect(self.on_filtro_jerarquico_changed)

        # 5. CLIENTES (V1.3.0)
        lbl_clientes = QLabel("CLIENTES")
        lbl_clientes.setObjectName("PanelTitle")
        izq_layout.addWidget(lbl_clientes)
        self.list_clientes = QListWidget()
        self.list_clientes.setMinimumHeight(80)
        self.list_clientes.setMaximumHeight(200)
        izq_layout.addWidget(self.list_clientes)
        self.add_toggle_buttons(izq_layout, self.list_clientes)

        # 6. PROYECTOS (V1.3.0)
        lbl_proys = QLabel("PROYECTOS")
        lbl_proys.setObjectName("PanelTitle")
        izq_layout.addWidget(lbl_proys)
        self.list_proyectos = QListWidget()
        self.list_proyectos.setMinimumHeight(80)
        self.list_proyectos.setMaximumHeight(200)
        izq_layout.addWidget(self.list_proyectos)
        self.add_toggle_buttons(izq_layout, self.list_proyectos)
        
        # Conectar señales para Cascada (V1.0.0 - Completo)
        self.list_companeros.itemChanged.connect(self.on_filtro_jerarquico_changed)
        self.list_años.itemChanged.connect(self.on_filtro_jerarquico_changed)
        self.list_clientes.itemChanged.connect(self.on_filtro_jerarquico_changed)
        self.list_proyectos.itemChanged.connect(self.on_filtro_jerarquico_changed)
        
        izq_layout.addStretch()
        scroll.setWidget(scroll_widget)
        izq_outer_layout.addWidget(scroll)
        
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
        self.grupo_densidad, botones_dens = _crear_segmento([("Cómoda", None), ("Compacta", None)])
        self.btn_dens_comoda, self.btn_dens_compacta = botones_dens
        self.btn_dens_comoda.setChecked(True)
        self.grupo_densidad.buttonClicked[int].connect(self._on_densidad_segment)
        seg_dens_layout = QHBoxLayout()
        seg_dens_layout.setSpacing(0)
        for b in botones_dens:
            seg_dens_layout.addWidget(b)
        toolbar_layout.addLayout(seg_dens_layout)

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
        preview_layout.setContentsMargins(15, 5, 15, 20)
        preview_layout.setSpacing(8)
        
        # El botón de ocultar panel fue movido al footer
        
        self.lbl_preview_icon = QLabel()
        self.lbl_preview_icon.setPixmap(svg_pixmap("buscar", color="#777777", size=64))
        self.lbl_preview_icon.setAlignment(Qt.AlignCenter)
        self.lbl_preview_icon.setMinimumHeight(100)
        
        # Efecto de opacidad para animaciones (V1.3.16)
        self.preview_opacity = QGraphicsOpacityEffect()
        self.lbl_preview_icon.setGraphicsEffect(self.preview_opacity)
        self.anim_opacity = QPropertyAnimation(self.preview_opacity, b"opacity")
        self.anim_opacity.setDuration(400)
        
        preview_layout.addWidget(self.lbl_preview_icon)
        
        self.lbl_preview_nombre = QLabel("Seleccione un archivo")
        self.lbl_preview_nombre.setObjectName("FileName")
        self.lbl_preview_nombre.setAlignment(Qt.AlignCenter)
        self.lbl_preview_nombre.setWordWrap(True)
        preview_layout.addWidget(self.lbl_preview_nombre)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #3D3D3D;")
        preview_layout.addWidget(line)
        
        self.lbl_preview_tipo = QLabel("")
        self.lbl_preview_tipo.setFont(QFont("Segoe UI", 9))
        self.lbl_preview_comp = QLabel("")
        self.lbl_preview_comp.setFont(QFont("Segoe UI", 9))
        self.lbl_preview_proyecto = QLabel("")
        self.lbl_preview_proyecto.setFont(QFont("Segoe UI", 9))
        self.lbl_preview_proyecto.setWordWrap(True)
        self.lbl_preview_tamaño = QLabel("")
        self.lbl_preview_tamaño.setFont(QFont("Segoe UI", 9))
        self.lbl_preview_ruta = QLabel("")
        self.lbl_preview_ruta.setWordWrap(True)
        self.lbl_preview_ruta.setStyleSheet("font-size: 10px; color: #999999;")
        self.lbl_preview_ruta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        preview_layout.addWidget(self.lbl_preview_tipo)
        preview_layout.addWidget(self.lbl_preview_comp)
        preview_layout.addWidget(self.lbl_preview_proyecto)
        preview_layout.addWidget(self.lbl_preview_tamaño)
        preview_layout.addWidget(self.lbl_preview_ruta)
        
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
        
        # --- Panel filtros derecho (Propiedades) ---
        panel_derecho = QFrame()
        panel_derecho.setObjectName("Panel")
        panel_derecho.setMinimumWidth(80)
        panel_derecho.setMaximumWidth(300)
        der_outer_layout = QVBoxLayout(panel_derecho)
        der_outer_layout.setContentsMargins(10, 10, 10, 10)
        der_outer_layout.setSpacing(6)

        lbl_panel_props = QLabel("PROPIEDADES SW")
        aplicar_h2(lbl_panel_props)
        der_outer_layout.addWidget(lbl_panel_props)
        
        scroll_der = QScrollArea()
        scroll_der.setWidgetResizable(True)
        scroll_der.setFrameShape(QFrame.NoFrame)
        scroll_widget_der = QWidget()
        der_layout = QVBoxLayout(scroll_widget_der)
        der_layout.setContentsMargins(4, 4, 4, 4)
        der_layout.setSpacing(4)
        
        # --- Fabricación (Checkboxes booleanos) — ARRIBA ---
        lbl_fabricacion = QLabel("FABRICACIÓN")
        lbl_fabricacion.setObjectName("PanelTitle")
        der_layout.addWidget(lbl_fabricacion)
        
        self.chk_laser = QCheckBox("Láser")
        self.chk_torno = QCheckBox("Torno")
        self.chk_fresa = QCheckBox("Fresa")
        self.chk_soldadura = QCheckBox("Soldadura")
        self.chk_pintura = QCheckBox("Pintura")
        self.chk_montaje = QCheckBox("Montaje")
        
        for chk in [self.chk_laser, self.chk_torno, self.chk_fresa, self.chk_soldadura, self.chk_pintura, self.chk_montaje]:
            der_layout.addWidget(chk)
            chk.stateChanged.connect(self.ejecutar_busqueda)
        
        # --- Material (QListWidget multi-selección) ---
        lbl_material = QLabel("MATERIAL")
        lbl_material.setObjectName("PanelTitle")
        der_layout.addWidget(lbl_material)
        self.list_materiales = QListWidget()
        self.list_materiales.setMinimumHeight(60)
        self.list_materiales.setMaximumHeight(150)
        der_layout.addWidget(self.list_materiales)
        self.add_toggle_buttons(der_layout, self.list_materiales)
        self.list_materiales.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))
        
        # --- Tratamiento (QListWidget multi-selección, valores oficiales de plantilla SW) ---
        lbl_tratamiento = QLabel("TRATAMIENTO")
        lbl_tratamiento.setObjectName("PanelTitle")
        der_layout.addWidget(lbl_tratamiento)
        self.list_tratamientos = QListWidget()
        self.list_tratamientos.setMinimumHeight(60)
        self.list_tratamientos.setMaximumHeight(150)
        # Valores oficiales de template_PZ.prtprp
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
        der_layout.addWidget(self.list_tratamientos)
        self.add_toggle_buttons(der_layout, self.list_tratamientos)
        self.list_tratamientos.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))
        
        # --- Cierre (QListWidget multi-selección) ---
        lbl_cierre = QLabel("CIERRE")
        lbl_cierre.setObjectName("PanelTitle")
        der_layout.addWidget(lbl_cierre)
        self.list_cierres = QListWidget()
        self.list_cierres.setMinimumHeight(60)
        self.list_cierres.setMaximumHeight(120)
        for cierre in ["SIN FIN", "CON GRAPA", "CON GRAPA OCULTA", "ABIERTA", "CON GRAPA EN UN LADO"]:
            item = QListWidgetItem(cierre)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_cierres.addItem(item)
        der_layout.addWidget(self.list_cierres)
        self.add_toggle_buttons(der_layout, self.list_cierres)
        self.list_cierres.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))
        
        # --- Tipo de Banda (Checkboxes booleanos) ---
        lbl_banda = QLabel("TIPO DE BANDA")
        lbl_banda.setObjectName("PanelTitle")
        der_layout.addWidget(lbl_banda)
        
        self.chk_filo_guiado = QCheckBox("Filo Guiado")
        self.chk_onda = QCheckBox("Onda")
        self.chk_cangilon = QCheckBox("Cangilón")
        self.chk_runer = QCheckBox("Runer")
        
        for chk in [self.chk_filo_guiado, self.chk_onda, self.chk_cangilon, self.chk_runer]:
            der_layout.addWidget(chk)
            chk.stateChanged.connect(self.ejecutar_busqueda)
        
        # --- Espesor (QListWidget multi-selección, solo para piezas, 1-20mm) ---
        lbl_espesor = QLabel("ESPESOR")
        lbl_espesor.setObjectName("PanelTitle")
        der_layout.addWidget(lbl_espesor)
        self.list_espesores = QListWidget()
        self.list_espesores.setMinimumHeight(60)
        self.list_espesores.setMaximumHeight(150)
        for mm in range(1, 21):
            item = QListWidgetItem(f"{mm}mm")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_espesores.addItem(item)
        der_layout.addWidget(self.list_espesores)
        self.add_toggle_buttons(der_layout, self.list_espesores)
        self.list_espesores.itemChanged.connect(lambda: self.ejecutar_busqueda(auto=True))
            
        der_layout.addStretch()
        scroll_der.setWidget(scroll_widget_der)
        der_outer_layout.addWidget(scroll_der)

        # Añadir splitter derecho al splitter principal
        self.main_splitter.addWidget(self.splitter)
        self.main_splitter.addWidget(panel_derecho)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        
        # Restaurar ancho guardado (Persistencia)
        saved_width = self.controller.load_preference('sidebar_width')
        if saved_width:
             self.main_splitter.setSizes([int(saved_width), 1200, 200])
        else:
             self.main_splitter.setSizes([240, 1200, 200]) # Default original

        main_layout.addWidget(self.main_splitter, stretch=1)

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
        except Exception as e:
            logger.debug(f"Error restaurando config UI: {e}")

    # ═══════════════════════════════════════════
    # VISTA GALERÍA (V2.0.0)
    # ═══════════════════════════════════════════
    def _cambiar_vista(self, index):
        """Conmuta Lista (0) / Galería (1)."""
        self.stack_vistas.setCurrentIndex(index)
        self.seg_tam_container.setVisible(index == 1)
        if index == 1:
            self._sincronizar_galeria()
        self.qsettings.setValue("vista_modo", index)

    TAM_GALERIA = [(96, (150, 175)), (128, (180, 210)), (160, (220, 250))]  # S, M, L

    def _aplicar_tam_galeria(self, index):
        icono, grid = self.TAM_GALERIA[max(0, min(index, 2))]
        self.galeria.setIconSize(QSize(icono, icono))
        self.galeria.setGridSize(QSize(*grid))

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
        self.save_window_state()
        super().closeEvent(event)

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
                espesores_sel
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
                    item = QTableWidgetItem(str(val) if val else "")
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
                
            self.lbl_count.setText(f"{len(resultados)} resultados")
            if not resultados and termino:
                txt = f"No se encontraron resultados para '{termino}'"
                self.lbl_status.setText(txt)
                
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
        self.lbl_status.setText("Indexación completada")
        self.lbl_count.setText(f"{total} archivos en total")
        
        QMessageBox.information(self, "Éxito", f"Se han indexado {total} archivos en {tiempo:.1f} segundos.")
        self.lbl_status.setText(f"Última indexación: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        self.refrescar_filtros_jerarquicos()

    # ═══════════════════════════════════════════
    # PREVISUALIZACIÓN (Cambio 4)
    # ═══════════════════════════════════════════


    def extraer_miniatura_raw(self, ruta, size=256):
        """Devuelve (QImage, hbitmap) permitiendo su uso seguro en QThreads (V1.0.3)"""
        try:
            if not ruta or not os.path.exists(ruta):
                return None, 0
            
            # 1. PRIORIZAR IShellItemImageFactory (Calidad Explorador de Windows)
            try:
                hbitmap = self._thumbnail_via_shell_factory(ruta, size)
                if hbitmap and hbitmap != 0:
                    return None, hbitmap
            except Exception as e:
                logger.debug(f"IShellItemImageFactory falló: {e}")

            ext = Path(ruta).suffix.lower()
            
            # 2. FALLBACK A EXTRACTORES ESPECÍFICOS
            # SolidWorks OLE (PreviewPNG)
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

            # PDF (Matrix 4x para nitidez HD)
            if ext == '.pdf':
                try:
                    import fitz
                    doc = fitz.open(ruta)
                    if doc.page_count > 0:
                        page = doc[0]
                        mat = fitz.Matrix(4, 4) # Mayor resolución (V1.0.6)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                        if not image.isNull():
                            return image.copy(), 0
                    doc.close()
                except Exception as e:
                    logger.debug(f"PyMuPDF falló para PDF: {e}")

        except Exception as e:
            logger.debug(f"Error en extraer_miniatura_raw: {e}")
        
        return None, 0

    def extraer_miniatura(self, ruta, size=256):
        """Extrae miniatura (QPixmap) para el hilo principal (Compatible hacia atrás)"""
        if not ruta or not os.path.exists(ruta):
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
                res = shell.SHGetFileInfo(ruta, 0, shellcon.SHGFI_ICON | shellcon.SHGFI_LARGEICON)
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
                SIIGBF_BIGGERSIZEOK = 0x01
                hbitmap = c_void_p()
                
                hr = get_image(ppv, sz, SIIGBF_BIGGERSIZEOK, byref(hbitmap))
                
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

            # 1. ACTUALIZACIÓN INSTANTÁNEA (Solo Texto)
            self.lbl_preview_nombre.setText(nombre)
            ext = Path(nombre).suffix.lower()
            tipo_desc = DESCRIPCIONES_EXTENSION.get(ext, 'Archivo')
            self.lbl_preview_tipo.setText(f"Tipo: {tipo_desc} ({tipo})")
            self.lbl_preview_comp.setText(f"Origen: {comp} | AÑO {año}")

            proy_str = f"{cod_proy} {nom_proy}" if cod_proy else (nom_proy if nom_proy else proyecto)
            ord_str = f"Orden: {orden_completa}" if orden_completa else ""
            self.lbl_preview_proyecto.setText(f"Cliente: {cliente}\nProyecto: {proy_str}\n{ord_str}")
            self.lbl_preview_ruta.setText(ruta)
            self.lbl_preview_tamaño.setText("Tamaño: Cargando...")
            
            # Mostrar miniatura cacheada inmediatamente o placeholder (V1.0.4 Fix)
            if ruta in self.cache_miniaturas:
                cached = self.cache_miniaturas[ruta]
                self.lbl_preview_icon.setPixmap(cached.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.lbl_preview_icon.setText("")
                self.preview_opacity.setOpacity(1.0)
            else:
                # V2.0.0: badge de extensión en vez de emoji
                self.lbl_preview_icon.setText("")
                self.lbl_preview_icon.setPixmap(pixmap_badge_extension(ext, size=96))
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
                            self.lbl_preview_icon.setPixmap(pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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

            # Verificar existencia (IO Pesado en red)
            if not os.path.exists(ruta):
                 self.lbl_preview_tamaño.setText("Tamaño: No accesible")
                 return

            # Tamaño
            size = os.path.getsize(ruta)
            if size < 1024:
                self.lbl_preview_tamaño.setText(f"Tamaño: {size} B")
            elif size < 1024 * 1024:
                self.lbl_preview_tamaño.setText(f"Tamaño: {size / 1024:.1f} KB")
            else:
                self.lbl_preview_tamaño.setText(f"Tamaño: {size / (1024 * 1024):.1f} MB")

            # Miniatura (Heavy IO)
            pixmap = self.extraer_miniatura(ruta)
            if pixmap and not pixmap.isNull():
                self.lbl_preview_icon.setPixmap(pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
            ruta = self.tabla.item(row, 0).text()  # Columna 0 = Ruta Completa
            if ruta and os.path.exists(ruta):
                subprocess.Popen(f'explorer /select,"{ruta}"')
            else:
                QMessageBox.critical(self, "Error", "No se puede acceder a la ruta. Puede que el servidor no esté disponible.")

    def copiar_ruta_seleccionada(self):
        row = self.tabla.currentRow()
        if row >= 0:
            ruta = self.tabla.item(row, 0).text()  # Columna 0 = Ruta Completa
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
        # Keyboard First Navigation
        if event.key() == Qt.Key_F and event.modifiers() == Qt.ControlModifier:
            self.search_box.setFocus()
            self.search_box.selectAll()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            if self.search_box.hasFocus():
                self.search_box.clear()
            else:
                self.panel_preview.setVisible(False)
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

            # Columna 0 = Ruta Completa
            item_ruta = self.tabla.item(self.tabla.currentRow(), 0)
            ruta = item_ruta.text() if item_ruta else ""
            if ruta and os.path.exists(ruta):
                menu.addSeparator()
                menu.addAction(svg_icon("arrastrar-solidworks"), "Abrir/Insertar en SolidWorks").triggered.connect(
                    lambda: os.startfile(ruta)
                )

            # Export selection option
            if len(self.tabla.selectedItems()) > self.tabla.columnCount(): # Si hay más de 1 fila seleccionada
                menu.addSeparator()
                action_export_sel = QAction(svg_icon("exportar-descargar"), "Exportar Selección a Excel", self)
                action_export_sel.triggered.connect(self.exportar_excel_seleccion)
                menu.addAction(action_export_sel)

            menu.exec_(widget_menu.mapToGlobal(pos))

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
            dialog.resize(800, 600)
            layout = QVBoxLayout(dialog)
            
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            
            # Cargar contenido MD
            path_md = resource_path(os.path.join("docs", "GUIA_RAPIDA.md"))
            if os.path.exists(path_md):
                with open(path_md, "r", encoding="utf-8") as f:
                    text = f.read()
                    # Convertir MD básico a HTML simple para QTextBrowser (Line-by-line R3)
                    lines = text.split('\n')
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
                    html = html.replace("```markdown", "<pre style='background:#262626; padding:10px;'>").replace("```", "</pre>")
                    html = html.replace("**", "<b>").replace("__", "<b>")
                    
                    # Estilo base Profesional (V1.0.0 Polish R3 - Optimized Fonts)
                    style = """
                    <style>
                        h1 { 
                            color: #E15B1E; 
                            font-family: 'Segoe UI', sans-serif; 
                            font-size: 16px; 
                            margin-bottom: 5px; 
                            border-bottom: 2px solid #E15B1E;
                            padding-bottom: 2px;
                        }
                        h2 {
                            color: #F5F5F5;
                            font-family: 'Segoe UI', sans-serif;
                            font-size: 13px;
                            margin-top: 10px;
                            margin-bottom: 5px;
                            font-weight: bold;
                        }
                        p, li, body {
                            font-family: 'Segoe UI', sans-serif;
                            font-size: 11px;
                            line-height: 1.4;
                            color: #DFDFDF;
                        }
                        blockquote {
                            border-left: 3px solid #E66C32;
                            background-color: #3A2C21;
                            padding: 5px;
                            margin: 5px 0;
                            color: #F0A377;
                            font-style: italic;
                        }
                    </style>
                    """
                    browser.setHtml(style + html)
            else:
                browser.setText("No se encontró el archivo de ayuda.")
                
            layout.addWidget(browser)
            
            btn_close = QPushButton("Cerrar")
            btn_close.clicked.connect(dialog.accept)
            layout.addWidget(btn_close, alignment=Qt.AlignCenter)
            
            dialog.exec_()
        except Exception as e:
            logger.error(f"Error mostrando ayuda: {e}")

    def mostrar_info(self):
        """Muestra créditos y versión (Fixed HTML & Empty Notes R3)"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Acerca de - Buscador ALSI")
            dialog.setFixedSize(450, 480) # Un poco más alto para las notas
            layout = QVBoxLayout(dialog)
            layout.setSpacing(10)
            layout.setContentsMargins(20, 20, 20, 20)
            
            # Cabecera
            lbl_title = QLabel("Buscador de Piezas ALSI")
            lbl_title.setStyleSheet("font-size: 22px; font-weight: bold; color: #E15B1E;")
            lbl_title.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl_title)
            
            lbl_ver = QLabel("Versión 1.0.7 (Migración NAS Nuevo)")
            lbl_ver.setStyleSheet("font-size: 14px; color: #7f8c8d; font-weight: 500;")
            lbl_ver.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl_ver)
            
            # Separador
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            layout.addWidget(line)
            
            # Créditos con RichText forzado (R3 Fix)
            lbl_author = QLabel()
            lbl_author.setAlignment(Qt.AlignCenter)
            lbl_author.setStyleSheet("font-size: 13px; color: #DFDFDF;")
            lbl_author.setText("<html>Desarrollado por:<br><b>Francisco Fernández Rodríguez</b></html>")
            layout.addWidget(lbl_author)
            
            lbl_desc = QLabel()
            lbl_desc.setAlignment(Qt.AlignCenter)
            lbl_desc.setStyleSheet("color: #999999; font-size: 12px;")
            lbl_desc.setText("<html>Departamento de Oficina Técnica<br><b>ALSI</b></html>")
            layout.addWidget(lbl_desc)

            # Sección de Novedades (Vacía por ahora)
            lbl_updates = QLabel("Notas de Versión:")
            lbl_updates.setStyleSheet("font-weight: bold; margin-top: 10px; color: #DFDFDF;")
            layout.addWidget(lbl_updates)
            
            browser = QTextBrowser()
            browser.setHtml(self._obtener_changelog_html())
            # V2.0.0: QTextBrowser oscuro heredado del QSS global
            browser.setMaximumHeight(120)
            layout.addWidget(browser)
            
            layout.addStretch()

            btn_close = QPushButton("Cerrar")
            btn_close.setCursor(Qt.PointingHandCursor)
            btn_close.setFixedSize(110, 38)
            btn_close.setStyleSheet("""
                QPushButton {
                    background-color: #7f8c8d;
                    color: white;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover { background-color: #6c7a7d; }
            """)
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
                    html_lines.append(f"<h3 style='color:#E15B1E;'>{l.replace('#', '').strip()}</h3>")
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
