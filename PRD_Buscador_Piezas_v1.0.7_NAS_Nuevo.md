# PRD / Prompt - Buscador de Piezas ALSI v1.0.7 para NAS nuevo

## Contexto

Proyecto local:

```text
C:\Users\OFITEC 4\Desktop\ANTIGRAVITY\BÚSQUEDA PIEZAS
```

Aplicación actual:

- App de escritorio Windows en Python/PyQt5.
- Archivos principales:
  - `buscar_piezas.py`: UI principal.
  - `controllers.py`: indexación y lógica de negocio.
  - `models.py`: SQLite local.
  - `sw_properties.py`: extracción de propiedades SolidWorks mediante Document Manager.
- Base actual:
  - SQLite local en `C:\Users\OFITEC 4\.alsi_busqueda\index.db`.
  - Actualmente indexa rutas antiguas de compañeros y `Z:`.
  - No debe parchearse manualmente esa BD: para v1.0.7 debe poder reconstruirse un índice nuevo contra el NAS nuevo.

## Objetivo

Crear versión `v1.0.7` del Buscador de Piezas ALSI apuntando al NAS nuevo, con la nueva estructura centralizada de proyectos.

La app debe dejar de depender de rutas por compañero tipo:

```text
\\OFITEC-4\alsi proyectos aprobados (paco)
\\OFITEC-5\alsi - proyectos aprobados (dani)
\\OFITEC-1\alsi proyectos aprobados (jesus)
Z:\ALSI INTERCAMBIO\...
```

Y debe indexar principalmente:

```text
\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS
\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D
\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR
\\192.168.1.10\Oficina Tecnica\ALSI INTERCAMBIO\ALSI LEGENDS
```

## Cambio importante de estructura

Antes, proyectos estaban así:

```text
AÑO 2026\CLIENTE\26046 LINEA PALETIZADO\133 LINEA PALETIZADO\MECANICA
```

Ahora estarán así:

```text
CLIENTE\26046 LINEA PALETIZADO\133 LINEA PALETIZADO\MECANICA
```

Ya no existe carpeta `AÑO YYYY` en el destino nuevo.

El año se debe inferir desde el código de proyecto:

- `26046` -> año 2026.
- `25052` -> año 2025.
- `23059` -> año 2023.
- `19015` -> año 2019.

Regla:

- Si el código de proyecto empieza por `YY`, año = `20YY`.
- Si no hay código claro, año = `0` o `DESCONOCIDO`.

## Alcance v1.0.7

### 1. Rutas nuevas

Sustituir el modelo de `RUTAS_RED` basado en compañeros por un modelo basado en orígenes:

```python
RUTAS_NAS_NUEVO = {
    "PROYECTOS": r"\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS",
    "BIBLIOTECA_3D": r"\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D",
    "ALSI_ESTANDAR": r"\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR",
    "ALSI_LEGENDS": r"\\192.168.1.10\Oficina Tecnica\ALSI INTERCAMBIO\ALSI LEGENDS",
}
```

La UI puede mantener internamente la columna `compañero` por compatibilidad, pero visualmente debe llamarse `Origen` o `Ubicación`.

Valores esperados:

- `PROYECTOS`
- `BIBLIOTECA_3D`
- `ALSI_ESTANDAR`
- `ALSI_LEGENDS`

### 2. Parser de proyectos nuevo

Actualizar `extraer_metadata()` en `controllers.py`.

Para rutas bajo:

```text
\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS\<CLIENTE>\<PROYECTO>\<ORDEN>\...
```

Debe extraer:

```text
cliente = segmento 1 bajo ALSI PROYECTOS APROBADOS
proyecto = segmento 2
orden = segmento 3
tipo_carpeta = MECANICA / LISTADOS / LAYOUT / PLIEGO DE CONDICIONES / OFERTAS Y PEDIDOS / OTRO
codigo_proyecto = primeros dígitos del nombre del proyecto
nombre_proyecto = texto tras código
codigo_orden = primeros dígitos del nombre de orden
nombre_orden = texto tras código
año = inferido desde codigo_proyecto
```

