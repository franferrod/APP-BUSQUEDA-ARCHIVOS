# Contexto del Proyecto: Buscador de Piezas ALSI

> **PROPÓSITO**: Este documento resume todo lo que necesitas saber para trabajar en este proyecto sin romper nada. Léelo COMPLETO antes de hacer cualquier cambio.

---

## 1. ¿Qué es este proyecto?

Una **aplicación de escritorio** (Windows) para la Oficina Técnica de ALSI que permite buscar archivos de ingeniería (piezas SolidWorks, planos DWG, PDFs, etc.) distribuidos en **carpetas de red compartidas** de varios compañeros de trabajo.

- **Lenguaje**: Python 3.8+ (compatibilidad con Windows 7 requerida)
- **UI Framework**: PyQt5
- **Base de datos**: SQLite local (`~/.alsi_busqueda/index.db`)
- **Distribución**: Ejecutable `.exe` compilado con PyInstaller, desplegado a una carpeta de red compartida

---

## 2. Arquitectura (MVC simplificado)

El proyecto tiene **3 archivos Python principales**. Es CRÍTICO entender qué hace cada uno:

| Archivo | Rol | Descripción |
|---|---|---|
| `buscar_piezas.py` | **Vista (View)** | QMainWindow, toda la UI, tabla de resultados, panel de preview, menús. (~163KB, es el más grande) |
| `controllers.py` | **Controlador** | Lógica de negocio: SearchController, IndexadorThread (hilo secundario para indexar), lógica de búsqueda |
| `models.py` | **Modelo** | IndexManager: gestión de la base de datos SQLite, queries, creación de tablas |

### Otros archivos importantes:
- `generar_icono.py` — Genera el `.ico` con múltiples resoluciones
- `compilar.bat` — Compila el `.exe` con PyInstaller y despliega a la red
- `DESPLEGAR_VERSION.bat` — Despliega una versión específica de `releases/` a la red
- `INSTALAR_LOCAL.bat` — Lo ejecutan los usuarios finales desde la red para instalarse la app localmente
- `CREAR_PUNTO_DE_RESTAURACION.bat` / `hacer_backup.py` — Crea snapshots de los archivos fuente en `BACKUPS/`
- `CHANGELOG.md` — Historial de cambios por versión
- `BuscadorPiezas.spec` — Configuración de PyInstaller

---

## 3. Control de Versiones (Git)

El proyecto usa **Git** como sistema de control de versiones.

### Ramas
- Se trabaja principalmente en `main` (o la rama activa).
- Los commits siguen un formato descriptivo con prefijos: `feat()`, `fix()`, `V1.0.X:`

### Historial de versiones principales (de más reciente a más antigua):
```
v1.0.5  - UI/UX Global Remaster (Fluent Design, hover effects, scrollbars compactos)
v1.0.4  - Fix miniaturas desincronizadas al ordenar
v1.0.3  - Thumbnails asíncronos, búsqueda sin acentos, filtro Dark Web J.A.
v1.1.0  - Rama especial de compatibilidad Windows 7
v1.0.0  - Lanzamiento oficial de producción
```

### Qué está en .gitignore (NO se versiona):
```
__pycache__/        # Cache de Python
build/              # Artefactos de compilación
dist/               # El .exe compilado
*.spec              # Config de PyInstaller (nota: BuscadorPiezas.spec SÍ está trackeado, se añadió antes del .gitignore)
BACKUPS/            # Snapshots manuales
releases/           # Versiones empaquetadas para despliegue
index.db / app.log  # DB y logs locales
```

### Archivos que SÍ se versionan (los críticos):
```
buscar_piezas.py
controllers.py
models.py
generar_icono.py
hacer_backup.py
compilar.bat
DESPLEGAR_VERSION.bat
INSTALAR_LOCAL.bat
CREAR_PUNTO_DE_RESTAURACION.bat
CHANGELOG.md
README.txt
requirements.txt
.gitignore
Imágenes de marca (ALSI_*.png, ALSI_*.ico)
docs/  (manuales y ADRs)
```

