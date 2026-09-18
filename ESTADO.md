# ESTADO DEL PROYECTO — Buscador de Piezas ALSI

> Reconstruido el **25/08/2026** a partir de las transcripciones de las sesiones perdidas, del
> historial de git de las ramas de worktree, del remoto de GitHub y del código.
> Actualizado ese mismo día con el saneamiento posterior.

---

## 1. Qué es la app

Aplicación **de escritorio Windows en PyQt5** para que los ~10 técnicos de oficina de ALSI
encuentren archivos de SolidWorks (`.sldprt`, `.sldasm`, `.slddrw`, `.dwg`, `.pdf`, `.step`)
guardados en el NAS Synology, sin navegar por carpetas.

- **Backend**: PostgreSQL en `192.168.1.10:5433`, base `ALSI`, esquema `buscador`.
- **Distribución**: un `.exe` de ~82 MB (PyInstaller *onefile*) que cada compañero instala desde
  la carpeta de red con `INSTALAR_LOCAL.bat`. La app avisa sola cuando hay versión nueva.
- **En producción: v2.3.3**.

**Cifras reales del índice, medidas el 25/08/2026:**

| | |
|---|---|
| Archivos indexados | **563.742** (PROYECTOS 542.551 · ALSI_ESTANDAR 13.256 · BIBLIOTECA_3D 7.935) |
| Miniaturas guardadas | 531.466 |
| Relaciones de componentes | 456.239 |
| Placas CE | 7.914 |
| Archivos con peso/volumen/área | 74.715 |

Lo que la app hace hoy, en corto:

- Búsqueda por nombre con gramática propia: `espacio` = frase exacta · `;` = todas las palabras ·
  `,` = cualquiera · `-palabra` = **quita** resultados.
- Filtros: origen, años, clientes, proyectos, órdenes, tipo, propiedades SW y placas CE.
- **Refinado apilable** sobre los resultados, en modo "que contengan" / "que NO contengan", con
  opción **en profundidad** (subconjuntos a cualquier nivel).
- **Buscar conjuntos que lleven una pieza**.
- Vista tabla (23 columnas, incl. Peso kg y Sup. m²) y galería con zoom continuo S/M/L/XL.
- Panel de vista previa y **vista previa flotante al pasar el ratón**.
- Diálogos de botón derecho: despiece/BOM, ¿dónde se usa?, similares, duplicados, comparar,
  abrir/insertar en SolidWorks, arrastrar a SolidWorks, Abrir PDF. Todos con miniaturas, menú
  contextual completo y buscador interno.
- **Análisis**: piezas más reutilizadas · **conjuntos con más piezas sin vista previa** (v2.2.0).
- Diagnóstico integrado (`--diagnostico`) y botón **"Copiar para enviar"** en cualquier error.
- Procesos nocturnos: reindexado del NAS, poblado de propiedades/miniaturas/masa, refresco diario
  de placas CE y purga semanal de rutas huérfanas.

---

## 2. Dónde está cada cosa

