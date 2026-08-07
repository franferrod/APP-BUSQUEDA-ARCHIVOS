# Changelog - Buscador de Piezas ALSI

## [2.0.3] - 2026-07-16 (Búsqueda en cascada — refinar resultados)
- **Vista previa ampliable**: al arrastrar el divisor del panel derecho la imagen crece de verdad (antes se quedaba fija en un recuadro pequeño).
- **Galería con tamaño XL y zoom libre**: además de S/M/L/XL, un deslizador para el tamaño exacto que quieras (y Ctrl + rueda del ratón sobre la galería). Se recuerda en cada equipo.
- **Botón "Subconjuntos" (búsqueda en profundidad)**: al buscar/refinar por pieza contenida, encuentra también las que están dentro de subconjuntos, a cualquier nivel (ej. MOTOR REM 0.37: 241 conjuntos directos → 627 en total).
- **Buscar conjuntos que lleven una pieza**: el botón Buscar tiene ahora un menú (▾) con "Buscar conjuntos que lo lleven" — escribes una pieza o referencia (ej. AC30-Q6A014) y salen los ENSAMBLAJES que la contienen, respetando todos los filtros (años, cliente, Placa CE…). Sintaxis: ; = que lleven todas · , = cualquiera de ellas.
- **Refinar resultados (búsqueda en cascada)**: sobre los resultados de una búsqueda se pueden apilar niveles de refinado — "En el nombre" o "Que contenga (pieza/ensamblaje)" (ej. cintas A450 → que lleven el MOTOR REM 0.37KW). Cada nivel deja un chip quitable; Esc deshace el último nivel hasta volver a la búsqueda general. Misma sintaxis del buscador (espacio=frase, ;=Y, ,=O) y contador X → Y.
- **Fix "connection pool exhausted"**: más conexiones simultáneas a la base de datos y espera automática en picos (búsqueda + miniaturas + preview a la vez).
- **Fix resultados obsoletos**: al lanzar una búsqueda la rejilla se vacía al instante — ya no se quedan los resultados anteriores visibles durante el "Buscando…" (podían leerse como si fueran la respuesta del filtro nuevo).

## [2.0.2] - 2026-07-13 (Despiece, comparación, miniaturas sin SolidWorks y PDFs)
- **Previsualizador instantáneo**: al clicar una pieza, la imagen sale al momento de la caché en BD y la versión en alta calidad llega en segundo plano — clicar ya no congela la interfaz 1-2 s.
- **Miniaturas de lista/galería por lotes**: el hilo de miniaturas las trae de la BD en bloques de 400 (una consulta por bloque) — cientos de miniaturas en décimas de segundo.
- **"Ensamblajes similares"** (clic derecho en un ensamblaje): encuentra máquinas que comparten un alto % de piezas (ignorando tornillería común) — ideal para localizar diseños parecidos entre proyectos.
- **"Buscar piezas idénticas"** (clic derecho): detecta duplicados — piezas con la misma vista previa embebida aunque tengan otro nombre ("copia exacta" si además pesa lo mismo el archivo).
- **Placas CE al día**: la base de placas CE se actualiza cada tarde desde los Excel de NÚMEROS DE SERIE (2005-hoy); los documentos de años nuevos se detectan solos y un Excel ilegible no rompe nada.
- **La app ya no se congela nunca al buscar**: la consulta corre en segundo plano y los resultados se pintan por tramos — puedes seguir usando la interfaz aunque la búsqueda tarde (Placa CE, 5000 resultados, galería...). Si encadenas búsquedas, siempre gana la última.
- **Galería instantánea**: pintar miles de tarjetas congelaba la app ~10 s; ahora se rellena por tramos reutilizando los iconos ya resueltos (5000 tarjetas en ~0,1 s).
- **Fix "Abrir/Insertar en SolidWorks"**: en algunos equipos daba "startfile: filepath should be string... not bool" — corregido.
- **Miniaturas al instante desde la base de datos**: las miniaturas de la lista y la galería ahora se sirven de la caché en BD sin releer el NAS en cada búsqueda (antes se regeneraban una y otra vez). Búsquedas más rápidas y sin tirones.
- **Fin de los cuelgues al encadenar filtros/botones**: el cambio de miniaturas ya no bloquea la interfaz al hacer búsquedas o tocar filtros seguidos.
- **Barra de título oscura**: la ventana principal y todos los diálogos usan la barra de título en oscuro, a juego con la app (se acabó la franja blanca de Windows).
- **Miniaturas en todos los diálogos**: comparar componentes, ensamblajes similares, piezas similares, duplicados, candidatas a biblioteca, "dónde se usa" y el despiece muestran la miniatura de cada elemento a la izquierda.
- **Miniaturas en equipos SIN SolidWorks**: las miniaturas de piezas, ensamblajes y planos ahora también se ven en ordenadores que no tienen SolidWorks instalado (se sirven desde una caché central en la base de datos, alimentada por la indexación nocturna). De regalo: miniaturas más rápidas para todos.
- **Previsualización de DWG**: las miniaturas y el previsualizador muestran el dibujo embebido en el propio DWG (sin necesidad de AutoCAD), en lugar del icono.
- **Previsualización de STEP/IGES**: miniaturas 3D sombreadas (vista isométrica) generadas automáticamente por la indexación nocturna — visibles en todos los equipos sin ningún programa CAD.
- **Previsualización de PDFs**: el previsualizador y las miniaturas muestran la primera página real del PDF (antes solo el icono de Adobe), sin necesidad de tener Adobe instalado.
- **Indicador "sin plano"**: el previsualizador muestra si la pieza/ensamblaje tiene plano (.slddrw) y PDF con su mismo código, con enlace "abrir" directo — y avisa en ámbar si no tiene documentación. Detecta trabajo pendiente antes de que taller lo eche en falta.
- **Aviso de referencias rotas**: al seleccionar un ensamblaje, el previsualizador muestra cuántos componentes tiene y avisa (⚠) si alguno ya no existe en el índice (pieza borrada o renombrada).
- **"Piezas similares"**: botón en el previsualizador que lista piezas con el mismo material, espesor y procesos de fabricación — para reaprovechar en vez de rediseñar.
- **Botón "Análisis" → "Piezas más reutilizadas"**: ranking de las piezas usadas en más proyectos que NO están en la biblioteca — candidatas a estandarizar, exportable a CSV.
- **Ctrl+C copia el código + nombre sin extensión** ("23018.P166 Pletina sujeción"), listo para pegar en correos o el ERP.
- **"Ver componentes (despiece)"**: clic derecho sobre un ensamblaje muestra su lista de piezas (BOM) al instante — con cliente, proyecto, año y origen de cada componente — sin abrir SolidWorks. Doble clic abre la carpeta de la pieza y botón "Exportar CSV" para llevarlo a Excel. Los componentes con referencia rota o fuera del índice se marcan en gris.
- **"Comparar componentes de los 2 ensamblajes"**: seleccionando dos ensamblajes, el clic derecho ofrece un diff de componentes — qué piezas tiene solo A, solo B y cuáles comparten (ej. qué cambió entre la cinta de 2023 y la de 2025). Exportable a CSV con matriz de presencia.
- **Fix indexado de propiedades SW**: el reindexado automático guardaba en blanco las propiedades con acentos (LÁSER=SÍ, SOLDADURA=SÍ...) por un error de codificación; los filtros de fabricación no devolvían resultados. Corregido y repoblado el histórico.
- **Fix actualizador**: la ventana de actualización ya no se queda abierta indefinidamente si hay otra instancia de la app abierta; fuerza el cierre y continúa.