---

## 4. Flujo de Compilación y Despliegue

### Paso a paso:

```
1. DESARROLLO
   └── Editar buscar_piezas.py, controllers.py, models.py
   └── Probar localmente con: python buscar_piezas.py

2. SNAPSHOT (opcional pero recomendado)
   └── Ejecutar CREAR_PUNTO_DE_RESTAURACION.bat
   └── Esto copia los archivos fuente a BACKUPS/SNAPSHOT_vX.X.X_timestamp/

3. COMMIT en Git
   └── git add -A && git commit -m "descripción del cambio"

4. COMPILAR
   └── Ejecutar compilar.bat
   └── Esto hace:
       a) pip install -r requirements.txt
       b) python generar_icono.py
       c) PyInstaller genera el .exe en dist/
       d) Copia recursos (imágenes, .bat, CHANGELOG) a dist/
       e) Despliega automáticamente dist/* → Z:\ALSI INTERCAMBIO\...\APP BÚSQUEDA ARCHIVOS

5. ARCHIVAR LA RELEASE
   └── Copiar TODO el contenido de dist/ a releases/v1.0.X/
   └── Esta carpeta queda como ARCHIVO HISTÓRICO de esa versión
   └── Estructura de releases/:
       releases/
       ├── v1.0.1/
       ├── v1.0.2/
       ├── v1.0.3/
       ├── v1.0.3_repaired/
       ├── v1.0.4/
       ├── v1.0.5/          ← versión actual
       └── v1.1.0/          ← rama especial Win7

6. DESPLIEGUE A RED (alternativo, por versión)
   └── Ejecutar: DESPLEGAR_VERSION.bat v1.0.X
   └── Esto copia releases/v1.0.X/* → \\192.168.1.229\...\APP BÚSQUEDA ARCHIVOS

6. INSTALACIÓN POR USUARIO FINAL
   └── El usuario navega a la carpeta de red
   └── Ejecuta INSTALAR_LOCAL.bat
   └── Esto copia el .exe a %LOCALAPPDATA%\ALSI_Buscador y crea acceso directo
```

### Ruta de despliegue en red:
```
\\192.168.1.229\Volume_1\ALSI INTERCAMBIO\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS
```
(También mapeada como unidad `Z:` en algunos equipos)

### 4.1. Flujo al empezar una NUEVA versión

Cuando se va a desarrollar una nueva versión (ej: pasar de v1.0.5 a v1.0.6), hay que actualizar el número de versión en **4 puntos del código**:

#### PUNTO 1: `compilar.bat` — Línea 3 (título del script)
```batch
echo COMPILANDO BUSCADOR DE PIEZAS (ALSI) - V1.0.6   ← cambiar aquí
```

#### PUNTO 2: `buscar_piezas.py` — Línea ~1485 (función `check_for_updates`)
Esta función compara la versión local con la versión desplegada en red (via `version.txt`):
```python
local_version = "v1.0.6"   ← cambiar aquí
```

#### PUNTO 3: `buscar_piezas.py` — Línea ~3521 (función `mostrar_info`, diálogo "Acerca de")
```python
lbl_ver = QLabel("Versión 1.0.6 (Descripción breve del cambio)")   ← cambiar aquí
```

#### PUNTO 4: `CHANGELOG.md` — Añadir nueva entrada al principio
```markdown
## [1.0.6] - FECHA (Título descriptivo)
- **Feature**: Descripción del cambio principal
- **Fix**: Correcciones importantes
```

### 4.2. Pestaña "Acerca de" (botón ℹ️)

La app tiene un botón **ℹ️** en el footer que abre un diálogo `mostrar_info()` (línea ~3505 de `buscar_piezas.py`) que muestra:

1. **Título**: "Buscador de Piezas ALSI"
2. **Versión**: String hardcodeado (ej: "Versión 1.0.5 (UI/UX Global Remaster)")
3. **Autor**: Francisco Fernández Rodríguez
4. **Notas de versión**: Lee dinámicamente `CHANGELOG.md` con `_obtener_changelog_html()` (línea ~3578) y lo renderiza como HTML en un `QTextBrowser`