| Sitio | Qué es | Estado |
|---|---|---|
| `Desktop\ANTIGRAVITY\BÚSQUEDA PIEZAS\` (**raíz**) | Copia de trabajo principal **y** máquina servidor de los pases nocturnos | Sincronizada con `master` el 25/08. Copia de los ficheros de producción previos en `BACKUPS\produccion_antes_de_sincronizar_20260825\` |
| `.claude\worktrees\recursing-shamir-b9fab6\` | Worktree donde se desarrolla la línea 2.x | v2.3.3 |
| `.claude\worktrees\nervous-ptolemy-89ad8f\` | Investigación de las miniaturas perdidas | v2.0.9, cerrada. Contenido absorbido en master |
| `.claude\worktrees\plate-search-freezing-3491f2\` | Rama de julio | v2.0.2. Su feature de cascada ya está portada (§6.1); la rama se puede retirar |
| `\\192.168.1.10\Oficina Tecnica\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS` | Despliegue para los compañeros | `version.txt` = **v2.3.3** |
| GitHub `franferrod/APP-BUSQUEDA-ARCHIVOS` | `master` + ramas + **26 etiquetas** (v1.0.0 → v2.3.3) | Al día |

**Tareas programadas en OFITEC-4**: `ALSI_Reindexar_Diario` (15:45) y
`ALSI_Poblar_Props_Miniaturas` (16:30), con la ruta corta 8.3 `BSQUED~1` porque el Programador de
tareas de Windows falla con la `Ú` (error `0x8007010B`).

Tres cosas de esas tareas que no se ven desde el código (medidas el 18/09):

- **El reindexado muere a las 2 horas** (`ExecutionTimeLimit PT2H`). Un pase normal dura 50-62 min;
  la recuperación usa el hueco hasta los 100 min y para sola.
- **Solo corren con la sesión de `OFITEC 4` iniciada** (`LogonType Interactive`). Con el equipo
  apagado o la sesión cerrada, ese día no hay pase — y no queda rastro en ningún log.
- **El pase escribe en `~\.alsi_busqueda\reindexacion.log`** (y también en `app.log`). Hasta el
  18/09 solo escribía en `app.log`, que rota a los 3 MB: `models.py` configura el registro al
  importarse y el `basicConfig` del pase no hacía nada.

---

## 3. Decisiones de arquitectura (y por qué)

Las dos formales están en `docs\ADR-001-SQLite.md` (superada) y `docs\ADR-002-PostgreSQL.md`
(vigente). En resumen:

| Decisión | Motivo |
|---|---|
| **PostgreSQL en el NAS, no SQLite** | El índice es de toda la oficina y un proceso nocturno escribe mientras la gente lee. Un SQLite sobre SMB depende de que el sistema de archivos respete `fcntl`: es corrupción esperando |
| **La reindexación vive en OFITEC-4, no en el NAS** | Cerrado el 09/07. El Synology es Linux y la **API Document Manager de SolidWorks es solo Windows**. Sin ella no hay propiedades ni miniaturas. El equipo queda encendido L-V y la app muestra un semáforo con la antigüedad del índice |
| **Extracción vía C# `SwPropExtractor.exe`** | Document Manager es COM/.NET. Flags `--preview`, `--masa`. Abre siempre `allowReadOnly=true`: **nunca bloquea ni escribe archivos de producción** |
| **Miniaturas cacheadas en la BD** | Para que funcionen en equipos **sin SolidWorks** y no releer el NAS en cada búsqueda |
| **Búsqueda indexada con `pg_trgm`** | `unaccent()` es `STABLE` y no se indexa → `buscador.sin_tildes()` `IMMUTABLE` + índice GIN. De 4× a 172× más rápido |
| **Antes de dibujar la ventana no se toca la red** (v2.1.0) | Causa raíz del "no me abre la app". La ventana sale en **0,6 s** haya servidor o no |
| **Barrido del índice sin relojes** | Un sweep por timestamps comparaba `NOW()` (UTC) con `datetime.now()` (local) y **vació orígenes enteros dos veces**. Ahora es por conjunto de rutas, con tres salvaguardas |
| **Geometría de ventana en `QSettings`** | Estaba en la tabla compartida y las coordenadas de un doble monitor abrían la app fuera de pantalla a todos |
| **Credenciales por entorno** (v2.2.0) | `ALSI_PG_*` evita dejar la contraseña en disco. El `config.ini` sigue valiendo para no romper a nadie |
| **Sin PDM de verdad** | Fingir check-in/check-out y control de revisiones sin un *vault* sería peor que no tenerlo |
| **Parqueado por decisión** | Visor 3D rotable; miniaturas STEP (código listo, `EJECUTAR_STEP = False`) |

---

## 4. Terminado

Toda la línea 2.x hasta la **v2.3.3** está en producción. Lo más reciente:

**Pase nocturno, 18/09 — el índice se cura solo** (sin versión de app: el `.exe` no cambia):

- **Faltaban 70.909 archivos de PROYECTOS** (11 % del NAS), medido recorriendo el NAS entero
  contra el índice: 63.088 legibles que nunca entraron, 7.605 con ruta de 260+ caracteres y 216 de
  los últimos días (esos los recoge el pase normal). BIBLIOTECA_3D y ALSI_ESTANDAR, completos.
- **Causa**: PROYECTOS solo se reindexaba por fecha, últimos 7 días. Del 17 al 23/07 el pase se
  lanzó pero el NAS no respondía (`NAS no responde` en `app.log.1`), y otros días ni se lanzó.
  Lo tocado esos días no entró nunca. Detonante: el PDF de `26003.P270`.
- **`recuperar_faltantes`**: en el mismo recorrido de cada noche se apunta lo que falta y se mete
  al final, **solo insertando** (`ON CONFLICT DO NOTHING`, un `SAVEPOINT` por archivo), con tope
  de 100 min de pase. Orden: PDF/DWG/STEP → SolidWorks del año más nuevo al más viejo → sin año.
  A mano: `python reindexar_diario.py --recuperar --minutos N`.
- **Rutas de 260+**: un único recorrido `recorrer_nas` con el prefijo `\\?\UNC\` para indexar,
  recuperar y purgar. En la BD, siempre la ruta normal.
- **Coste medido**: extraer propiedades cuesta 0,13 s por archivo (muestra de 40); los 39.603
  SolidWorks legibles que faltaban son ~86 min. Con rutas largas el extractor falla en 0,03 s:
  entran sin propiedades ni miniatura.
- **Recuperado el 18/09 por la tarde, a mano y vigilado** (`--recuperar`, dos tandas: 25 y 80
  min): **70.693 archivos**, 0 fallidos, 6 conjuntos que agotaron los 20 s del extractor (entran
  sin propiedades). PROYECTOS 546.233 → 616.926. **Medido otra vez recorriendo el NAS entero:
  faltan 0 en los tres orígenes**, 0 rutas repetidas, 0 prefijos colados. La búsqueda real de la
  app para `26003.P270` pasa de 1 resultado (la pieza) a 4 (pieza, plano, DWG y PDF).
- **Mañana a las 16:30** `poblar_propiedades` repasará las 70.693 filas nuevas (ids por encima
  de su punto de control): redundante para lo de SolidWorks, útil para las miniaturas de los
  19.351 PDF y 7.097 DWG. Unas 2-3 horas, fuera de horario.

- **v2.1.4** — exclusiones `-palabra` con chips «Sin …» y un único analizador `parsear_termino`.
- **v2.1.3** — la vista previa ya no machaca la miniatura buena con el icono genérico de Windows.
- **v2.1.2** — buscador dentro de todos los diálogos, "Abrir PDF", Guía Rápida reescrita.
- **v2.1.1** — el refinado coordina con la búsqueda de arriba; botón "Copiar para enviar".
- **v2.1.0** — la app abre siempre; diagnóstico; `crash.log`; instancia única.
- **v2.0.7–v2.0.9** — búsqueda indexada, peso y superficie, `config.ini` robusto, arreglo del
  `taskkill 0xc0000142`, "Abrir carpeta" con re-detección de host.

**v2.3.3 — desplegada el 03/09**:

- **Dos instancias a la vez**, una por escritorio de Windows, con una búsqueda distinta en cada
  una. La tercera se rechaza con un aviso que explica dónde están las otras dos.
- **Dos y no más, por aritmética medida**: el servidor admite 100 conexiones y cada instancia
  abre hasta 10; con diez personas, una por cabeza ya roza el techo.
- El candado de la v2.1.0 existía porque entonces la app tardaba en abrir y se acumulaban
  procesos invisibles. Esa causa desapareció en esa misma versión (ventana en 0,6 s).
- **`max_conexiones` ajustable** en `config.ini` sin recompilar.

**v2.3.2 — desplegada el 02/09**:

- **Los filtros son de cada equipo.** Origen, años, carpetas, tipos y el reparto de la ventana
  se guardaban en `buscador.preferencias`, una tabla compartida de dos columnas: los del último
  que cerraba la app se los encontraba puestos el siguiente. Ahora van a QSettings, con herencia
  la primera vez para que nadie note un salto.
- **El banco de pruebas vuelve a ser fiable**: varias baterías terminaban con error aunque
  pasaran todo, porque `runpy` desmontaba la app con los hilos de fondo vivos. Se sale desde
  dentro del arnés (`arnes_pruebas.salir`). 353 comprobaciones, todas en verde.

**v2.3.1 — desplegada el 26/08**:

- **El arranque ya no lanza DDL.** `init_db()` corría entero en cada arranque: un esquema, seis
  tablas y quince índices con `IF NOT EXISTS`, todos pidiendo bloqueo aunque no hubiera nada que
  hacer. Con un `pg_dump` ajeno de 8 horas encima, eso dejó **9 sentencias atascadas y 31
  consultas paradas**: la oficina entera sin buscador. Ahora, si el esquema está completo, cero
  sentencias.
- **`lock_timeout` de 15 s** en todas las conexiones: ninguna consulta puede volver a esperar un
  bloqueo indefinidamente.
- **Tocar un filtro pasa de congelar la ventana 0,65 s a 0,000 s.**
- **El refinado queda atado a su propia búsqueda** (carrera de 4 ms destapada al pasar los
  filtros a segundo plano).
- **Las pruebas ya no escriben en `buscador.preferencias`** (`ALSI_SIN_PREFERENCIAS=1`).

**v2.3.0 — desplegada el 25/08** (incluye la v2.2.0, que no salió por separado para no dar dos avisos de actualización el mismo día):

- **Cascada de filtros de propiedades SW** (§6.1): de 204 materiales a 68 con un cliente marcado.


- **Análisis › Conjuntos con más piezas sin vista previa** (§5).
- **Credenciales fuera del repositorio**: variables `ALSI_PG_*` y `.gitignore` que bloquea
  `config.ini`. Comprobado que la contraseña **nunca llegó a subirse** a GitHub.
- `INSTALAR_LOCAL.bat` anunciaba la **2.1.2** con la app en 2.1.4: corregido.
- Etiquetas retroactivas de la v2.0.0 a la v2.1.2.

**Pruebas: 427 comprobaciones en verde** (18 preferencias + 19 fluidez + 30 cascada + 31 análisis +
16 credenciales + 47 exclusiones + 51 robustez servidor OK + 39 robustez servidor caído + 48 datos +
19 v2.1.2 + 11 preview + 32 sobre el `.exe` empaquetado + **66 del pase nocturno**).

---

## 5. Las vistas previas perdidas: investigación cerrada y qué se hizo

Problema **ajeno a la app**, demostrado con datos:

- **4.677 archivos de 2026 sin vista previa**; **1.053** la tenían y la perdieron.
- **No es la app**: abre en solo lectura, nunca escribe miniaturas, y el 17/09/2025 un guardado
  dejó 682 de 685 archivos sin vista previa **cinco meses antes del primer commit de la app**.
- **No es junio**: los proyectos viejos tocados en junio están al 18,3 % sin vista frente al
  35,0 % de sus iguales sin tocar.
- **La causa es guardar en bloque**: 0,9 % de uno en uno → 3,8 % en tandas de 8-20. Los planos
  `.slddrw` no se rompen nunca (0 de 3.257).

**Y no se puede reparar automáticamente.** Se le preguntó a la propia DLL: de vista previa solo
existen métodos `Get*` (`GetPreviewBitmap`, `GetPreviewPNGBitmapBytes`…). **No hay ningún `Set`.**
Document Manager sabe *leer* la miniatura rápido — eso ya lo hacemos — pero el archivo roto
sencillamente no la tiene guardada. Generarla exige que SolidWorks dibuje el modelo: abrir,
reconstruir y guardar. Eso es escribir en archivos de producción y **no se hace desatendido**.

**Lo que sí se ha hecho (v2.2.0)**: como la reparación la tiene que hacer una persona, la app
señala **dónde compensa**. `Análisis › Conjuntos con más piezas sin vista previa` ordena los
conjuntos por cuántas piezas recuperarías de una sola pasada — el primero arregla 278 de golpe.
Se abre en SolidWorks desde el propio diálogo, se reconstruye con Ctrl+Q, se guarda todo, y esa
noche el índice recoge las miniaturas nuevas.

El conteo es **conservador a propósito**: una pieza solo cuenta como rota si **ninguna** copia
suya del índice tiene miniatura. La tabla `componentes` guarda el nombre, no la ruta, y una misma
pieza está copiada en decenas de proyectos; contar "le falta en alguna copia" mandaría a la gente
a reabrir conjuntos que están bien.

---

## 6. Qué sigue pendiente

### 6.1 ✅ Filtros de propiedades SW en cascada — portados en la v2.3.0

Estuvieron nueve meses colgando en `claude/plate-search-freezing-3491f2` (commits `159dfb0` y
`5862cc2`) sin llegar nunca a master. Portados el 25/08/2026.

Conviene recordar la distinción, porque se confunde fácil:

- **Filtrar por una propiedad ya funcionaba bien.** Elegir "montaje" devuelve resultados correctos
  (52.433 archivos tienen ese valor). Eso se arregló en su día con el fallo de codificación cp850.
- **Lo que faltaba era que la lista de opciones se estrechara** al contexto. Medido: **204**
  materiales distintos en PROYECTOS, pero solo **68** con el cliente GRUPO LUCAS.

Al portarlo se corrigió un fallo del original: un valor formado solo por espacios entraba como
cadena vacía y descuadraba el recuento en uno.

### 6.2 Cosas propuestas y no empezadas

- **Informe de carpetas casi idénticas** (self-join trigram) para cazar erratas tipo
  APILADOR / APLIADOR.
- **Panel "Salud del índice"**.
- **Pack de fricción diaria**: abrir el trío (pieza + plano + PDF), copiar imagen, vista rápida
  con ESPACIO, favoritos, "usada en N conjuntos".
- **"Novedades de la semana"**, columna Plano ✓/✗, informe de duplicados.
- **Detección nocturna de vistas previas rotas**: el pase ya lee la vista previa de cada archivo
  que cambia y hoy descarta el dato. Marcarlo no cuesta ni una lectura extra y haría que el
  informe del punto 5 detecte roturas **el mismo día**.

### 6.3 Salido de la investigación del 18/09 — propuesto, NO hecho

- **🔴 Buscar con «Ø» o «º» no encuentra NADA** (medido 18/09, fallo antiguo de la app, ajeno
  a la recuperación). `rodillo Ø50` → 0 resultados, `rodillo o50` → 390; `curva 90º` → 0,
  `curva 90` → 3.082. Los 9 nombres con Ø o º probados, buscados tal cual: 0 resultados todos.
  **Causa**: el término se normaliza en Python (`normalizar_texto`, NFKD) y el nombre en la BD
  con `unaccent`; no coinciden en 12 caracteres presentes en el índice: **Ø** (8.521 archivos:
  la app la deja, la BD la hace O), **º** (2.300: la app la hace O, la BD la deja), **ª** (601),
  ø, ¾, espacio duro, ´, ¡, ±, ×, ®, Ð. **Arreglo propuesto**: normalizar el término con la
  misma función de la BD (`UPPER(buscador.sin_tildes(%s))`) — iguales por construcción, como
  `NOMBRE_NORM` — midiendo antes que el índice GIN se sigue usando. Cambio de la app.
- **Casilla «Sin año» en el filtro de años.** 53.712 archivos de carpetas sin número de proyecto
  (48.997 bajo `ALSI\`: PALETIZADOR 11.926, AÑO 2015 8.771, HORNO 5.469…) entran en el índice pero
  `anio IN (...)` los deja fuera de la búsqueda: medido, 0 de 5 salen con los filtros de siempre y
  5 de 5 sin filtro de años. Ya había 273 así antes de la recuperación. **Aun así valen ya**: el
  despiece cruza por nombre sin filtro de años, y 1.795 componentes que hoy salen en gris (usados
  5.953 veces; `CT.530.P724 … RODILLO SUJECCION LONA`, en 258 conjuntos) están en esas carpetas.
  Es cambio de la app. De paso: `ALSI\AÑO 2015\…` podría leerse como año 2015.
- **«Reindexar NAS» de la app borra antes de volver a indexar** (`IndexadorThread`: `DELETE ...
  WHERE origen/anio` y luego recorre). Si se corta a mitad, se pierde lo borrado: es el mismo
  fallo que tuvo el pase en agosto (mark & sweep lo arregló allí, no aquí). Y con años marcados
  se salta todo lo «sin año». Hipótesis SIN MEDIR: podría explicar parte de los 63.088 perdidos.
- **El pase lanza DDL al arrancar** (`CREATE INDEX IF NOT EXISTS` sobre `componentes`). Pide
  bloqueo aunque no haga nada: la regla 2 de CLAUDE.md. Comprobar antes en el catálogo.
- **Un error de base de datos en el bucle de cada noche** deja la transacción abortada y el
  resto de la noche no indexa nada (antes, además, en silencio). La recuperación ya usa un
  `SAVEPOINT` por archivo; el indexado diario y el completo, no.
- **La purga no debería borrar lo de las carpetas que no pudo listar**: `recorrer_nas` ya las
  apunta en `errores`, falta usarlo.
- **Rutas largas en la app**: «Abrir carpeta»/«Abrir» fallan con 260+ y el aviso diría que el
  archivo se movió. Y `poblar_propiedades` usa `os.path.exists` sin prefijo: no les saca miniatura.

---

## 7. Bugs conocidos y riesgos

1. **Diálogos anidados con aspecto distinto** — en la segunda anidación de "¿qué componentes
   lleva?" el símbolo de la ventana y el tooltip cambian de color. Se descartaron icono, flags,
   paleta, modalidad y tamaños: todos idénticos a nivel Qt. Posiblemente resuelto en la última
   versión; pendiente de confirmación con una captura.
3. **`config.ini` sigue viajando en la carpeta de red** con la contraseña en claro. Desde la
   v2.2.0 existe la alternativa por entorno, pero los equipos ya instalados siguen con el archivo.
4. **La lectura nocturna de vista previa falla ~1 % de las veces** (10 de 44 discrepancias eran
   archivos que sí la tenían y el pase no se la encontró). Declarado en el informe.
5. **RESUELTO en la v2.3.1**: tocar un filtro congelaba la ventana 0,65 s porque
   `refrescar_filtros_jerarquicos` consultaba la base de datos en el hilo de la interfaz.
   Era código de febrero, la última pieza sin migrar a segundo plano. Ahora bloquea 0,000 s.
6. **La consulta de conjuntos sin vista previa tarda ~7-9 s** y bloquea la interfaz con el cursor
   de espera, igual que "Piezas más reutilizadas". Si molesta, toca moverla a un worker.
7. **🔴 Desde el 25/08 los pases nocturnos no calculan el PESO** (medido el 18/09, SIN ARREGLAR,
   pendiente de permiso). El `SwPropExtractor.exe` de git es la compilación del **13/07**, sin
   `--masa`; el bueno (18/08, md5 `d2af77cb`, 8.192 B) está en `releases\v2.0.8`…`v2.1.2` y en la
   red. Al sincronizar la raíz con git el 25/08 se cambió el bueno por el viejo. El `.cs` de git es
   idéntico al de `releases\v2.1.2`: lo que está mal es solo el binario. Las mismas 4 piezas: el
   de la raíz no da peso a ninguna, el de `v2.1.2` a las 4 (1,85 · 3,64 · 0,009 · 1,43 kg), igual
   de rápido. Piezas de 2020 en adelante sin peso y con material: **3.606**.
   Arreglo propuesto: poner el bueno en la raíz **y subirlo a git** (si no, la próxima
   sincronización lo vuelve a romper) y rellenar con `poblar_masa.py` fuera de horario.
8. **La clave de licencia de Document Manager está en claro en `app.log` y `app.log.1` de
   OFITEC-4**, de los avisos de tiempo agotado anteriores al 18/09 (el código ya no la escribe).
   Propuesto: borrarla de esos dos ficheros. `reindexacion.log` está limpio (0 apariciones).
9. **La carpeta `BACKUPS\produccion_antes_de_sincronizar_20260825\` que cita el punto 2 no
   existe** (comprobado el 18/09): la copia de lo que había en producción antes del 25/08 no está.

**Resueltos el 25/08:** el conteo de archivos de la guía (decía 590.000, son 563.742) · el desfase
de versión de `INSTALAR_LOCAL.bat` · las etiquetas que faltaban · `ADR-001` obsoleto · el worktree
`banda-rugosa` (era una consulta de ingeniería mecánica, no del proyecto) · el fichero con nombre
corrupto · la desincronización de la carpeta raíz.

**Las placas CE `26-0303` y `24-0568` no son un fallo nuestro.** Comprobado el 25/08 leyendo el
Excel y la base a la vez: nuestro parseo lee `26-0303 → 26009.E130` y `24-0568 → 24061.E091`
exactamente como están escritos en los listados. El error está en el Excel; al corregirlo ahí, el
pase nocturno lo recoge solo.

---

## 8. Incidentes que no se pueden repetir

- **Dos vaciados de orígenes completos** por un sweep con relojes de husos distintos. Cualquier
  cambio en la purga se prueba **antes** contra un origen sintético.
- **Propiedades SW sin indexar durante meses**: el extractor emite **cp850** y se decodificaba
  como UTF-8; el error se lo tragaba un `except: pass`.
- **Filtro de placa CE "roto"**: era un plan de consulta de 20 s por usar `IN (subquery)`. Con
  `EXISTS`, 0,07 s y resultados idénticos.
- **Un identificador con `ñ`** colgaba `connect()` de PyQt al arrancar.
- **Escapado de barras invertidas en heredocs**: rompió la UNC del NAS dos veces y metió un `\t`
  en un `.bat` que habría dejado a la oficina sin poder actualizar.
- **Un `taskkill /F /IM python.exe` global** durante unas pruebas mató el pase nocturno a mitad y
  dejó BIBLIOTECA_3D a medias. Se mata por PID, nunca por nombre de imagen.
- **Un cambio no pedido** en la regex de placa CE. De ahí: *"para la próxima me pides permiso"*.
- **Una semana sin pase = archivos perdidos para siempre.** Del 17 al 23/07 el pase no llegó al
  NAS; con la ventana de 7 días, lo modificado esos días no entró nunca. Se descubrió dos meses
  después por un PDF que no salía. Desde el 18/09 el pase recupera lo que falte, sea de cuando sea.
