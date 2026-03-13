import sys
import os
import re
import time
import subprocess
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QStatusBar, QProgressBar, QLabel, QMessageBox, 
                             QMenu, QAction, QAbstractItemView, QListWidget, QListWidgetItem,
                             QDialog, QDialogButtonBox, QSplitter, QGroupBox, QFrame, QScrollArea,
                             QCheckBox, QSizePolicy, QGraphicsOpacityEffect, QTextBrowser, QGridLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QPoint, QMimeData, QUrl, QTimer, QPropertyAnimation
from PyQt5.QtGui import QIcon, QFont, QColor, QPixmap, QDrag, QImage
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
from controllers import SearchController, IndexadorThread, SWPropertyExtractorThread, extraer_propiedades_ondemand

# Configuración Global
CONFIG_DIR = Path(os.path.expanduser("~")) / ".alsi_busqueda"
DB_PATH = CONFIG_DIR / "index.db"

# Colores Corporativos ALSI
RAL_2010_NARANJA = "#E15B1E"  # Naranja corporativo
RAL_7000_GRIS = "#78858B"     # Gris corporativo
WHITE = "#FFFFFF"

# Logos y Recursos (V1.0.0)
LOGO_ISOTIPO = resource_path("ALSI_ISOTIPO_naranja.png")
LOGO_IMAGOTIPO = resource_path("ALSI_IMAGOTIPO_naranja.png")
APP_ICON = resource_path("ALSI_BUSCADOR.ico")

RUTAS_RED = {
    'EMRAH': r'\\OFITEC-7\alsi proyectos aprobados (emrah)',
    'DANI': r'\\OFITEC-5\alsi - proyectos aprobados (dani)',
    'EMILIA': r'\\OFITEC-3\alsi proyectos aprobados (emilia)',
    'MACIEK': r'\\PABLO-OT\alsi - proyectos aprobados (maciek)',
    'MARCOS': r'\\OFITEC-2\alsi proyectos aprobados (marcos)',
    'JESUS': r'\\OFITEC-1\alsi proyectos aprobados (jesus)',
    'PACO': r'\\OFITEC-4\alsi proyectos aprobados (paco)',
    'ALVARO': r'\\Ofitec-3\alsi proyectos aprobados (álvaro)',
    'MICHO': r'\\Ofitec-3\alsi proyectos aprobados (antonio)',
    'JAVI GARCÍA': r'\\OFITEC-4\ALSI PROYECTOS APROBADOS',
    'JAVI ALONSO': r'\\OFITEC-5\alsi-proyectos aprobados javier',
    'DAVID BARÓN': r'Z:\ALSI INTERCAMBIO\ALSI LEGENDS\DAVID B',
}

# Rutas especiales para V1.0.0
RUTA_BIBLIOTECA = r'Z:\ALSI INTERCAMBIO\BIBLIOTECA SIDDEX'
RUTA_ESTANDAR = r'Z:\ALSI INTERCAMBIO\ALSI ESTANDAR'
RUTA_DARKWEB_JA = r'\\Ofitec-5\javier alonso'

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

# MOTOR DE BASE DE DATOS E INDEXACIÓN MOVIDOS A models.py Y controllers.py

# -----------------------------------------------------------------------------
# DIÁLOGO DE INDEXACIÓN SELECTIVA (Cambio 2)
# -----------------------------------------------------------------------------
class DialogIndexacion(QDialog):
    """Modal para elegir qué compañeros y años indexar"""
    def __init__(self, rutas_red, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔄 Configurar Indexación")
        self.setMinimumSize(420, 520)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Título descriptivo
        lbl_titulo = QLabel("Selecciona los compañeros a re-indexar:")
        lbl_titulo.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(lbl_titulo)
        
        # --- Compañeros ---
        group_comp = QGroupBox("👥 Compañeros")
        group_comp.setFont(QFont("Segoe UI", 9))
        comp_layout = QVBoxLayout(group_comp)
        
        self.list_companeros = QListWidget()
        self.list_companeros.setMaximumHeight(220)
        for comp in rutas_red.keys():
            item = QListWidgetItem(comp)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_companeros.addItem(item)
        comp_layout.addWidget(self.list_companeros)
        
        btn_comp_layout = QHBoxLayout()
        btn_todos = QPushButton("✅ Todos")
        btn_todos.setCursor(Qt.PointingHandCursor)
        btn_todos.clicked.connect(lambda: self._toggle(self.list_companeros, True))
        btn_ninguno = QPushButton("❌ Ninguno")
        btn_ninguno.setCursor(Qt.PointingHandCursor)
        btn_ninguno.clicked.connect(lambda: self._toggle(self.list_companeros, False))
        btn_comp_layout.addWidget(btn_todos)
        btn_comp_layout.addWidget(btn_ninguno)
        comp_layout.addLayout(btn_comp_layout)
        layout.addWidget(group_comp)
        
        # --- Años (Añadido V1.2.4 para consistencia) ---
        group_años = QGroupBox("📅 Años")
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
        btn_t_años = QPushButton("✅ Todos")
        btn_t_años.clicked.connect(lambda: self._toggle(self.list_años, True))
        btn_n_años = QPushButton("❌ Ninguno")
        btn_n_años.clicked.connect(lambda: self._toggle(self.list_años, False))
        btn_años_layout.addWidget(btn_t_años)
        btn_años_layout.addWidget(btn_n_años)
        años_layout.addLayout(btn_años_layout)
        layout.addWidget(group_años)
        
        # --- Info ---
        lbl_info = QLabel("⏱ El proceso puede tardar 1-3 minutos por compañero.\n"
                         "Puedes cancelar en cualquier momento.")
        lbl_info.setStyleSheet("color: #666; font-style: italic; padding: 4px;")
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)
        
        # --- Botones ---
        button_box = QDialogButtonBox()
        self.btn_ok = QPushButton("🚀 Iniciar Indexación")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setStyleSheet("""
            QPushButton { background-color: #0078D4; color: white; border: none; 
                         border-radius: 4px; padding: 10px 20px; font-weight: bold; font-size: 10pt; }
            QPushButton:hover { background-color: #005A9E; }
        """)
        self.btn_ok.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        
        button_box.addButton(self.btn_ok, QDialogButtonBox.AcceptRole)
        button_box.addButton(btn_cancel, QDialogButtonBox.RejectRole)
        layout.addWidget(button_box)
        
        # Estilo del diálogo
        self.setStyleSheet("""
            QDialog { background-color: #F5F5F5; }
            QGroupBox { background-color: white; border: 1px solid #D0D0D0; 
                        border-radius: 6px; padding: 12px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
            QListWidget { border: 1px solid #D0D0D0; border-radius: 3px; background: white; }
            QListWidget::item { padding: 3px; }
            QListWidget::item:hover { background-color: #F0F0F0; }
        """)
    
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
    """QTableWidget con drag habilitado para arrastrar archivos a SolidWorks"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
    
    def mimeData(self, items):
        """Genera mimeData con file:/// URI para drag & drop a SolidWorks"""
        mime = QMimeData()
        urls = []
        
        # Obtener las filas seleccionadas (sin duplicados)
        rows = set()
        for item in items:
            if item is not None:
                rows.add(item.row())
        
        for row in rows:
            # Columna 11 = ruta completa (V1.0.3: se movió de col 10 a col 11)
            ruta_item = self.item(row, 11)
            if ruta_item:
                ruta = ruta_item.text()
                if ruta:
                    # Convertir a file:/// URL
                    url = QUrl.fromLocalFile(ruta)
                    urls.append(url)
        
        if urls:
            mime.setUrls(urls)
            # También poner como texto plano para compatibilidad
            mime.setText('\n'.join(u.toLocalFile() for u in urls))
        
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
                    image, hbitmap = self.method_extractor(ruta, size=256)
                    if image is not None or hbitmap != 0:
                        self.thumbnail_ready.emit(row, ruta, image, hbitmap)
                except Exception as e:
                    logger.debug(f"Error procesando miniatura en hilo para {ruta}: {e}")
        finally:
            pythoncom.CoUninitialize()

