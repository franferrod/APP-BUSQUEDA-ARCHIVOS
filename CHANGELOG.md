# Changelog - Buscador de Piezas ALSI

## [1.1.0] - 2026-07-03 (Rediseño Completo UI/UX y Fix Logo)
- **Fix Logo Definitivo**: Solucionado el problema visual ("franja negra") del logo ALSI al arrancar, procesando la imagen con PIL (LANCZOS) sobre fondo blanco puro, eliminando los píxeles de anti-aliasing con transparencia alfa.
- **Rediseño Panel Propiedades SW**: Cambio completo del paradigma de filtrado en el panel derecho. Sustitución de `QComboBox` por `QListWidget` para permitir selección múltiple en Material, Tratamiento, Cierre y Espesor.
- **SQL IN**: Actualización del motor de búsqueda en PostgreSQL para soportar `IN (...)` y lógica OR/LIKE avanzada, permitiendo búsquedas combinadas (ej. buscar piezas que sean Zincadas O Cromadas O Pintadas).
- **Tratamientos Oficiales**: Sincronizado dinámicamente con la plantilla oficial `template_PZ.prtprp` del NAS (ZINCADO, RALs, GRANALLADO, etc.).
- **Filtro de Espesores Inteligente**: Nuevo filtro para "Espesores" (1mm-20mm). El motor filtra automáticamente entre los valores de la base de datos (que pueden ser números simples "3" o fórmulas de SolidWorks).
- **Limpieza de Código**: Eliminación de scripts de prueba, limpieza del directorio raíz y actualización de `.gitignore` para un repositorio más limpio.

## [1.0.8] - 2026-07-01 (Seguridad & UI/UX Extension)
- **Seguridad**: Extracción de credenciales de PostgreSQL a archivo externo `config.ini`. La app y los scripts leen desde el archivo para mayor seguridad y adherencia a buenas prácticas.
- **UI/UX Enterprise**: Implementación completa de atajos de teclado, exportación selectiva a Excel (CSV), panel master-detail colapsable, vistas dinámicas (Cómoda vs Compacta), notificaciones flotantes (Toasts) y corrección del filtrado combinado de propiedades booleanas.

## [1.0.7] - 2026-07-01 (Migración NAS Nuevo y Filtros de Propiedades)
- **Base de Datos Compartida**: Migración de la base de datos local SQLite a PostgreSQL centralizada (`192.168.1.10:5433`). Todos los usuarios comparten la misma indexación en tiempo real.
- **Indexación Automática**: Nuevo script de reindexación diaria (a las 15:45h) que se lanza de forma desatendida, actualizando archivos recientes de proyectos.
- **Nuevas Propiedades de Fabricación y Bandas**: El buscador ahora extrae y permite filtrar por `TIPO DE CIERRE`, `FILO GUIADO`, `ONDA`, `CANGILÓN`, `RUNER`, `MONTAJE`, `LÁSER`, `TORNO`, `FRESA`, `SOLDADURA` y `PINTURA`.
- **Panel de Filtros de Propiedades**: Añadido un nuevo panel lateral derecho interactivo para filtrar por todas las propiedades de SolidWorks de forma independiente a la estructura jerárquica de la izquierda.
- **NAS Centralizado**: Toda la indexación apunta al NAS `\\192.168.1.10\Oficina Tecnica\...`, eliminando dependencia de carpetas por compañero (`\\OFITEC-*`, `Z:\`).
- **4 Orígenes**: `PROYECTOS`, `BIBLIOTECA_3D`, `ALSI_ESTANDAR`. `ALSI_LEGENDS` se ha eliminado al haberse integrado en los proyectos del NAS nuevo.
- **UI Simplificada**: Columna "Descripción" eliminada para limpiar la vista. Botón único "Reindexar NAS".
## [1.0.5] - 2026-04-08 (UI/UX Global Remaster)
- **UI Pro**: Modernización visual completa de la interfaz inspirada en macOS/Fluent Design con base en el color corporativo.
- **Oculto bajo el capó**: Aplicación de estilos mediante QSS global optimizado e inyectado en el ejecutable, eliminando CSS en línea y bordes "feos" heredados.
- **Micro-interacciones**: Nuevos efectos *Hover*, Scrollbars compactos semi-transparentes, y alternancia de color de fila dinámico en tablas sin grid-lines bruscas.
- **UX Pulida**: Reestructurado el panel de filtros izquierdo: ahora muestra obligatoriamente varios compañeros, años, y carpetas al mismo tiempo, sin aplastarse ni ocultar los selectores. Se resolvió el fallo gráfico del texto cruzado en el grupo *Filtros Avanzados*.

## [1.0.4] - 2026-04-07 (Fix Miniaturas y Ordenación)
- **Fix Miniaturas**: Corregido un error donde la imagen del panel de previsualización no correspondía con la miniatura de la tabla al ordenar por columnas.
- **Causa**: Las miniaturas usaban `setCellWidget` (QLabel) que no se mueve al ordenar la tabla. Ahora usan `QTableWidgetItem` con `DecorationRole`, que se reordena correctamente con los datos.
- **Mejora Preview**: La previsualización ahora muestra inmediatamente la miniatura cacheada al seleccionar una fila, sin esperar al timer de carga diferida.

## [1.0.3] - 2026-02-26 (Thumbnails y Sin Acentos)
- **Búsqueda Inteligente**: Las búsquedas ahora ignoran los acentos/tildes, tratando (por ejemplo) "telescópico" y "telescopico" como equivalentes.
- **Columna de Miniaturas (Asíncrona)**: Se ha incorporado una nueva columna "Vista" al inicio de la tabla.
- **Estabilidad 64-bits**: Corregido un error de desbordamiento (`OverflowError`) al manejar punteros de Windows en hilos secundarios, asegurando que las miniaturas se carguen correctamente en todos los sistemas.
- **Corrección de Índices**: Reparados los accesos directos de "Abrir Carpeta" y "Copiar Ruta" que apuntaban a columnas incorrectas tras el rediseño.
- **Filtro Dark Web J.A**: Nuevo filtro independiente para la carpeta `\\Ofitec-5\javier alonso`, que funciona igual que Siddex y Estándar (ignora filtros de compañeros, años, etc.).

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