> **IMPORTANTE**: Las notas de versión se leen del archivo `CHANGELOG.md` que se incluye en el paquete de distribución (se copia a `dist/` en `compilar.bat`). Así que actualizar `CHANGELOG.md` actualiza automáticamente las notas que ven los usuarios.

### 4.3. Sistema de auto-actualización

La función `check_for_updates()` (línea ~1480) se ejecuta 2 segundos después del arranque y:
1. Lee `version.txt` de la carpeta de red (`\\...\APP BÚSQUEDA ARCHIVOS\version.txt`)
2. Compara con `local_version` hardcodeado en el código
3. Si son distintas, muestra un **banner verde** en la UI: "🚀 ¡Nueva versión X disponible!"
4. El `version.txt` se genera automáticamente por `DESPLEGAR_VERSION.bat` al desplegar

### 4.4. Contenido de cada carpeta en `releases/`

Cada carpeta de release contiene una **copia completa** de todo lo necesario para instalar:
```
releases/v1.0.5/
├── BuscadorPiezas.exe        ← El ejecutable compilado
├── INSTALAR_LOCAL.bat         ← Instalador para usuarios
├── ALSI_BUSCADOR.ico          ← Icono
├── ALSI_IMAGOTIPO_naranja.png ← Logo
├── ALSI_ISOTIPO_naranja.png   ← Logo isotipo
├── CHANGELOG.md               ← Notas de versión
├── compilar.bat               ← Copia del script de compilación
├── version.txt                ← Archivo con el string "v1.0.5"
├── buscar_piezas.py           ← Copia del fuente (backup)
├── controllers.py             ← Copia del fuente (backup)
└── models.py                  ← Copia del fuente (backup)
```

---

## 5. ⚠️ REGLAS CRÍTICAS PARA NO ROMPER NADA

> [!CAUTION]
> Estas reglas son OBLIGATORIAS. Incumplirlas puede dejar la aplicación inutilizable para toda la oficina.

### 5.1. Nunca modificar archivos directamente en la carpeta de red
La carpeta de red (`\\192.168.1.229\...`) es **solo destino de despliegue**. Los cambios se hacen en el código fuente local y se despliegan con los scripts.

### 5.2. Hacer snapshot ANTES de cambios grandes
Ejecutar `CREAR_PUNTO_DE_RESTAURACION.bat` antes de modificaciones importantes. Esto crea una copia en `BACKUPS/` con timestamp.

### 5.3. Respetar la separación MVC
- **NO** meter lógica de base de datos en `buscar_piezas.py` (es la Vista)
- **NO** meter código de UI en `models.py` o `controllers.py`
- Los imports circulares romperán la aplicación

### 5.4. Cuidado con los índices de columna de la tabla
La tabla (`QTableWidget`) tiene columnas con índices hardcodeados. Si reordenas o añades columnas, hay que actualizar TODOS los accesos por índice en todo el código. Esto ha causado bugs antes (ver v1.0.3, v1.0.4, v1.0.5 en CHANGELOG).

### 5.5. Compatibilidad con Windows 7
- No usar f-strings con `=` (debugging): `f"{var=}"` → usar `f"var={var}"`
- No usar `os.add_dll_directory()` (no existe en Win7)
- No usar `walrus operator` (`:=`)
- PyInstaller debe compilar en modo `--onefile`

### 5.6. Rutas de red (UNC)
- Las rutas de red usan formato UNC: `\\SERVIDOR\recurso\...`
- Siempre manejar con `try-except` porque la red puede estar caída
- Usar `pushd` en scripts .bat para soporte UNC (ver `INSTALAR_LOCAL.bat`)

### 5.7. Hilos y UI
- La indexación corre en un `QThread` separado (`IndexadorThread`)
- **NUNCA** acceder a widgets de PyQt5 desde un hilo secundario
- Usar señales (`pyqtSignal`) para comunicar resultados del hilo a la UI