class ODSWExtractor(QThread):
    """Hilo para extraer propiedades SW de 1 archivo sin bloquear la UI"""
    extracted = pyqtSignal(str, dict)
    
    def __init__(self, db, ruta):
        super().__init__()
        self.db = db
        self.ruta = ruta
        
    def run(self):
        props = extraer_propiedades_ondemand(self.db, self.ruta)
        if props:
            self.extracted.emit(self.ruta, props)

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
        self.refrescar_filtros_jerarquicos()  # Carga inicial V1.0.0
        self.cargar_preferencias()
        
        # Diagnóstico de red (V1.0.0)
        QTimer.singleShot(1000, self.verificar_rutas_red)

    def verificar_rutas_red(self):
        """Comprueba si las rutas críticas de la biblioteca son accesibles (V1.0.0)"""
        error_msg = ""
        if not os.path.exists(RUTA_BIBLIOTECA):
            error_msg += f"• No se detecta: {RUTA_BIBLIOTECA}\n"
        if not os.path.exists(RUTA_ESTANDAR):
            error_msg += f"• No se detecta: {RUTA_ESTANDAR}\n"
            
        if error_msg:
            QMessageBox.warning(self, "Problema de Red", 
                                "Atención: No se puede acceder a las librerías comerciales.\n\n" + 
                                error_msg + 
                                "\nPor favor, asegúrate de que la unidad Z: está correctamente conectada.")
            logger.error(f"Rutas de red no accesibles: {error_msg}")

    def toggle_checkboxes(self, list_widget, state):
        """Activa o desactiva todos los checkboxes en un QListWidget"""
        for i in range(list_widget.count()):
            list_widget.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)
    
    def get_selected_items(self, list_widget):
        """Devuelve una lista con el texto de los items marcados en un QListWidget"""
        sel = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                sel.append(item.text())
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
            self.btn_tipos.setText("📁 Tipos: TODOS")
        elif len(sel) == 0:
            self.btn_tipos.setText("📁 Tipos: NINGUNO")
        elif len(sel) == 1:
            self.btn_tipos.setText(f"📁 Tipos: {sel[0]}")
        else:
            self.btn_tipos.setText(f"📁 Tipos: ({len(sel)})")

    def toggle_tipos_menu(self, state):
        """Marca o desmarca todos los tipos en el menú"""
        for action in self.tipos_actions.values():
            action.setChecked(state)
        self.actualizar_texto_tipos()

    def init_ui(self):
        self.setWindowTitle("🔍 Buscador de Piezas SolidWorks - ALSI")
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
        # CABECERA (LOGO + BARRA DE BÚSQUEDA)
        # ═══════════════════════════════════════════
        header_layout = QHBoxLayout()
        header_layout.setSpacing(20)
        
        # Imagotipo Corporativo
        self.lbl_logo = QLabel()
        if os.path.exists(LOGO_IMAGOTIPO):
            pixmap = QPixmap(LOGO_IMAGOTIPO)
            self.lbl_logo.setPixmap(pixmap.scaled(180, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_logo.setText("ALSI")
            self.lbl_logo.setStyleSheet(f"color: {RAL_2010_NARANJA}; font-size: 24px; font-weight: bold;")
        header_layout.addWidget(self.lbl_logo)
        
        # Barra de búsqueda
        self.input_buscar = QLineEdit()
        self.input_buscar.setPlaceholderText("Buscar: travesaño, cama, inox (separar por comas)")
        self.input_buscar.setToolTip("Introduce palabras separadas por comas para una búsqueda inteligente")
        self.input_buscar.setFont(QFont("Segoe UI", 10))
        self.input_buscar.setMinimumHeight(40)
        self.input_buscar.returnPressed.connect(self.ejecutar_busqueda)
        header_layout.addWidget(self.input_buscar, stretch=1)

        # 4. TIPOS DE ARCHIVO (V1.0.0 - Reubicado a Barra Superior)
        self.btn_tipos = QPushButton("📁 Tipos: TODOS")
        self.btn_tipos.setMinimumHeight(40)
        self.btn_tipos.setCursor(Qt.PointingHandCursor)
        self.btn_tipos.setFixedWidth(150)
        self.btn_tipos.setStyleSheet("""
            QPushButton::menu-indicator { image: none; } 
            QPushButton { padding: 5px; font-weight: bold; }
        """)
        
        self.menu_tipos = CheckableMenu(self)  # Menú que no se cierra al seleccionar (R5)
        
        action_todos = self.menu_tipos.addAction("✅ Seleccionar Todos")
        action_todos.triggered.connect(lambda: self.toggle_tipos_menu(True))
        action_ninguno = self.menu_tipos.addAction("❌ Deseleccionar Todos")
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

        self.btn_buscar = QPushButton("🔍 Buscar")
        self.btn_buscar.setObjectName("btn_buscar")
        self.btn_buscar.setToolTip("Haz clic para iniciar la búsqueda (o pulsa Enter)")
        self.btn_buscar.setCursor(Qt.PointingHandCursor)
        self.btn_buscar.setMinimumHeight(45)
        self.btn_buscar.setFixedWidth(120)
        self.btn_buscar.clicked.connect(self.ejecutar_busqueda)
        header_layout.addWidget(self.btn_buscar)
        
        main_layout.addLayout(header_layout)

        # ═══════════════════════════════════════════
        # CONTENIDO PRINCIPAL (SPLITTER: SIDEBAR + CONTENT) V1.0.0
        # ═══════════════════════════════════════════
        
        # Splitter Principal (Horizontal) para redimensionar barra lateral
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(4) # Línea sutil
        self.main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #bdc3c7;
                margin: 2px;
            }
            QSplitter::handle:hover {
                background-color: #e67e22; /* Color corporativo al pasar el ratón */
            }
        """)

        # --- Panel filtros izquierdo (Scrollable Sidebar) ---
        panel_izquierdo = QGroupBox("Filtros Avanzados")
        panel_izquierdo.setMinimumWidth(80)
        panel_izquierdo.setMaximumWidth(500)
        izq_outer_layout = QVBoxLayout(panel_izquierdo)
        izq_outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_widget = QWidget()
        izq_layout = QVBoxLayout(scroll_widget)
        izq_layout.setContentsMargins(8, 8, 8, 8)
        izq_layout.setSpacing(10)
        
        # 1. COMPAÑEROS
        lbl_comp = QLabel("Compañeros:")
        lbl_comp.setStyleSheet("font-weight: bold; color: #555;")
        izq_layout.addWidget(lbl_comp)

        # Checkbox para Biblioteca y Estándar (V1.0.0 - Separadas)
        self.chk_siddex = QCheckBox("Incluir biblioteca Siddex")
        self.chk_siddex.setToolTip("Buscar también en la biblioteca Siddex")
        self.chk_siddex.setStyleSheet("color: #d35400; font-weight: bold;")
        izq_layout.addWidget(self.chk_siddex)

        self.chk_estandar = QCheckBox("Incluir ALSI Estándar")
        self.chk_estandar.setToolTip("Buscar también en las piezas estándar de ALSI")
        self.chk_estandar.setStyleSheet("color: #d35400; font-weight: bold;")
        izq_layout.addWidget(self.chk_estandar)

        self.chk_darkweb_ja = QCheckBox("Incluir Dark Web J.A")
        self.chk_darkweb_ja.setToolTip("Buscar también en \\\\Ofitec-5\\javier alonso")
        self.chk_darkweb_ja.setStyleSheet("color: #8e44ad; font-weight: bold;")
        izq_layout.addWidget(self.chk_darkweb_ja)

        self.list_companeros = QListWidget()
        self.list_companeros.setMaximumHeight(200)
        for comp in list(RUTAS_RED.keys()):
            item = QListWidgetItem(comp)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_companeros.addItem(item)
        izq_layout.addWidget(self.list_companeros)
        self.add_toggle_buttons(izq_layout, self.list_companeros)

        # Conectar checkboxes de biblioteca (V1.0.1 Auto-update)
        self.chk_siddex.stateChanged.connect(self.on_filtro_jerarquico_changed)
        self.chk_estandar.stateChanged.connect(self.on_filtro_jerarquico_changed)

        izq_layout.addSpacing(10)

        # 2. AÑOS
        lbl_años = QLabel("Años de Proyecto:")
        lbl_años.setStyleSheet("font-weight: bold; color: #555;")
        izq_layout.addWidget(lbl_años)
        self.list_años = QListWidget()
        self.list_años.setMaximumHeight(200)
        año_actual = datetime.now().year
        for año in range(año_actual + 1, 2012, -1):
            item = QListWidgetItem(str(año))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if año >= 2024 else Qt.Unchecked)
            self.list_años.addItem(item)
        izq_layout.addWidget(self.list_años)
        self.add_toggle_buttons(izq_layout, self.list_años)

        izq_layout.addSpacing(10)

        # 3. CARPETAS (MECANICA, LAYOUT...) - V1.2.3
        lbl_folder = QLabel("Carpetas:")
        lbl_folder.setStyleSheet("font-weight: bold; color: #555;")
        izq_layout.addWidget(lbl_folder)
        self.list_carpetas = QListWidget()
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

        izq_layout.addSpacing(10)

        izq_layout.addSpacing(10)

        # 5. CLIENTES (V1.3.0)
        lbl_clientes = QLabel("Clientes:")
        lbl_clientes.setStyleSheet("font-weight: bold; color: #555;")
        izq_layout.addWidget(lbl_clientes)
        self.list_clientes = QListWidget()
        self.list_clientes.setMaximumHeight(200)
        izq_layout.addWidget(self.list_clientes)
        self.add_toggle_buttons(izq_layout, self.list_clientes)

        izq_layout.addSpacing(10)

        # 6. PROYECTOS (V1.3.0)
        lbl_proys = QLabel("Proyectos:")
        lbl_proys.setStyleSheet("font-weight: bold; color: #555;")
        izq_layout.addWidget(lbl_proys)
        self.list_proyectos = QListWidget()
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
        
        # Tabla (V1.0.4: 20 columnas incluyendo propiedades SW)
        self.tabla = TablaArrastrable()
        self.tabla.setColumnCount(20)
        self.tabla.setHorizontalHeaderLabels([
            "Vista", "Nombre", "Compañero", "Año", "Cliente", "Proyecto", "Tipo", 
            "Cód. Proyecto", "Nombre Proyecto", "Cód. Orden", "Nombre Orden",
            "Ruta Completa", "Soldadura", "Pintura", "Montaje", "Láser", "Torno", "Fresa",
            "Tratamiento", "Material"
        ])
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSortingEnabled(True)  # <-- Ordenación por columnas activada
        
        # Ajuste de tamaño de filas e iconos para las miniaturas
        self.tabla.setIconSize(QSize(44, 44))
        self.tabla.verticalHeader().setDefaultSectionSize(46)
        
        header = self.tabla.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive) # Todas interactivas V1.3.11
        header.setStretchLastSection(True) # La última columna estira hasta el final V1.3.12
        header.setStyleSheet("""
            QHeaderView::section {
                background-color: #7f8c8d;
                color: white;
                padding: 4px;
                border: none;
                border-right: 1px solid #95a5a6; /* Delimitadores visuales */
                font-weight: bold;
            }
        """)
        
        self.tabla.setColumnWidth(0, 52)  # Vista
        self.tabla.setColumnWidth(1, 400) # Nombre
        self.tabla.setColumnWidth(2, 95)  # Compañero
        self.tabla.setColumnWidth(3, 55)  # Año
        self.tabla.setColumnWidth(4, 120) # Cliente
        self.tabla.setColumnWidth(5, 250) # Proyecto
        self.tabla.setColumnWidth(6, 120) # Tipo
        self.tabla.setColumnHidden(7, True) # Cod. Proy
        # Ocultar nuevas columnas de propiedades (V1.0.4)
        for i in range(12, 20):
            self.tabla.setColumnHidden(i, True)
        
        self.tabla.doubleClicked.connect(self.abrir_carpeta_seleccionada)
        self.tabla.selectionModel().currentRowChanged.connect(self.actualizar_preview)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self.mostrar_menu_contextual)

        self.splitter.addWidget(self.tabla)

        # Panel Preview
        self.panel_preview = QFrame()
        self.panel_preview.setObjectName("panel_preview")
        self.panel_preview.setFrameStyle(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(self.panel_preview)
        preview_layout.setContentsMargins(15, 20, 15, 20)
        preview_layout.setSpacing(8)
        
        self.lbl_preview_icon = QLabel("🔍")
        self.lbl_preview_icon.setAlignment(Qt.AlignCenter)
        self.lbl_preview_icon.setStyleSheet("font-size: 64px;")
        self.lbl_preview_icon.setMinimumHeight(100)
        
        # Efecto de opacidad para animaciones (V1.3.16)
        self.preview_opacity = QGraphicsOpacityEffect()
        self.lbl_preview_icon.setGraphicsEffect(self.preview_opacity)
        self.anim_opacity = QPropertyAnimation(self.preview_opacity, b"opacity")
        self.anim_opacity.setDuration(400)
        
        preview_layout.addWidget(self.lbl_preview_icon)
        
        self.lbl_preview_nombre = QLabel("Seleccione un archivo")
        self.lbl_preview_nombre.setAlignment(Qt.AlignCenter)
        self.lbl_preview_nombre.setWordWrap(True)
        self.lbl_preview_nombre.setStyleSheet(f"color: {RAL_2010_NARANJA}; font-weight: bold; font-size: 14px;")
        preview_layout.addWidget(self.lbl_preview_nombre)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet(f"background-color: {RAL_7000_GRIS};")
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
        self.lbl_preview_ruta.setStyleSheet("font-size: 10px; color: #666;")
        self.lbl_preview_ruta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Propiedades SW (V1.0.4)
        self.lbl_preview_props = QLabel("")
        self.lbl_preview_props.setFont(QFont("Segoe UI", 9))
        self.lbl_preview_props.setStyleSheet("color: #2c3e50; font-weight: bold;")
        self.lbl_preview_sw_procesos = QLabel("")
        self.lbl_preview_sw_procesos.setFont(QFont("Segoe UI", 8))
        self.lbl_preview_sw_procesos.setWordWrap(True)

        preview_layout.addWidget(self.lbl_preview_tipo)
        preview_layout.addWidget(self.lbl_preview_comp)
        preview_layout.addWidget(self.lbl_preview_proyecto)
        preview_layout.addWidget(self.lbl_preview_tamaño)
        preview_layout.addWidget(self.lbl_preview_props)
        preview_layout.addWidget(self.lbl_preview_sw_procesos)
        preview_layout.addWidget(self.lbl_preview_ruta)
        
        preview_layout.addSpacing(15)
        
        # ═══════════════════════════════════════════
        # FILTRAR POR PROPIEDADES (V1.0.4 - Debajo de preview)
        # ═══════════════════════════════════════════
        self.group_prop_filters = QGroupBox("🔧 Filtrar por Propiedades")
        self.group_prop_filters.setStyleSheet(f"font-weight: bold; color: {RAL_7000_GRIS};")
        prop_filter_layout = QVBoxLayout(self.group_prop_filters)
        prop_grid = QGridLayout()
        prop_grid.setSpacing(5)
        
        procesos = ["Soldadura", "Pintura", "Montaje", "Láser", "Torno", "Fresa"]
        self.prop_checkboxes = {}
        for i, proc in enumerate(procesos):
            chk = QCheckBox(proc)
            chk.setStyleSheet("font-weight: normal; color: #333;")
            chk.stateChanged.connect(lambda: self.ejecutar_busqueda(auto=True))
            prop_grid.addWidget(chk, i // 2, i % 2)
            self.prop_checkboxes[proc] = chk
            
        prop_filter_layout.addLayout(prop_grid)
        preview_layout.addWidget(self.group_prop_filters)
        
        preview_layout.addStretch()
        
        tip_drag = QLabel("🖱 Arrastra para abrir en SolidWorks")
        tip_drag.setStyleSheet(f"color: {RAL_7000_GRIS}; font-style: italic; font-size: 11px;")
        tip_drag.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(tip_drag)

        self.splitter.addWidget(self.panel_preview)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        
        # Añadir splitter derecho al splitter principal
        self.main_splitter.addWidget(self.splitter)
        self.main_splitter.setStretchFactor(1, 1)
        
        # Restaurar ancho guardado (Persistencia)
        saved_width = self.controller.load_preference('sidebar_width')
        if saved_width:
             self.main_splitter.setSizes([int(saved_width), 1200])
        else:
             self.main_splitter.setSizes([240, 1200]) # Default original

        main_layout.addWidget(self.main_splitter, stretch=1)

        # PIE DE PÁGINA (Botones y Estado)
        # ═══════════════════════════════════════════
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)
        
        # Botones de Acción Rápida (V1.0.0)
        self.btn_abrir_carpeta = QPushButton("📁 Abrir Carpeta")
        self.btn_abrir_carpeta.setToolTip("Abre la carpeta que contiene el archivo")
        self.btn_abrir_carpeta.clicked.connect(self.abrir_carpeta_seleccionada)
        self.btn_abrir_carpeta.setEnabled(False)
        self.btn_abrir_carpeta.setCursor(Qt.PointingHandCursor)
        footer_layout.addWidget(self.btn_abrir_carpeta)
        
        self.btn_copiar_ruta = QPushButton("📋 Copiar Ruta")
        self.btn_copiar_ruta.setToolTip("Copia la ruta completa al portapapeles")
        self.btn_copiar_ruta.clicked.connect(self.copiar_ruta_seleccionada)
        self.btn_copiar_ruta.setEnabled(False)
        self.btn_copiar_ruta.setCursor(Qt.PointingHandCursor)
        footer_layout.addWidget(self.btn_copiar_ruta)
        
        self.btn_copiar_nombre = QPushButton("📝 Copiar Nombre")
        self.btn_copiar_nombre.setToolTip("Copia solo el nombre del archivo")
        self.btn_copiar_nombre.clicked.connect(self.copiar_nombre_seleccionado)
        self.btn_copiar_nombre.setEnabled(False)
        self.btn_copiar_nombre.setCursor(Qt.PointingHandCursor)
        footer_layout.addWidget(self.btn_copiar_nombre)
        
        # Separador visual
        line_sep = QFrame()
        line_sep.setFrameShape(QFrame.VLine)
        line_sep.setFrameShadow(QFrame.Sunken)
        footer_layout.addWidget(line_sep)
        # Botón Indexar Compañeros (Renombrado V1.0.0)
        self.btn_indexar = QPushButton("Indexar Compañeros")
        self.btn_indexar.setToolTip("Abre el diálogo para elegir qué compañeros indexar")
        self.btn_indexar.setIcon(QIcon(LOGO_ISOTIPO)) # Usar el isotipo naranja
        self.btn_indexar.setStyleSheet("""
            QPushButton {
                background-color: #e67e22; 
                color: white; 
                font-weight: bold; 
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #d35400;
            }
        """)
        self.btn_indexar.setFixedWidth(185)
        self.btn_indexar.clicked.connect(self.confirmar_indexacion)
        footer_layout.addWidget(self.btn_indexar)

        # Botón Indexar Comerciales (Nuevo V1.0.0)
        self.btn_indexar_comerciales = QPushButton("Indexar Comerciales")
        self.btn_indexar_comerciales.setToolTip("Indexar Biblioteca Siddex y Alsi Estándar")
        # self.btn_indexar_comerciales.setIcon(QIcon("ruta_icono.png")) # Opcional
        self.btn_indexar_comerciales.setStyleSheet("""
            QPushButton {
                background-color: #27ae60; 
                color: white; 
                font-weight: bold; 
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        self.btn_indexar_comerciales.setFixedWidth(185)
        self.btn_indexar_comerciales.clicked.connect(self.abrir_dialogo_indexacion_comerciales)
        footer_layout.addWidget(self.btn_indexar_comerciales)
        
        # Botón Indexar Otros (Nuevo V1.0.3)
        self.btn_indexar_otros = QPushButton("Indexar Otros")
        self.btn_indexar_otros.setToolTip("Indexar carpetas especiales (ej: Dark Web J.A)")
        self.btn_indexar_otros.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad; 
                color: white; 
                font-weight: bold; 
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #9b59b6;
            }
        """)
        self.btn_indexar_otros.setFixedWidth(185)
        self.btn_indexar_otros.setFixedWidth(185)
        self.btn_indexar_otros.clicked.connect(self.abrir_dialogo_indexacion_otros)
        footer_layout.addWidget(self.btn_indexar_otros)
        
        # Botón Extraer Propiedades SW (Nuevo V1.0.4)
        self.btn_extraer_sw = QPushButton("Extraer Props SW")
        self.btn_extraer_sw.setToolTip("Extrae propiedades (Láser, Pintura...) de SolidWorks en segundo plano")
        self.btn_extraer_sw.setStyleSheet("""
            QPushButton {
                background-color: #3498db; 
                color: white; 
                font-weight: bold; 
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.btn_extraer_sw.setFixedWidth(130)
        self.btn_extraer_sw.clicked.connect(self.iniciar_extraccion_sw)
        footer_layout.addWidget(self.btn_extraer_sw)
        
        self.btn_cancelar = QPushButton("⏹ Cancelar")
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
        footer_layout.addWidget(self.lbl_status, stretch=1)

        # Botones de Ayuda e Info (V1.0.0 Polish Round 2)
        self.btn_ayuda = QPushButton("❓")
        self.btn_ayuda.setToolTip("Guía de uso rápida") 
        self.btn_ayuda.setStatusTip("Botón de ayuda") 
        self.btn_ayuda.setCursor(Qt.PointingHandCursor)
        self.btn_ayuda.setFixedSize(42, 42)
        self.btn_ayuda.clicked.connect(self.mostrar_ayuda)
        self.btn_ayuda.setStyleSheet("""
            QPushButton { 
                background-color: #3498db; 
                color: white;
                font-size: 20px; 
                border-radius: 8px;
                border: 1px solid #2980b9;
                transition: all 0.3s ease;
            }
            QPushButton:hover { 
                background-color: #2980b9; 
                border: 1px solid #1c5980;
                margin-top: -2px;
            }
            QPushButton:pressed { 
                background-color: #1c5980; 
                margin-top: 0px;
            }
        """)
        footer_layout.addWidget(self.btn_ayuda)

        self.btn_info = QPushButton("ℹ️")
        self.btn_info.setToolTip("Acerca de") # Tooltip simplificado
        self.btn_info.setStatusTip("Información de la aplicación")
        self.btn_info.setCursor(Qt.PointingHandCursor)
        self.btn_info.setFixedSize(42, 42)
        self.btn_info.clicked.connect(self.mostrar_info)
        self.btn_info.setStyleSheet("""
            QPushButton { 
                background-color: #95a5a6; 
                color: white;
                font-size: 20px; 
                border-radius: 8px;
                border: 1px solid #7f8c8d;
                transition: all 0.3s ease;
            }
            QPushButton:hover { 
                background-color: #7f8c8d; 
                border: 1px solid #6c7a7d;
                margin-top: -2px;
            }
            QPushButton:pressed { 
                background-color: #6c7a7d; 
                margin-top: 0px;
            }
        """)
        footer_layout.addWidget(self.btn_info)
        
        self.lbl_count = QLabel("0 resultados")
        footer_layout.addWidget(self.lbl_count)
        
        main_layout.addLayout(footer_layout)
        
        self.actualizar_estilos()

    def actualizar_estilos(self):
        # fuentes corporativas
        font_body = "Poppins, Segoe UI, Arial"
        
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: #F8F9FA;
                font-family: {font_body};
                font-size: 13px;
                color: #333;
            }}
            QLineEdit {{
                border: 2px solid {RAL_7000_GRIS};
                border-radius: 6px;
                padding: 8px 15px;
                background-color: {WHITE};
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {RAL_2010_NARANJA};
            }}
            QPushButton {{
                background-color: {RAL_7000_GRIS};
                color: {WHITE};
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: bold;
                border: none;
            }}
            QPushButton#btn_toggle {{
                padding: 1px 2px;
                font-size: 9px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #8C999F;
            }}
            QPushButton#btn_buscar {{
                background-color: {RAL_2010_NARANJA};
                font-size: 15px;
            }}
            QPushButton#btn_buscar:hover {{
                background-color: #F06A2E;
            }}
            QPushButton#btn_indexar {{
                background-color: {RAL_2010_NARANJA};
            }}
            QPushButton#btn_cancelar {{
                background-color: #D9534F;
            }}
            QComboBox {{
                border: 1px solid {RAL_7000_GRIS};
                border-radius: 4px;
                padding: 5px;
                background-color: {WHITE};
            }}
            QTableWidget {{
                background-color: {WHITE};
                border: 1px solid {RAL_7000_GRIS};
                border-radius: 4px;
                gridline-color: #EEEEEE;
            }}
            QTableWidget::item {{
                padding-top: 2px;
                padding-bottom: 2px;
            }}
            QHeaderView::section {{
                background-color: {RAL_7000_GRIS};
                color: {WHITE};
                padding: 8px;
                font-weight: bold;
                border: none;
            }}
            QListWidget {{
                border: 1px solid {RAL_7000_GRIS};
                border-radius: 4px;
                background-color: {WHITE};
            }}
            QListWidget::item:selected {{
                background-color: {RAL_2010_NARANJA};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {RAL_7000_GRIS};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                color: {RAL_2010_NARANJA};
            }}
            QSplitter::handle {{
                background-color: #DDD;
            }}
            QFrame#panel_preview {{
                background-color: {WHITE};
                border: 1px solid {RAL_7000_GRIS};
                border-radius: 8px;
            }}
        """)

    # ═══════════════════════════════════════════
    # PREFERENCIAS
    # ═══════════════════════════════════════════
    def cargar_preferencias(self):
        self.input_buscar.setText(self.controller.load_preference("ultimo_termino", ""))
        
        # Restaurar Checkbox Biblioteca (V1.0.0)
        sid_status = self.controller.load_preference("incluir_siddex", "0")
        self.chk_siddex.setChecked(sid_status == "1")
        est_status = self.controller.load_preference("incluir_estandar", "0")
        self.chk_estandar.setChecked(est_status == "1")
        
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
        
        # Guardar Checkbox Biblioteca (V1.0.0)
        self.controller.save_preference("incluir_siddex", "1" if self.chk_siddex.isChecked() else "0")
        self.controller.save_preference("incluir_estandar", "1" if self.chk_estandar.isChecked() else "0")
        

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

            # Validación: al menos un compañero y un año, A MENOS QUE se busque en biblioteca (V1.0.0)
            buscar_siddex = self.chk_siddex.isChecked()
            buscar_estandar = self.chk_estandar.isChecked()
            buscar_darkweb = self.chk_darkweb_ja.isChecked()
            
            if not comp_sel and not años_sel and not buscar_siddex and not buscar_estandar and not buscar_darkweb:
                if not auto:
                    QMessageBox.warning(self, "Atención", "Selecciona al menos un compañero y un año, o marca una casilla de Biblioteca.")
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

            # Filtros de Propiedades (V1.0.4)
            procesos_filtro = {proc: chk.isChecked() for proc, chk in self.prop_checkboxes.items()}

            resultados = self.controller.perform_search(
                termino, 
                comp_sel,
                años_sel,
                extensiones,
                carpetas_sel,
                clientes_sel,
                proyectos_sel,
                incluir_siddex=buscar_siddex,
                incluir_estandar=buscar_estandar,
                incluir_darkweb_ja=buscar_darkweb,
                procesos_filtro=procesos_filtro
            )
            
            # Prealocar filas de golpe (mucho más rápido que insertRow en bucle)
            self.tabla.setRowCount(len(resultados))
            vistas_pendientes = []
            
            for row, data in enumerate(resultados):
                # data[10] es la ruta completa
                ruta = data[10]
                vistas_pendientes.append((row, ruta))
                
                # Columna de miniatura (Vista centrada V1.0.3)
                lbl_img = QLabel()
                lbl_img.setAlignment(Qt.AlignCenter)
                lbl_img.setContentsMargins(0, 0, 0, 0)
                lbl_img.setStyleSheet("background: transparent; border: none; padding: 0px; margin: 0px;")
                self.tabla.setCellWidget(row, 0, lbl_img)
                
                for col, val in enumerate(data):
                    item = QTableWidgetItem(str(val) if val else "")
                    self.tabla.setItem(row, col + 1, item)
            
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
            
            if len(resultados) >= 5000:
                self.lbl_status.setText("⚠ Mostrando 5000 de 5000+ resultados. Refina tu búsqueda.")
            else:
                self.lbl_status.setText("Listo")
                
            self.lbl_count.setText(f"{len(resultados)} resultados")
            if not resultados and termino:
                txt = f"No se encontraron resultados para '{termino}'"
                if buscar_siddex or buscar_estandar:
                    txt += "\n(Pista: Asegúrate de haber usado el botón 'Indexar Comerciales' al menos una vez)"
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
        dialog = DialogIndexacion(RUTAS_RED, self)
        dialog.setWindowTitle("Configurar Indexación Compañeros")
        if dialog.exec_() == QDialog.Accepted:
            companeros = dialog.get_companeros_seleccionados()
            anos = dialog.get_años_seleccionados()
            if companeros:
                self.iniciar_indexacion(companeros, anos)
            else:
                QMessageBox.warning(self, "Atención", "No has seleccionado ningún compañero.")

    def abrir_dialogo_indexacion_comerciales(self):
        # Nuevo Diálogo para Biblioteca y Estándar (V1.0.0)
        dialog = QDialog(self)
        dialog.setWindowTitle("Indexar Comerciales")
        dialog.setMinimumWidth(350)
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        layout = QVBoxLayout(dialog)

        lbl_info = QLabel("Selecciona las carpetas comerciales a indexar:")
        lbl_info.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(lbl_info)

        # Checkboxes
        chk_biblioteca = QCheckBox("Biblioteca Siddex")
        chk_biblioteca.setChecked(True)
        layout.addWidget(chk_biblioteca)

        chk_estandar = QCheckBox("Alsi Estándar")
        chk_estandar.setChecked(True)
        layout.addWidget(chk_estandar)

        # Botones
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec_() == QDialog.Accepted:
            rutas_a_indexar = {}
            if chk_biblioteca.isChecked():
                rutas_a_indexar['BIBLIOTECA'] = RUTA_BIBLIOTECA
            if chk_estandar.isChecked():
                rutas_a_indexar['ESTANDAR'] = RUTA_ESTANDAR
            
            if rutas_a_indexar:
                # Iniciamos indexación SIN pasar años (lista vacía) para que no filtre por año
                self.iniciar_indexacion(rutas_a_indexar, anos_sel=[], rutas_custom=rutas_a_indexar) 
            else:
                QMessageBox.warning(self, "Atención", "No has seleccionado ninguna carpeta.")

    def abrir_dialogo_indexacion_otros(self):
        # Nuevo Diálogo para Otras Carpetas (V1.0.3)
        dialog = QDialog(self)
        dialog.setWindowTitle("Indexar Otras Carpetas")
        dialog.setMinimumWidth(350)
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        layout = QVBoxLayout(dialog)

        lbl_info = QLabel("Selecciona las carpetas adicionales a indexar:")
        lbl_info.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(lbl_info)

        # Checkboxes
        chk_darkweb = QCheckBox("Dark Web J.A")
        chk_darkweb.setChecked(True)
        layout.addWidget(chk_darkweb)

        # Botones
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec_() == QDialog.Accepted:
            rutas_a_indexar = {}
            if chk_darkweb.isChecked():
                rutas_a_indexar['DARKWEB_JA'] = RUTA_DARKWEB_JA
            
            if rutas_a_indexar:
                # Iniciamos indexación SIN pasar años (lista vacía) para que no filtre por año
                self.iniciar_indexacion(rutas_a_indexar, anos_sel=[], rutas_custom=rutas_a_indexar) 
            else:
                QMessageBox.warning(self, "Atención", "No has seleccionado ninguna carpeta.")

    def iniciar_indexacion(self, companeros_sel, anos_sel, rutas_custom=None):
        self.btn_indexar.setEnabled(False)
        self.btn_cancelar.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminado
        
        # Determinar qué diccionario de rutas usar (V1.0.0)
        rutas_dict = rutas_custom if rutas_custom else RUTAS_RED
        
        # Si usamos rutas custom, companeros_sel debe ser la lista de claves de ese dict
        if rutas_custom:
            companeros_sel = list(rutas_custom.keys())

        self.lbl_status.setText(f"Iniciando indexación de {len(companeros_sel)} compañeros...")
        
        self.thread = IndexadorThread(self.db, rutas_dict, companeros_sel, anos_sel)
        self.thread.status.connect(self.lbl_status.setText)
        self.thread.progress.connect(lambda n: self.lbl_count.setText(f"{n} archivos indexados"))
        self.thread.comp_finished.connect(self.on_comp_indexado)
        self.thread.finished.connect(self.finalizar_indexacion)
        self.thread.error.connect(lambda e: QMessageBox.critical(self, "Error", f"Error en indexación: {e}"))
        self.thread.start()

    def cancelar_indexacion(self):
        if hasattr(self, 'thread') and self.thread and self.thread.isRunning():
            self.thread.cancelar()
            self.lbl_status.setText("⏹ Cancelando... esperando a que termine el compañero actual")
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
    # EXTRACCIÓN DE PROPIEDADES SW (V1.0.4)
    # ═══════════════════════════════════════════
    def iniciar_extraccion_sw(self):
        sw_thread = getattr(self, 'sw_thread', None)
        if sw_thread is not None:
            try:
                if sw_thread.isRunning():
                    QMessageBox.warning(self, "Extracción en curso", "Ya hay una extracción de propiedades SolidWorks en curso.")
                    return
            except RuntimeError:
                pass
            
        with self.db.get_connection() as conn:
            c = conn.execute("SELECT COUNT(*) FROM archivos WHERE extension IN ('.sldprt', '.sldasm') AND (sw_props_extracted IS NULL OR sw_props_extracted = 0)")
            pendientes = c.fetchone()[0]
            
        if pendientes == 0:
            QMessageBox.information(self, "Completado", "Todas las piezas tienen ya extraídas sus propiedades.")
            return
            
        resp = QMessageBox.question(self, "Extraer Propiedades", f"Hay {pendientes:,} archivos de SolidWorks pendientes de extraer sus propiedades personalizadas (Láser, Pintura, etc.).\\n\\nEl proceso se ejecutará en segundo plano usando SolidWorks. Tardará varios minutos u horas dependiendo de la cantidad, pero puedes seguir usando la aplicación.\\n\\n¿Deseas comenzar la extracción de este lote ahora?", QMessageBox.Yes | QMessageBox.No)
        
        if resp == QMessageBox.Yes:
            self.btn_extraer_sw.setEnabled(False)
            self.btn_extraer_sw.setText("Extrayendo...")
            self.lbl_status.setText("Iniciando extractor SW...")
            
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, pendientes)
            self.progress_bar.setValue(0)
            
            self.sw_thread = SWPropertyExtractorThread(self.db, batch_size=500)
            self.sw_thread.progress.connect(self.on_extraccion_progress)
            self.sw_thread.status.connect(self.lbl_status.setText)
            self.sw_thread.error.connect(lambda e: QMessageBox.critical(self, "Error SW", e))
            self.sw_thread.finished.connect(self.on_extraccion_finished)
            self.sw_thread.file_extracted.connect(self.on_sw_file_extracted)
            self.sw_thread.start()

    def on_extraccion_progress(self, procesados, total):
        self.progress_bar.setValue(procesados)

    def on_extraccion_finished(self, procesados, duracion):
        self.btn_extraer_sw.setEnabled(True)
        self.btn_extraer_sw.setText("Extraer Props SW")
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"Extracción SW Finalizada ({procesados} procesados en {duracion/60:.1f} min)")
        if procesados > 0:
            self.ejecutar_busqueda()
            
    def on_sw_file_extracted(self, ruta, props):
        # Si el usuario está viendo actualmente el archivo que se acaba de extraer
        if hasattr(self, 'current_preview_data') and self.current_preview_data and self.current_preview_data.get('ruta') == ruta:
            # Actualizar data en RAM
            for pk, pv in props.items():
                self.current_preview_data[pk] = pv
            self.timer_preview.start(50)  # Forzar repintado del preview


    # ═══════════════════════════════════════════
    # PREVISUALIZACIÓN (Cambio 4)
    # ═══════════════════════════════════════════


    def extraer_miniatura_raw(self, ruta, size=256):
        """Devuelve (QImage, hbitmap) permitiendo su uso seguro en QThreads (V1.0.3)"""
        try:
            if not ruta or not os.path.exists(ruta):
                return None, 0
            
            ext = Path(ruta).suffix.lower()
            
            # 1. SolidWorks OLE (PreviewPNG)
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

            # 2. PDF
            if ext == '.pdf':
                try:
                    import fitz
                    doc = fitz.open(ruta)
                    if doc.page_count > 0:
                        page = doc[0]
                        mat = fitz.Matrix(2, 2)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                        if not image.isNull():
                            # Retornar una copia para evitar problemas de punteros al destruir 'pix'
                            return image.copy(), 0
                    doc.close()
                except Exception as e:
                    logger.debug(f"PyMuPDF falló para PDF: {e}")

            # 3. IShellItemImageFactory (hbitmap)
            try:
                hbitmap = self._thumbnail_via_shell_factory(ruta, size)
                if hbitmap and hbitmap != 0:
                    return None, hbitmap
            except Exception as e:
                logger.debug(f"IShellItemImageFactory falló: {e}")

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
            logger.debug(f"_thumbnail_via_shell_factory error: {e}")
        
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

            nombre = get_text(1)
            comp = get_text(2)
            año = get_text(3)
            cliente = get_text(4)
            proyecto = get_text(5)
            tipo = get_text(6)
            cod_proy = get_text(7)
            nom_proy = get_text(8)
            cod_ord = get_text(9)
            nom_ord = get_text(10)
            ruta = get_text(11)
            # Extracción de propiedades para preview (V1.0.4)
            soldadura = get_text(12)
            pintura = get_text(13)
            montaje = get_text(14)
            laser = get_text(15)
            torno = get_text(16)
            fresa = get_text(17)
            tratami = get_text(18)
            material = get_text(19)
            
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
            self.lbl_preview_tipo.setText(f"📎 Tipo: {tipo_desc} ({tipo})")
            self.lbl_preview_comp.setText(f"👤 Compañero: {comp} | AÑO {año}")
            
            proy_str = f"{cod_proy} {nom_proy}" if cod_proy else (nom_proy if nom_proy else proyecto)
            ord_str = f"Orden: {cod_ord} {nom_ord}" if cod_ord else ""
            self.lbl_preview_proyecto.setText(f"🏢 Cliente: {cliente}\n🏗️ Proyecto: {proy_str}\n📄 {ord_str}")
            self.lbl_preview_ruta.setText(f"📂 {ruta}")
            self.lbl_preview_tamaño.setText("💾 Tamaño: Cargando...")
            
            # Mostrar propiedades V1.0.4
            if ext in ('.sldprt', '.sldasm'):
                props_text = ""
                if material: props_text += f"🧱 Material: {material}\n"
                if tratami: props_text += f"🔨 Tratamiento: {tratami}\n"
                self.lbl_preview_props.setText(props_text)
                self.lbl_preview_props.setVisible(True)
                
                proc_list = []
                if soldadura == 'Sí': proc_list.append("👨‍🏭 SOLDADURA")
                if pintura == 'Sí': proc_list.append("🎨 PINTURA")
                if montaje == 'Sí': proc_list.append("🏗️ MONTAJE")
                if laser == 'Sí': proc_list.append("⚡ LÁSER")
                if torno == 'Sí': proc_list.append("🌀 TORNO")
                if fresa == 'Sí': proc_list.append("⚙️ FRESA")
                
                if proc_list:
                    self.lbl_preview_sw_procesos.setText(" | ".join(proc_list))
                    self.lbl_preview_sw_procesos.setVisible(True)
                else:
                    self.lbl_preview_sw_procesos.setText("Sin procesos definidos")
                    self.lbl_preview_sw_procesos.setVisible(True)
            else:
                self.lbl_preview_props.setVisible(False)
                self.lbl_preview_sw_procesos.setVisible(False)
            
            # Limpiar icono previo o poner temporal
            if ruta not in self.cache_miniaturas:
                icono = ICONOS_EXTENSION.get(ext, '🔍')
                self.lbl_preview_icon.setPixmap(QPixmap())
                self.lbl_preview_icon.setText(icono)
                self.preview_opacity.setOpacity(0.5)
            
            # 2. DIFERIR RECURSOS PESADOS (Miniatura, os.path.exists, etc.)
            self._preview_hd_loaded = False  # Resetear flag HD para nueva fila
            self.current_preview_data = {
                'ruta': ruta, 'tipo': tipo, 'ext': ext
            }
            self.timer_preview.start(100) # (V1.0.05) Esperar 100ms antes de cargar la ruta

        except Exception as e:
            logger.debug(f"Error actualizando preview inicial: {e}")

    def set_cell_thumbnail(self, row, pixmap):
        """Helper para poner el pixmap en el QLabel de la celda (V1.0.3)"""
        try:
            widget = self.tabla.cellWidget(row, 0)
            if isinstance(widget, QLabel):
                scaled = pixmap.scaled(50, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                widget.setPixmap(scaled)
        except Exception as e:
            logger.debug(f"Error set_cell_thumbnail: {e}")

    def on_thumbnail_ready(self, row, ruta, image, hbitmap):
        """Callback ejecutado en el hilo UI cuando el ThumbnailWorker extrae una miniatura"""
        try:
            # Guard: comprobar que la fila sigue existiendo en la tabla
            if row < 0 or row >= self.tabla.rowCount():
                if hbitmap and hbitmap != 0:
                    import ctypes
                    from ctypes import c_void_p
                    ctypes.windll.gdi32.DeleteObject.argtypes = [c_void_p]
                    ctypes.windll.gdi32.DeleteObject(hbitmap)
                return
            
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
                self.set_cell_thumbnail(row, pixmap)
                
                # Si es la fila actualmente seleccionada, poner preview provisional
                # (será reemplazado por _actualizar_preview_recursos_pesados con calidad HD)
                try:
                    if row == self.tabla.currentRow() and not getattr(self, '_preview_hd_loaded', False):
                        self.lbl_preview_icon.setPixmap(pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                        self.lbl_preview_icon.setText("")
                except RuntimeError:
                    pass  # Widget eliminado durante búsqueda rápida
                    
        except Exception as e:
            logger.debug(f"Error renderizando miniatura remota fila {row}: {e}")

    def _actualizar_preview_recursos_pesados(self):
        """Ejecutado por el timer_preview tras 100ms de inactividad (V1.0.05)"""
        try:
            data = self.current_preview_data
            ruta = data.get('ruta')
            if not ruta: return

            # Verificar existencia (IO Pesado en red)
            if not os.path.exists(ruta):
                 self.lbl_preview_tamaño.setText("💾 Tamaño: No accesible")
                 return

            # Tamaño
            size = os.path.getsize(ruta)
            if size < 1024:
                self.lbl_preview_tamaño.setText(f"💾 Tamaño: {size} B")
            elif size < 1024 * 1024:
                self.lbl_preview_tamaño.setText(f"💾 Tamaño: {size / 1024:.1f} KB")
            else:
                self.lbl_preview_tamaño.setText(f"💾 Tamaño: {size / (1024 * 1024):.1f} MB")

            # Miniatura HD para el panel preview (extracción directa a 512px, sin caché)
            image, hbitmap = self.extraer_miniatura_raw(ruta, size=512)
            pixmap = None
            if hbitmap != 0:
                pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapPremultipliedAlpha)
                if not pixmap or pixmap.isNull():
                    pixmap = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapNoAlpha)
                import ctypes
                ctypes.windll.gdi32.DeleteObject(hbitmap)
            elif image is not None and not image.isNull():
                pixmap = QPixmap.fromImage(image)
            
            if not pixmap or pixmap.isNull():
                # Fallback: usar caché si la extracción HD falla
                pixmap = self.extraer_miniatura(ruta)
            
            if pixmap and not pixmap.isNull():
                self.lbl_preview_icon.setPixmap(pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.lbl_preview_icon.setText("")
                self._preview_hd_loaded = True
                self.anim_opacity.stop()
                self.preview_opacity.setOpacity(0.0)
                self.anim_opacity.setStartValue(0.0)
                self.anim_opacity.setEndValue(1.0)
                self.anim_opacity.start()
            else:
                self.preview_opacity.setOpacity(1.0)

            # V1.0.4: Extracción on-demand si es SW y le faltan props
            ext = Path(ruta).suffix.lower()
            if ext in ('.sldprt', '.sldasm'):
                 # Chequear si le faltan de base de datos
                 with self.db.get_connection() as conn:
                     c = conn.execute("SELECT sw_props_extracted FROM archivos WHERE ruta_completa = ?", (ruta,))
                     row = c.fetchone()
                     extracted = row[0] if (row and row[0] is not None) else 0
                     
                 if extracted == 0:
                     self.od_thread = ODSWExtractor(self.db, ruta)
                     self.od_thread.extracted.connect(self.on_sw_file_extracted)
                     self.od_thread.start()

        except Exception as e:
            logger.debug(f"Error en recursos diferidos: {e}")

    # ═══════════════════════════════════════════
    # ACCIONES
    # ═══════════════════════════════════════════
    def abrir_carpeta_seleccionada(self):
        row = self.tabla.currentRow()
        if row >= 0:
            ruta = self.tabla.item(row, 11).text()  # Columna 11 = Ruta Completa
            if ruta and os.path.exists(ruta):
                subprocess.Popen(f'explorer /select,"{ruta}"')
            else:
                QMessageBox.critical(self, "Error", "No se puede acceder a la ruta. Puede que el servidor no esté disponible.")

    def copiar_ruta_seleccionada(self):
        row = self.tabla.currentRow()
        if row >= 0:
            ruta = self.tabla.item(row, 11).text()  # Columna 11 = Ruta Completa
            QApplication.clipboard().setText(ruta)
            self.lbl_status.setText("✅ Ruta copiada al portapapeles")

    def mostrar_menu_contextual(self, pos):
        if self.tabla.currentRow() >= 0:
            menu = QMenu()
            menu.setStyleSheet("""
                QMenu { background: white; border: 1px solid #D0D0D0; padding: 4px; }
                QMenu::item { padding: 6px 24px; }
                QMenu::item:selected { background: #CCE8FF; }
            """)
            action_open = QAction("📁 Abrir Carpeta", self)
            action_open.triggered.connect(self.abrir_carpeta_seleccionada)
            action_copy = QAction("📋 Copiar Ruta", self)
            action_copy.triggered.connect(self.copiar_ruta_seleccionada)
            action_copy_name = QAction("📝 Copiar Nombre", self)
            action_copy_name.triggered.connect(self.copiar_nombre_seleccionado)
            
            menu.addAction(action_open)
            menu.addAction(action_copy)
            menu.addAction(action_copy_name)

            # Columna 11 = Ruta Completa
            item_ruta = self.tabla.item(self.tabla.currentRow(), 11)
            ruta = item_ruta.text() if item_ruta else ""
            if ruta and os.path.exists(ruta):
                menu.addSeparator()
                menu.addAction("🚀 Abrir/Insertar en SolidWorks").triggered.connect(
                    lambda: os.startfile(ruta)
                )

            menu.exec_(self.tabla.mapToGlobal(pos))

    def copiar_nombre_seleccionado(self):
        """Acción proactiva: copiar solo el nombre del archivo"""
        row = self.tabla.currentRow()
        if row >= 0:
            nombre = self.tabla.item(row, 1).text() # Columna 1 = Nombre
            QApplication.clipboard().setText(nombre)
            self.lbl_status.setText(f"✅ Nombre copiado: {nombre}")

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
                    html = html.replace("```markdown", "<pre style='background:#eee; padding:10px;'>").replace("```", "</pre>")
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
                            color: #2c3e50; 
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
                            color: #333;
                        }
                        blockquote {
                            border-left: 3px solid #E15B1E;
                            background-color: #fff3e0;
                            padding: 5px;
                            margin: 5px 0;
                            color: #555;
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
            
            lbl_ver = QLabel("Versión 1.0.5 (Estabilidad Crítica)")
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
            lbl_author.setStyleSheet("font-size: 13px; color: #333;")
            lbl_author.setText("<html>Desarrollado por:<br><b>Francisco Fernández Rodríguez</b></html>")
            layout.addWidget(lbl_author)
            
            lbl_desc = QLabel()
            lbl_desc.setAlignment(Qt.AlignCenter)
            lbl_desc.setStyleSheet("color: #555; font-size: 12px;")
            lbl_desc.setText("<html>Departamento de Oficina Técnica<br><b>ALSI</b></html>")
            layout.addWidget(lbl_desc)

            # Sección de Novedades (Vacía por ahora)
            lbl_updates = QLabel("Notas de Versión:")
            lbl_updates.setStyleSheet("font-weight: bold; margin-top: 10px; color: #333;")
            layout.addWidget(lbl_updates)
            
            browser = QTextBrowser()
            browser.setHtml("""
            <b>v1.0.3:</b><br>
            • Nueva columna de miniaturas (Vista) con carga asíncrona.<br>
            • Búsqueda inteligente que ignora acentos (tildes).<br>
            • Filtro dedicado para "Dark Web J.A" (Javier Alonso).<br>
            • Corrección crítica de Drag & Drop hacia SolidWorks.<br>
            • Estabilidad 64-bits en extracción de iconos.<br><br>
            <b>v1.1.0:</b><br>
            • Compatibilidad oficial con Windows 7.<br>
            • Instalación de Python 3.8.10 embebido.<br>
            • Corrección de dependencias de sistema (api-ms-win-core-path).<br><br>
            <b>v1.0.2:</b><br>
            • Mejoras de rendimiento en hilos secundarios.<br><br>
            <b>v1.0.1:</b><br>
            • Búsqueda automática al cambiar filtros.<br>
            • Mejoras en el instalador para redes locales (UNC).<br><br>
            <b>v1.0.0:</b><br>
            • Lanzamiento oficial.
        """)
            browser.setStyleSheet("background-color: #f9f9f9; border: 1px solid #ddd; border-radius: 4px;")
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



if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Fuente global
    font = QFont("Segoe UI", 9)
    app.setFont(font)
    
    window = BuscadorPiezas()
    window.show()
    sys.exit(app.exec_())
