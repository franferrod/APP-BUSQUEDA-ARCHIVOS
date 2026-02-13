---
description: Guía de desarrollo y mantenimiento para el proyecto "Buscador de Piezas ALSI"
---

# Buscador de Piezas ALSI - Skill de Desarrollo

Esta Skill contiene todo el conocimiento necesario para mantener y extender la aplicación "Buscador de Piezas ALSI".

## Arquitectura del Proyecto

El proyecto sigue una arquitectura **MVC (Model-View-Controller)** simplificada usando PyQt5.

### Estructura de Archivos
- `buscar_piezas.py`: **Vista (View)** y controlador principal de UI. Contiene `QMainWindow`, `QTableWidget` y la lógica de presentación.
- `models.py`: **Modelo (Model)**. Gestiona la base de datos SQLite (`IndexManager`) y las consultas.
- `controllers.py`: **Controlador (Controller)**. Gestiona la lógica de negocio, búsqueda (`SearchController`) e indexación en segundo hilo (`IndexadorThread`).
- `generar_icono.py`: Script auxiliar para generar `ALSI_BUSCADOR.ico` con múltiples resoluciones (16x16 a 256x256).

### Base de Datos (SQLite)
La base de datos se encuentra en `~/.alsi_busqueda/index.db`.
Tabla principal: `archivos`

| Columna | Descripción |
| :--- | :--- |
| `id` | Identificador único (INTEGER PK) |
| `nombre` | Nombre del archivo (TEXT) |
| `ruta` | Ruta absoluta del archivo (TEXT UNIQUE) |
| `tipo` | Extensión del archivo (TEXT) |
| `tamano` | Tamaño en bytes (INTEGER) |
| `fecha_mod` | Timestamp de modificación (REAL) |
| `compañero` | Nombre de la carpeta raíz del compañero (TEXT) - Ej: "EMRAH", "DANI" |
| `año` | Año extraído de la ruta (TEXT) - Ej: "2024" |
| `cliente` | Cliente extraído de la ruta (TEXT) |
| `proyecto` | Nombre completo del proyecto (TEXT) |
| `cod_proy` | Código de proyecto extraído con Regex (TEXT) - Ej: "P-123" |
| `nom_proy` | Nombre limpio del proyecto (TEXT) |
| `cod_ord` | Código de orden extraído con Regex (TEXT) - Ej: "OT-456" |
| `nom_ord` | Nombre limpio de la orden (TEXT) |

## Convenciones de Código

- **UI Framework**: PyQt5.
- **Estilo**: Tema oscuro/profesional con colores corporativos ALSI:
    - Naranja: `#E15B1E`
    - Gris: `#78858B`
- **Logging**: Usar `logging` estándar. Logs en `~/.alsi_busqueda/app.log`.
- **Manejo de Errores**: Bloques `try-except` rodeando operaciones críticas de archivo/red. `exception_hook` global para evitar cierres inesperados.
- **Rutas**: Usar `pathlib` o `os.path`. Rutas de red (`\\SERVER\Share`) deben manejarse con cuidado.

## Funcionalidades Clave

1.  **Indexación**: Recorre recursivamente las rutas de red definidas en `RUTAS_RED`. Ignora carpetas del sistema y archivos temporales (`~$`).
2.  **Búsqueda Rápida**: Búsqueda incremental (`textChanged`) con `LIKE %query%`.
3.  **Filtros en Cascada**: Cliente -> Proyecto -> Orden. Al seleccionar un nivel superior, los inferiores se filtran.
4.  **Miniaturas**: 
    - **SolidWorks**: Usa `olefile` para leer el stream `PreviewPNG` directo del archivo binario.
    - **Otros**: Usa Windows Shell API (`IShellItemImageFactory`) para PDF, DWG, etc.
6.  **Acciones**: Abrir carpeta, Copiar ruta, Drag & Drop a SolidWorks.

## Comandos Útiles

- **Compilar**: Ejecutar `compilar.bat`.
- **Generar Icono**: `python generar_icono.py`.
- **Instalar Deps**: `pip install -r requirements.txt`.
