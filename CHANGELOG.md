# Changelog - Buscador de Piezas ALSI

## [1.0.5] - 2026-03-13 (Estabilidad Crítica)
**Esta versión corrige múltiples causas de cierre inesperado de la aplicación**, reportadas en varios equipos de la oficina técnica.

### 🐛 Correcciones Críticas de Estabilidad
- **Fix Hilo de Miniaturas**: El hilo `ThumbnailWorker` usaba variables sin inicializar (`procesados`, `tiempo_inicio`) y emitía una señal inexistente (`finished`). Esto causaba un cierre silencioso en **cada búsqueda que devolvía resultados**. Corregido completamente.
- **Fix `self.tab_resultados`**: El método `on_sw_file_extracted` intentaba acceder a un atributo que no existe (`self.tab_resultados`), causando crash al seleccionar archivos SolidWorks sin propiedades extraídas.
- **Fix COM en Miniaturas de Red**: Se eliminaron llamadas redundantes a `CoInitialize/CoUninitialize` dentro del hilo de miniaturas, que podían causar `AccessViolation` esporádico al cargar thumbnails desde rutas de red.
- **Fix Métodos Duplicados**: Los métodos `toggle_checkboxes`, `get_selected_items`, `add_toggle_buttons` y `closeEvent` estaban definidos dos veces en la clase principal. El segundo `closeEvent` sobreescribía al correcto y provocaba que las preferencias (compañeros, años, filtros) no se guardaran al cerrar.
- **Fix Guard `sw_thread`**: El acceso a `sw_thread.isRunning()` no manejaba `RuntimeError`, causando crash ocasional al pulsar "Extraer Props SW".
- **Fix `import time`**: Módulo `time` faltaba en la cabecera del archivo principal.

## [1.0.3] - 2026-02-26 (Thumbnails y Sin Acentos)
- **Búsqueda Inteligente**: Las búsquedas ahora ignoran los acentos/tildes, tratando (por ejemplo) "telescópico" y "telescopico" como equivalentes.
- **Columna de Miniaturas (Asíncrona)**: Se ha incorporado una nueva columna "Vista" al inicio de la tabla.
- **Estabilidad 64-bits**: Corregido un error de desbordamiento (`OverflowError`) al manejar punteros de Windows en hilos secundarios, asegurando que las miniaturas se carguen correctamente en todos los sistemas.
- **Corrección de Índices**: Reparados los accesos directos de "Abrir Carpeta" y "Copiar Ruta" que apuntaban a columnas incorrectas tras el rediseño.
- **Filtro Dark Web J.A**: Nuevo filtro independiente para la carpeta `\\Ofitec-5\javier alonso`, que funciona igual que Siddex y Estándar (ignora filtros de compañeros, años, etc.).
- **Fix Arrastrar y Soltar**: Corregido un error crítico (`NoneType`) que impedía arrastrar archivos a SolidWorks cuando se iniciaba el arrastre desde la columna de miniatura.

## [1.1.0] - 2026-02-20 (Win7 Compatibility)
Versión especial para asegurar el funcionamiento en equipos antiguos con Windows 7 (Rubén Edition).

### 🛠 Mejoras de Compatibilidad
- **Python 3.8.10**: Downgrade controlado del motor de Python para soporte oficial de Windows 7.
- **Fix DLLs**: Integración de `api-ms-win-core-path-l1-1-0.dll` para resolver errores de arranque.
- **Entorno Embebido**: Preparación de un entorno Python autocontenido para evitar conflictos de sistema.
- **Fix Onefile (2026-02-24)**: Recompilación en modo onefile para evitar `WinError 127` causado por `os.add_dll_directory()` (no disponible en Win7). Elimina la necesidad de la carpeta `pywin32_system32`.
- **INSTALAR_LOCAL.bat**: Añadido instalador local específico para v1.1.0.

## [1.0.0] - 2026-02-18 (Lanzamiento Oficial)
¡Primera versión oficial de producción! Esta entrega marca el fin de la fase de desarrollo y el inicio del despliegue oficial en la Oficina Técnica.

### 🌟 Novedades V1.0.0 (Final)
- **Ayuda e Info**: Botones premium `❓` y `ℹ️` reubicados en la barra inferior para mayor comodidad.
- **Identidad Corporativa**: Inclusión de logotipo, créditos del desarrollador y manuales integrados.
- **Rendimiento Pulido**: Navegación fluida por teclado y mouse con carga de recursos diferida.
- **Estabilidad Total**: Resolución de errores de rutas de red y normalización de accesos UNC.

### 🛠 Características Consolidadas
- **Búsqueda Avanzada**: Filtros en cascada por Compañero, Año, Cliente y Proyecto.
- **Filtros de Tipo**: Búsqueda por extensión (.sldprt, .pdf, .dwg, etc.).
- **Previsualización**: Panel lateral inteligente con metadatos y miniaturas automáticas.
- **Indexación Selectiva**: Actualización rápida de bases de datos por compañero o año.

---

## Historial de Desarrollo (Beta)

### [Beta 1.3.25] - 2026-02-17
- Optimización de UI con `QTimer` para evitar bloqueos en navegación rápida.

### [Beta 1.3.24] - 2026-02-17
- Limpieza de código y optimización de base de datos.
