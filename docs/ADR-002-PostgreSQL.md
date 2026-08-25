# ADR-002: PostgreSQL como índice compartido

## Estado

Aceptado en **v1.0.8** (julio de 2026) · Vigente

Sustituye a [ADR-001](ADR-001-SQLite.md).

## Contexto

La aplicación deja de ser una herramienta personal y pasa a usarla toda la oficina técnica (~10 personas). Eso rompe los tres supuestos sobre los que se eligió SQLite:

- El índice tiene que ser **el mismo para todos** y estar siempre al día, no una copia por equipo.
- Un proceso nocturno **escribe** mientras la gente **lee** durante el día.
- El volumen ya no son decenas de miles de archivos, sino **más de medio millón**.

Un SQLite en la carpeta de red no vale: su bloqueo depende de que el sistema de archivos respete `fcntl`, y sobre SMB eso ni está garantizado ni es fiable. Dos escrituras concurrentes acaban en corrupción.

## Decisión

**PostgreSQL en el NAS Synology** (`192.168.1.10:5433`, base `ALSI`, esquema `buscador`), en Docker, con acceso desde la app vía `psycopg2` y un `ThreadedConnectionPool`.

Consecuencias de diseño que se derivan de ahí y conviene no re-discutir:

- **Las credenciales no van en el código.** Salen del entorno (`ALSI_PG_*`) o de un `config.ini` que está en `.gitignore` (v2.2.0).
- **Búsqueda indexada con `pg_trgm`.** `unaccent()` es `STABLE` y no se puede indexar, así que hay una función propia `buscador.sin_tildes()` marcada `IMMUTABLE` y un índice GIN sobre `UPPER(buscador.sin_tildes(nombre_archivo))`. Medido: de 4× a 172× más rápido que el `LIKE` anterior, con resultados idénticos.
- **Las miniaturas se guardan en la base** (`buscador.miniaturas`, máximo 256 px). Así funcionan en los equipos que **no tienen SolidWorks instalado**, y no hay que releer el NAS en cada búsqueda.
- **Búsqueda en profundidad con CTE recursiva** (`WITH RECURSIVE`) para encontrar una pieza dentro de subconjuntos a cualquier nivel.
- **Toda consulta con filtros usa `EXISTS`, no `IN (subquery)`.** El mismo filtro de placa CE pasó de 20 s a 0,07 s solo por ese cambio de forma.

## Consecuencias

- **Positivo**: un solo índice, siempre coherente; los pases nocturnos escriben sin echar a nadie.
- **Positivo**: capacidades que SQLite no da a esta escala (trigramas indexados, CTEs recursivas, `FILTER`, `GROUPING SETS`).
- **Negativo**: la app **depende de la red**. De ahí la regla que rige el arranque desde la v2.1.0: *antes de que la ventana esté en pantalla no se toca la red*. La ventana aparece en 0,6 s haya servidor o no, y la conexión ocurre después, en segundo plano y con tope de tiempo.
- **Negativo**: hay que administrar un servidor. Mitigado: corre en Docker en el NAS, que ya estaba y ya se respalda.
- **Limitación asumida**: la **indexación no puede vivir en el NAS**. La extracción de propiedades y miniaturas usa la API Document Manager de SolidWorks, que es solo para Windows, y el Synology es Linux. El pase corre en el equipo OFITEC-4 a las 15:45 de lunes a viernes, y la app muestra un semáforo con la antigüedad del índice para que se note si deja de correr.
