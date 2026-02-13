# ADR-001: Uso de SQLite para Indexación de Archivos

## Estado
Aceptado (v1.0)

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