## [2.0.1] - 2026-07-10 (Dónde se usa una pieza + acceso NAS por nombre)
- **Nueva función "¿En qué ensamblajes se usa?"**: clic derecho sobre cualquier pieza o subensamblaje muestra al instante la lista de ensamblajes que la contienen (cliente, proyecto, año), con doble clic para abrir su carpeta. Especialmente útil para piezas estándar de biblioteca (arandelas, tuercas, rodamientos...).
- **Acceso al NAS por IP o por nombre**: los equipos que solo llegan al Synology por "NASCENTRAL" (y por IP les pedía credenciales) ya pueden abrir archivos, arrastrar a SolidWorks y ver miniaturas — la app detecta el host que funciona en cada equipo.
- **Instalador más robusto**: cierra la app antes de actualizar (evita el "archivo en uso" que dejaba el exe sin actualizar) y abre la app al terminar.
- **Arranque más fluido**: la ventana aparece al instante y los filtros se cargan justo después.
- **Aviso de actualización**: cuando hay una versión nueva en la carpeta de red, la app lo muestra con un botón "Actualizar ahora".

## [2.0.0] - 2026-07-08 (Rediseño visual completo - Marca ALSI 2025)
- **Nuevo filtro "Placa CE"**: botón junto al buscador que restringe los resultados a máquinas con placa CE registrada (ej. buscar "CINTA A450" muestra solo las cintas reales, no todas las patas y travesaños con nombre parecido).
- **Búsqueda por nº de placa**: escribir un número de placa (ej. "26-0006") en el buscador encuentra directamente su ensamblaje, plano y PDF.
- **Nueva tabla placas_ce en PostgreSQL**: se alimenta automáticamente al Reindexar NAS leyendo los Excel de NÚMEROS DE SERIE (todos los años, formato .xls y .xlsx).
- **Tema oscuro CAD**: Nueva interfaz oscura de marca (naranja #E66C32) aplicada con hoja de estilo QSS global.
- **Tipografía de marca**: AG ALSI en títulos principales, Nizzoli Alt en títulos de sección y Poppins como fuente de toda la interfaz.
- **Iconos SVG**: Sustituidos todos los emojis por iconografía vectorial monocroma recoloreable.
- **Vista Galería**: Nueva vista de tarjetas con miniaturas grandes (tamaños S/M/L), conmutable con la vista Lista y con el mismo arrastrar-a-SolidWorks.
- **Vista Lista mejorada**: Miniaturas de 56px, columnas de fabricación compactas (L·T·F·S·P·M con ✓), columna Tipo como píldora coloreada y densidad Cómoda/Compacta.
- **Columnas configurables**: Botón "Columnas" para mostrar/ocultar columnas; la configuración, la vista y la densidad se recuerdan entre sesiones.
- **Diálogos renovados**: Reindexar NAS (orígenes como tarjetas y años como chips), Guía rápida con índice lateral y Acerca de con cabecera de marca.
- **Fix Reindexar**: Corregido un error por el que el diálogo de indexación no lanzaba la indexación de ningún origen (etiquetas vs claves internas).
- **Placeholder de miniaturas**: Badge de extensión coloreado (PRT/ASM/DRW/PDF...) mientras carga la miniatura real.
- **Fix Previsualizador**: La miniatura ya no se desplaza sobre el texto ni deja el "fantasma" de la selección anterior; se ajusta al recuadro en cualquier resolución/escalado de pantalla.
- **Origen legible**: En la tabla de resultados el origen se muestra como "Proyectos", "Biblioteca 3D" o "ALSI Estándar" (sin guiones bajos).

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