Ejemplo:

```text
\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS\MABE\26046 LINEA PALETIZADO\133 LINEA PALETIZADO\MECANICA\26046.E223 CONJUNTO TRPs.SLDASM
```

Debe indexarse como:

```text
origen = PROYECTOS
cliente = MABE
codigo_proyecto = 26046
nombre_proyecto = LINEA PALETIZADO
año = 2026
codigo_orden = 133
nombre_orden = LINEA PALETIZADO
tipo_carpeta = MECANICA
```

### 3. Bibliotecas

Para:

```text
\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D
\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR
```

No intentar extraer cliente/proyecto/orden como si fueran proyectos.

Usar:

```text
origen = BIBLIOTECA_3D o ALSI_ESTANDAR
cliente = ALSI
año = 0
tipo_carpeta = BIBLIOTECA o ESTANDAR
```

### 4. ALSI LEGENDS

Para:

```text
\\192.168.1.10\Oficina Tecnica\ALSI INTERCAMBIO\ALSI LEGENDS
```

Indexar como origen separado:

```text
origen = ALSI_LEGENDS
cliente = ALSI LEGENDS
año = 0 si no se puede inferir
```

No mezclar con `PROYECTOS`.

### 5. Filtros UI

Actualizar etiquetas:

- `Compañeros` -> `Origen`
- `Años de Proyecto` se mantiene.
- `Biblioteca Siddex` debe pasar a `ALSI BIBLIOTECA 3D`.
- `Alsi Estándar` debe apuntar al NAS nuevo.
- Eliminar o desactivar `Dark Web J.A` si ya no se quiere indexar Javier Alonso antiguo.

Recomendación:

- Filtro `Origen` con checkboxes:
  - Proyectos
  - Biblioteca 3D
  - ALSI Estándar
  - ALSI Legends

### 6. Reindexación

Añadir botón o flujo claro:

```text
Reindexar NAS nuevo
```

Debe permitir:

- Indexar todo.
- Indexar solo proyectos.
- Indexar solo bibliotecas.
- Indexar solo un año inferido.
- Cancelar indexación.

Importante:

- No borrar archivos de red.
- No mover carpetas.
- No remapear SolidWorks.
- Solo leer rutas y actualizar SQLite local.

### 7. Base de datos

Mantener SQLite local para v1.0.7, pero preparar el código para que en v2 pueda conectarse a base central del NAS.

No romper compatibilidad con la tabla `archivos`.

Recomendación mínima:

- Mantener columna `compañero`, pero usarla como `origen`.
- Añadir comentarios claros en código.
- No hacer migraciones destructivas.

Ideal si da tiempo:

- Añadir columna `origen TEXT`.
- Rellenarla con `PROYECTOS`, `BIBLIOTECA_3D`, `ALSI_ESTANDAR`, `ALSI_LEGENDS`.
- Mantener `compañero` por compatibilidad temporal.

### 8. Document Manager / propiedades SolidWorks

La app ya tiene:

- `SwPropExtractor.cs`
- `SwPropExtractor.exe`
- `sw_properties.py`
- `SolidWorks.Interop.swdocumentmgr.dll`

Para v1.0.7:

- Mantener extracción de propiedades, pero no debe bloquear la indexación si falla.
- Si no hay key o falla Document Manager, indexar igualmente nombre/ruta/tamaño/fecha.
- No abrir SolidWorks COM.
- No mostrar ventanas de SolidWorks.
- No pedir piezas al usuario.

### 9. Exclusiones

Ignorar:

- Archivos temporales `~$*`
- `Thumbs.db`
- Carpetas de backup o revisión si existen:
  - `ARCHIVOS REPETIDOS`
  - `REVISION MIGRACION`
  - `D:\MIGRACION_NAS_BACKUPS`
  - cualquier carpeta temporal de migración
