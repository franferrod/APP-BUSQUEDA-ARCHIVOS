# Changelog - Buscador de Piezas ALSI

## [1.2.1] - 2026-02-10
### Añadido
- **Drag & Drop**: Ahora puedes arrastrar archivos directamente desde la tabla a SolidWorks para abrirlos.
- **Panel de Previsualización**: Nuevo panel derecho con información detallada e iconos por tipo de archivo.
- **Indexación Selectiva**: Diálogo modal para elegir qué compañeros/carpetas actualizar.
- **Botón Cancelar**: Permite detener la indexación en curso de forma segura.
- **Filtro por Extensión**: Reemplazo del filtro de carpetas por uno más útil basado en tipo de archivo (.sldprt, .dwg, .pdf, etc.).
- **Acción Proactiva**: Añadida opción "Copiar Nombre" al menú contextual.

### Cambiado
- Ruta de PACO actualizada a formato UNC (`\\OFITEC-4\`) para acceso universal.
- El divisor central (Splitter) ahora recuerda su posición entre sesiones.

## [1.2.0] - 2026-02-05

### Arquitectura
- **Refactorización MVC**: Separación de lógica de datos (`models.py`), controladores (`controllers.py`) e interfaz (`buscar_piezas.py`).
- Creación de `SearchController` para gestión centralizada de búsquedas y preferencias.

### UI/UX
- Layout rediseñado: panel lateral fijo (190px) para filtros + tabla responsive con expansión dinámica.
- Tooltips descriptivos en todos los controles interactivos.
- Cursor tipo "mano" (PointingHandCursor) en botones clickables.
- Márgenes y espaciados estandarizados a 10px/8px.

### Rendimiento
- Índices compuestos SQLite: `(compañero, año)` y `(nombre_archivo, compañero)`.
- Extensiones de archivo ampliadas: .step, .stp, .iges, .igs.

### Seguridad
- Migración completa a prepared statements (parámetros `?`) en todas las consultas SQL.
- Eliminación de f-strings con datos de usuario en queries.

### Testing
- Suite PyTest con 19 tests: búsqueda, scoring, filtros, SQL injection, preferencias.
- 100% tests pasando.

### Documentación
- Guía de usuario en español (`docs/Guia_Usuario.md`).
- ADR técnico: justificación de SQLite (`docs/ADR-001-SQLite.md`).

## [1.1.0] - 2026-02-09

### Añadido
- Búsqueda multi-keyword con scoring inteligente (separar por comas).
- Filtros multi-selección con checkboxes (Compañeros, Años).
- 3 nuevas rutas: JAVI GARCÍA, JAVI ALONSO, DAVID BARÓN.
- Límite de 2000 resultados con advertencia visual.
- Persistencia de estado de checkboxes en SQLite.

## [1.0.0] - 2026-01-26

### Inicial
- Buscador funcional con búsqueda por nombre de archivo.
- Indexación de 7 rutas de red.
- Filtros por compañero, año y tipo de carpeta.
- Acciones: Abrir carpeta, Copiar ruta.