### 5.8. Compilación
- El archivo `.spec` de PyInstaller (`BuscadorPiezas.spec`) define la configuración de compilación
- No cambiar `--onefile` porque rompe compatibilidad con Win7
- Actualizar la versión en `compilar.bat` cuando se haga una release nueva

---

## 6. Base de Datos

SQLite local en `~/.alsi_busqueda/index.db`. Tabla principal `archivos`:

```sql
CREATE TABLE archivos (
    id INTEGER PRIMARY KEY,
    nombre TEXT,           -- Nombre del archivo
    ruta TEXT UNIQUE,      -- Ruta absoluta (índice único)
    tipo TEXT,             -- Extensión (.sldprt, .pdf, etc.)
    tamano INTEGER,        -- Bytes
    fecha_mod REAL,        -- Timestamp de modificación
    compañero TEXT,        -- Carpeta raíz del compañero (ej: "EMRAH")
    año TEXT,              -- Extraído de la ruta (ej: "2024")
    cliente TEXT,          -- Extraído de la ruta
    proyecto TEXT,         -- Nombre completo del proyecto
    cod_proy TEXT,         -- Código de proyecto regex (ej: "P-123")
    nom_proy TEXT,         -- Nombre limpio del proyecto
    cod_ord TEXT,          -- Código de orden regex (ej: "OT-456")
    nom_ord TEXT           -- Nombre limpio de la orden
);
```

---

## 7. Dependencias

```
# requirements.txt
PyQt5
olefile       # Para leer miniaturas de archivos SolidWorks
pywin32       # API de Windows para Shell thumbnails
```

---

## 8. Colores corporativos y estilo

- **Naranja ALSI**: `#E15B1E`
- **Gris ALSI**: `#78858B`
- **Tema**: Oscuro/profesional, inspirado en macOS/Fluent Design
- **Estilizado con**: QSS (Qt Style Sheets) dentro de `buscar_piezas.py`

---

## 9. Estructura de carpetas del proyecto

```
BÚSQUEDA PIEZAS/
├── .git/                    # Repositorio Git
├── .gitignore
├── .agent/skills/           # Skills de IA (no tocar)
├── buscar_piezas.py         # VISTA - UI principal (~163KB)
├── controllers.py           # CONTROLADOR - lógica de negocio
├── models.py                # MODELO - base de datos
├── generar_icono.py         # Generador de iconos
├── hacer_backup.py          # Script de snapshots
├── compilar.bat             # Compilar + desplegar
├── DESPLEGAR_VERSION.bat    # Desplegar versión específica
├── INSTALAR_LOCAL.bat       # Instalador para usuarios finales
├── CREAR_PUNTO_DE_RESTAURACION.bat
├── BuscadorPiezas.spec      # Config PyInstaller
├── requirements.txt
├── CHANGELOG.md
├── README.txt
├── ALSI_BUSCADOR.ico        # Icono de la app
├── ALSI_IMAGOTIPO_naranja.png
├── ALSI_ISOTIPO_naranja.png
├── docs/
│   ├── ADR-001-SQLite.md    # Decisión arquitectural
│   ├── GUIA_RAPIDA.md
│   └── Manual_Buscador_Piezas.md
├── BACKUPS/                 # Snapshots manuales (no en Git)
├── releases/                # Versiones para despliegue (no en Git)
├── build/                   # Temporal de PyInstaller (no en Git)
└── dist/                    # .exe compilado (no en Git)
```

---

## 10. Resumen de rutas de red indexadas

La app indexa archivos de estas rutas de red (definidas como `RUTAS_RED` en el código):
- Carpetas de compañeros de la oficina técnica (EMRAH, DANI, PACO, RUBÉN, JAVI GARCÍA, JAVI ALONSO, DAVID BARÓN, etc.)
- Biblioteca SIDDEX
- ALSI ESTÁNDAR

Cada ruta se procesa recursivamente, ignorando carpetas del sistema y archivos temporales (`~$`).