- Opcionalmente excluir `BACKUPS`, `build`, `dist`, `__pycache__`.

No excluir:

- `MECANICA`
- `LISTADOS`
- `LAYOUT`
- `PLIEGO DE CONDICIONES`
- `OFERTAS Y PEDIDOS`

### 10. Extensiones a indexar

Mantener:

```text
.sldprt
.sldasm
.slddrw
.dwg
.pdf
.step
.stp
.iges
.igs
```

### 11. Rendimiento

La base actual tiene más de 660k registros, así que:

- Usar transacciones por lote.
- Hacer `commit` cada X archivos o por carpeta grande.
- No llamar Document Manager para PDFs/DWGs.
- Evitar refrescar UI por cada archivo; actualizar cada 500 o 1000.
- Mantener botón cancelar.

### 12. Versión y despliegue

Actualizar versión a `v1.0.7` en:

- `buscar_piezas.py`, función `check_for_updates`.
- Diálogo `Acerca de`.
- `CHANGELOG.md`.
- `README.txt`.
- `compilar.bat`.

El despliegue debe seguir apuntando a:

```text
\\192.168.1.10\Oficina Tecnica\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS
```

No desplegar automáticamente salvo que se pida explícitamente.

### 13. Tests mínimos

Añadir tests para `extraer_metadata()`.

Caso 1:

```text
\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS\MABE\26046 LINEA PALETIZADO\133 LINEA PALETIZADO\MECANICA
```

Debe devolver:

- cliente `MABE`
- año `2026`
- código proyecto `26046`
- código orden `133`
- tipo `MECANICA`

Caso 2:

```text
\\192.168.1.10\Oficina Tecnica\ALSI BIBLIOTECA 3D\RODILLOS\...
```

Debe devolver:

- origen biblioteca
- cliente `ALSI`
- año `0`

Caso 3:

```text
\\192.168.1.10\Oficina Tecnica\ALSI ESTANDAR\MESA DE TRÍAS (MTR)\...
```

Debe devolver:

- origen estándar
- cliente `ALSI`
- año `0`

Caso 4:

Ruta con acento, espacios y cliente normalizado:

```text
HORTOFRUTÍCOLA LAS NORIAS\26081 ALIM. SORTIPACK\335 DISTRIBOR CAJAS\LISTADOS
```

Debe conservar nombres reales, no inventar nombres.

### 14. Criterio de aceptación

La versión `v1.0.7` estará correcta si:

- La app arranca sin error.
- Se puede reindexar el NAS nuevo.
- La SQLite nueva contiene rutas `\\192.168.1.10\...`.
- No aparecen rutas antiguas `\\OFITEC-*` ni `Z:\` tras reindexar desde cero.
- Los filtros por cliente/proyecto/orden funcionan con la nueva estructura sin `AÑO`.
- Buscar una pieza por código, por ejemplo `26046.E223`, devuelve la ruta del NAS nuevo.
- Abrir carpeta desde resultado abre la carpeta del NAS nuevo.
- Drag & drop a SolidWorks usa la ruta del NAS nuevo.
- Si Document Manager falla, la app sigue indexando archivos básicos.

## Reglas de seguridad

- No borrar nada del NAS.
- No mover nada del NAS.
- No renombrar carpetas.
- No remapear SolidWorks desde esta app.
- No tocar el NAS viejo ni rutas `\\OFITEC-*`.
- No escribir en carpetas de proyectos salvo que el usuario lo pida explícitamente.
- Hacer cambios solo en el código fuente local del proyecto.

## Recomendación de implementación

Primero hacer solo:

1. Parser nuevo.
2. Rutas nuevas.
3. Tests.
4. Reindexación contra NAS nuevo.

Después abordar la UI.

La parte peligrosa no es la interfaz: es indexar mal la nueva estructura y llenar la búsqueda de clientes/proyectos mal clasificados.
