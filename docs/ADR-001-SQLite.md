# ADR-001: Uso de SQLite para Indexación de Archivos

## Estado

> ⚠️ **SUPERADA por [ADR-002](ADR-002-PostgreSQL.md) (v1.0.8, julio de 2026).**
> Se conserva por qué se decidió y por qué dejó de valer. **El código ya no usa
> SQLite**: el índice vive en PostgreSQL.

Aceptado en v1.0 · Superado en v1.0.8

## Contexto

El Buscador de Piezas necesita almacenar un índice de archivos (10.000-50.000+) con metadata (compañero, año, cliente, proyecto, tipo). Las alternativas consideradas fueron:

| Criterio | SQLite | JSON |
|----------|--------|------|
| **Velocidad de consulta** | ⚡ Índices SQL nativos | ❌ Lectura completa en memoria |
| **Filtros combinados** | ⚡ WHERE + AND nativo | ❌ Filtrado manual en Python |
| **Tamaño en disco** | ✅ ~2MB para 50k archivos | ⚠️ ~15MB (texto plano) |
| **Concurrencia** | ✅ Soporte nativo | ❌ Lock manual de archivos |
| **Dependencias** | ✅ Incluido en Python stdlib | ✅ Incluido en Python stdlib |
| **Escalabilidad** | ✅ Millones de filas | ❌ Lento >10k registros |

## Decisión

Usamos **SQLite** porque:
1. Las consultas con filtros múltiples (compañero + año + keyword LIKE) necesitan índices SQL para ser rápidas.
2. El scoring de relevancia se calcula en SQL (CASE WHEN + SUM), que sería muy lento en JSON.
3. La persistencia de preferencias del usuario se integra naturalmente con tablas adicionales.

## Consecuencias

- **Positivo**: Búsquedas en <100ms incluso con 50.000+ archivos.
- **Positivo**: Los índices compuestos (compañero, año) aceleran los filtros combinados.
- **Negativo**: La BD binaria no es editable a mano (mitigado: no es necesario para el usuario).

## Por qué se abandonó

La comparación de arriba era correcta para el problema de la v1.0 — **un índice local, de un solo usuario, de unas decenas de miles de archivos**. El problema cambió en tres cosas a la vez:

1. **Deja de ser de un usuario.** El índice pasa a ser el mismo para toda la oficina. Un archivo SQLite compartido por SMB no lo soporta: el bloqueo de escritura de SQLite depende de que el sistema de archivos cumpla el `fcntl`, y sobre una unidad de red eso ni está garantizado ni es fiable. Dos personas buscando mientras el pase nocturno escribe es corrupción esperando.
2. **Deja de ser de 50.000 archivos.** Hoy el índice pasa de 560.000, con 456.000 relaciones de componentes y medio millón de miniaturas guardadas.
3. **La búsqueda necesita más que `LIKE`.** Hace falta insensibilidad a tildes indexable (`pg_trgm` + una función `IMMUTABLE` propia) y CTEs recursivas para buscar dentro de subconjuntos a cualquier profundidad. En SQLite eso o no existe o va a paso de tortuga a esta escala.

La decisión de sustituirla, con sus motivos, está en **ADR-002**.
