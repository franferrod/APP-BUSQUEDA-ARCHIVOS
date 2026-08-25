# Changelog - Buscador de Piezas ALSI

## [2.3.0] - 2026-08-25 (Los filtros de propiedades ya se estrechan al contexto)

Incluye todo lo de la 2.2.0, que no llegó a desplegarse por separado.

- **Material, Tratamiento, Cierre y Espesor funcionan ya en cascada**, igual que Clientes y Proyectos: solo se ofrecen los valores que **existen en lo que tienes filtrado**. Hasta ahora la lista de materiales mostraba los **204** del índice entero aunque tuvieras marcado un cliente que solo usa **68**. Había que bajar por una lista larguísima llena de opciones que no iban a devolver nada.
- **Se recalcula solo** al cambiar origen, años, clientes o proyectos, y también después de reindexar el NAS.
- **Lo que tengas marcado nunca se esconde**, aunque deje de aplicar: si no, no habría forma de desmarcarlo. Y **«Todos» ya no marca lo que está oculto**, que era una manera silenciosa de filtrar por valores inexistentes y quedarse sin resultados.
- **No cuesta fluidez.** La consulta es una sola pasada con `GROUPING SETS` y corre **en segundo plano**, nunca en el hilo de la interfaz; lanzarla devuelve en 0,000 s. Lleva número de generación para descartar respuestas que llegan tarde, y si el mismo contexto ya está calculado no se vuelve a preguntar.
- **Si el servidor falla, se ve todo**, exactamente como antes: la cascada nunca deja la lista vacía por un error.
- **28 comprobaciones nuevas** (`pruebas_cascada.py`) contra el servidor real: que estrecha de verdad y cuadra con el SQL, que las bibliotecas siguen ignorando los filtros jerárquicos, que lo marcado no se esconde, que una respuesta obsoleta no pisa a la buena y que los espesores (`3`, `3.00`, `5.5`) se traducen bien a milímetros.

*De paso se corrigió un fallo del código original: un valor de propiedad formado solo por espacios entraba como cadena vacía y descuadraba el recuento en uno.*

## [2.2.0] - 2026-08-25 (Recuperar vistas previas · credenciales fuera del repositorio)

**Análisis nuevo: «Conjuntos con más piezas sin vista previa».** Cierra la investigación de las miniaturas perdidas. Quedó demostrado que no las rompe ni la app ni el NAS ni el indexado, sino guardar en bloque desde SolidWorks, y que **no hay forma de repararlas automáticamente**: la API de Document Manager sabe *leer* la vista previa pero no escribirla, así que lo único que la regenera es abrir el archivo, reconstruir (Ctrl+Q) y volver a guardar.

- Como eso lo tiene que hacer una persona, la app señala **dónde compensa hacerlo**: el botón **Análisis** lista los conjuntos ordenados por cuántas de sus piezas recuperarías de una sola pasada. El primero de la lista arregla 278 piezas de golpe.
- Cada fila trae su miniatura, el año, el cliente y el proyecto, y se abre en SolidWorks con el botón derecho como cualquier otro resultado. Se exporta a CSV para repartir el trabajo.
- El conteo es **conservador a propósito**: una pieza solo cuenta como rota si **ninguna** copia suya del índice tiene vista previa. La tabla de componentes guarda el nombre, no la ruta, y una misma pieza está copiada en decenas de proyectos: contar "le falta en alguna copia" habría mandado a la gente a reabrir conjuntos que están bien.
- La **Guía Rápida** explica por qué pasa, cómo arreglarlo y cómo evitarlo (Ctrl+Q antes de *Guardar todo*).

**Las credenciales pueden salir del repositorio.** `config.ini` lleva la contraseña de PostgreSQL en claro y el repositorio es público en GitHub. Se ha comprobado que **nunca llegó a subirse** —no aparece en ningún commit del historial—, pero nada lo impedía.

- Ahora la conexión se puede definir con las variables de entorno `ALSI_PG_HOST`, `ALSI_PG_PORT`, `ALSI_PG_DBNAME`, `ALSI_PG_USER` y `ALSI_PG_PASSWORD`, y no hace falta ningún archivo.
- El caso más práctico: dejar el `config.ini` **sin la línea `password`** y poner solo `ALSI_PG_PASSWORD` en el entorno del equipo. Si están las dos, manda el entorno.
- **Ningún equipo instalado se rompe**: un `config.ini` completo sigue funcionando exactamente igual que antes.
- `.gitignore` ahora bloquea `config.ini`, los artefactos de compilación y las sondas de diagnóstico.
- **16 comprobaciones nuevas** (`pruebas_credenciales.py`) sobre las cinco vías posibles, incluida la de que el archivo no esté en el árbol de git.

**Corrección de intendencia.** `INSTALAR_LOCAL.bat` anunciaba la versión **2.1.2** mientras la app ya iba por la 2.1.4: el instalador llevaba dos versiones desfasado en el rótulo. Ahora se sube junto con `APP_VERSION`.

**Historial de versiones completo.** Se han creado las etiquetas que faltaban de la v2.0.0 a la v2.1.2 — el etiquetado se había quedado parado en la v1.1.0. Cada versión apunta ya a su commit.

## [2.1.4] - 2026-08-24 (Quitar palabras de la búsqueda con «-palabra»)

Petición de un compañero: poder decir en la **barra de búsqueda** qué palabras **no** quieres ver en el nombre del archivo. Hasta ahora eso solo se podía hacer refinando por componentes, que es otra cosa: filtraba por lo que el conjunto lleva dentro, no por cómo se llama.

- **`-palabra` quita resultados.** `cinta;450;-banda` son las cintas de 450 que **no** llevan «banda» en el nombre. Se pueden encadenar (`-banda;-inox`) y convive con el resto de la sintaxis: `;` sigue exigiendo todas, `,` sigue ampliando, y lo que se quita se quita en los dos casos — en una búsqueda con comas, la exclusión manda sobre todo el conjunto.
- **Los nombres con guion de verdad no se rompen.** El guion solo quita cuando abre palabra. `26-0006`, `AC30-Q6A014`, `22057-188` o un nombre real del índice como `NO USAR - COLORES ERRONEOS` se siguen buscando tal cual. Comprobado archivo a archivo contra el servidor.
- **Se ve por qué salen menos resultados.** Cada palabra excluida aparece bajo la barra como un chip **«Sin banda»**, y su ✕ la devuelve a la búsqueda sin tener que reescribir el término. Antes, una exclusión olvidada no tenía ninguna explicación en pantalla.
- **`-banda` a solas no lanza una búsqueda a ciegas.** Quitar no es buscar: la app lo dice y propone el término completo (`cinta; -banda`) en vez de devolver medio índice o cero resultados sin motivo aparente.
- **El modo «Conjuntos que lo lleven» entiende lo mismo**: `pata curva;-soporte` son los conjuntos que llevan una pata curva y **no** llevan ningún soporte.
- **Una sola gramática para toda la app.** El troceado del término estaba copiado en cuatro sitios y podían discrepar. Ahora hay un único analizador (`parsear_termino`) que usan la consulta al servidor, el filtro local y el modo Conjuntos — y hay pruebas de que cliente y servidor deciden siempre lo mismo sobre el mismo archivo.
- **Ayuda al día**: el recuadro de búsqueda y su tooltip enseñan la sintaxis completa, y la Guía Rápida tiene un apartado nuevo con ejemplos y las dos trampas (el guion de las referencias y el `-palabra` a solas). De paso, los subtítulos `###` se pintaban literalmente en la pestaña de Ayuda; ahora se renderizan.
- **47 comprobaciones nuevas** (`pruebas_exclusiones.py`) sobre datos reales del servidor: gramática, consulta contra SQL a pelo (que se quita exactamente lo pedido, ni uno más), coherencia cliente/servidor, modo Conjuntos, la interfaz y la propia ayuda.

## [2.1.3] - 2026-08-24 (La vista previa ya no tapa la miniatura buena)

- **Al seleccionar un ensamblaje, el panel derecho mostraba el cubo genérico de SolidWorks** aunque en la galería se viera perfectamente su miniatura. Causa medida: cuando Windows no sabe renderizar un `.SLDASM` devuelve **el mismo icono genérico para archivos distintos** (comprobado: dos ensamblajes diferentes devolvían la misma imagen pixel a pixel), y la app lo aplicaba sin comprobar nada, machacando la miniatura correcta que ya estaba puesta.
- **Ahora el panel se queda con la imagen buena.** Antes de aplicar lo que devuelve Windows se compara con la miniatura del propio archivo —la misma que pinta la galería—: si no se parece lo suficiente, se descarta. Los números reales de la medición separan los dos casos sin ambigüedad: un render de verdad da 99–100 % de parecido y el icono genérico 35–36 %; el listón está en el 85 %.
- **Segunda red de seguridad**: si Windows devuelve exactamente la misma imagen para dos archivos distintos, se marca como icono genérico y no se vuelve a usar en toda la sesión. Archivos distintos no pueden tener la misma vista previa.
- **La miniatura del propio archivo se usa además como respuesta instantánea**: al seleccionar, el panel pinta ya la de la base de datos y solo la sustituye si llega algo mejor de verdad.
- **11 comprobaciones nuevas** (`pruebas_preview.py`) sobre archivos reales del servidor: que la medida de parecido separa los dos casos, que el icono genérico no reemplaza ni se guarda en caché, que un render de más resolución sí se aplica, y que galería y panel leen la misma imagen.

## [2.1.2] - 2026-08-21 (Buscar dentro de los diálogos · Abrir PDF · guía al día)

- **Buscar dentro de los resultados de un diálogo.** El despiece de un conjunto puede traer cientos de componentes y había que recorrerlos a ojo. Ahora todos los diálogos —despiece, ¿en qué ensamblajes se usa?, similares, duplicados y comparar— llevan un cuadro que filtra en vivo. Se escriben varias palabras y deben aparecer todas, sin importar tildes ni mayúsculas, y busca en todas las columnas (componente, cliente, proyecto, año…). Al lado indica cuántas filas quedan de cuántas.
- **"Abrir PDF" en el botón derecho**, sobre una pieza, un ensamblaje o un plano: abre directamente el PDF que comparte código con el archivo (mismo primer token del nombre, por ejemplo `24120.P027`). Si hay varios PDF con ese código, deja elegir. Si no hay ninguno, lo dice en vez de no hacer nada. Está tanto en la rejilla principal como dentro de los diálogos.
- **Guía Rápida reescrita entera.** Seguía describiendo la versión 1.x —hablaba de "Indexar Compañeros" y de filtrar por quién diseñó la pieza— y **explicaba mal la sintaxis de búsqueda**: decía que las comas buscan archivos que tengan todas las palabras, cuando en realidad las comas amplían (cualquiera de ellas). Ahora son 11 secciones que cubren lo que la app hace hoy:
  - La sintaxis de verdad: `tuerca m16` es frase exacta (6 resultados), `tuerca;m16` exige todas las palabras (23), `tuerca,m16` admite cualquiera (muchos más). Medido, no supuesto.
  - Refinado con SÍ/NO contengan, subconjuntos, chips y Esc; buscar conjuntos que lleven una pieza; el despiece con peso y superficie; placas CE; qué hacer si algo va mal; y los atajos.
- **Fix de la propia guía**: las negritas no se cerraban (se sustituía cada `**` por `<b>`), así que a partir de la primera negrita el resto de la sección salía en negrita. Se veía en el apartado "Mantenerlo al día". Ahora se cierran por pares y el texto entre acentos graves sale en monoespaciado.

## [2.1.1] - 2026-08-21 (Refinar sin pulsar Enter · errores que se pueden mandar)

- **El refinado ya coordina con la búsqueda de arriba.** Si escribías un término nuevo en el buscador y aplicabas un refinado sin pulsar Enter, el refinado se aplicaba sobre los resultados de la búsqueda *anterior* (o sobre nada), y parecía que «no busca bien». Ahora, si el cuadro de arriba no corresponde a los resultados que hay en pantalla, se lanza primero la búsqueda general y el refinado se aplica solo en cuanto llegan los resultados. Vale igual para «que contengan» y para «que NO contengan».
  - Si no hay nada escrito arriba, lo dice en la barra de estado en vez de no hacer nada.
  - Si la búsqueda no llega a lanzarse (por ejemplo sin ningún origen marcado), el refinado no se queda colgado para aplicarse solo en una búsqueda posterior: vuelve a su cuadro.
- **Todos los errores se pueden mandar con un botón.** Cualquier error abre ahora un aviso con **«Copiar para enviar»**: copia al portapapeles un informe con la versión, el equipo, la hora, el mensaje, el detalle técnico y las últimas líneas del registro. Un compañero solo tiene que pegarlo en un mensaje — se acabaron las capturas de pantalla y el «me ha dado un error». También hay un botón para abrir la carpeta del registro.
- **Los avisos ya no bloquean un arranque desatendido.** Los cuadros de «Atención» respetan el modo automático, igual que se hizo en la V2.0.8 con los pases nocturnos.
- **Válvula de seguridad del candado de instancia única** (V2.1.0): si el proceso que lo puso ya no existe, el candado se retira solo. Un candado huérfano dejando a alguien sin poder abrir la app habría sido el mismo problema que vinimos a arreglar, causado por el arreglo.
- **Batería de pruebas incluida** (`pruebas_robustez.py`): 90 comprobaciones automáticas en dos escenarios — servidor OK (51) y servidor inaccesible (39). Cubre arranque, tiempos, red, coordinación de la búsqueda, errores copiables, diagnóstico, instancia única, rutas de red y consultas reales. Se lanza con `python pruebas_robustez.py --todo` y devuelve error si algo falla.

## [2.1.0] - 2026-08-21 (La app abre siempre, y si algo falla lo dice)

Raíz de la incidencia de Pablo y Marcos ("le doy y no se abre"): **la aplicación hablaba con la red antes de dibujar la ventana**. Comprobaba el NAS y abría la conexión con PostgreSQL en el arranque, sin límite de tiempo. En un equipo que no llegaba al servidor —firewall de Windows 11 recién configurado, perfil de red en «Pública», el portátil aún levantando la Wi-Fi— Windows tarda unos 21 segundos en rendirse en cada intento. Durante ese rato había un proceso en el Administrador de tareas y **ni una ventana en pantalla**. Si además la conexión fallaba del todo, la excepción cerraba el proceso sin dejar rastro visible. Nadie podía saber qué estaba pasando.

**Regla nueva: antes de que la ventana esté en pantalla no se toca la red.** Medido: la ventana aparece en **0,6 s** tanto con el servidor bien como con el servidor completamente inaccesible (antes: 10,4 s en el mejor de los casos, o nunca).

- **La ventana abre siempre.** El NAS y la base de datos se consultan después, con la ventana ya visible.
- **Nada de esperas infinitas.** La conexión a PostgreSQL tiene ahora un tope de 5 s (ajustable en `config.ini` con `connect_timeout`), y la comprobación del NAS 3 s por host. Antes: ~21 s de bloqueo por intento.
- **Si no hay servidor, se dice.** Aparece un aviso rojo con **a qué servidor no se llega y por qué**, un botón *Reintentar* y otro de *Diagnóstico*. La app reintenta sola cada 10, 20, 40 s… hasta 5 minutos.
- **La ventana no se congela.** La conexión y los reintentos corren en segundo plano; el hilo de la interfaz se bloquea 0,04 s.
- **Nunca más un cierre mudo.** Cualquier fallo de arranque muestra un cuadro de diálogo con la causa y la ruta del log — incluso si ocurre antes de que exista la interfaz, que era justo cuando el aviso se perdía. Los cuelgues duros (fallos de Qt o de una DLL) quedan registrados en `crash.log`.
- **Botón de Diagnóstico**, también desde la línea de comandos con `BuscadorPiezas.exe --diagnostico` (funciona aunque la app no arranque). Comprueba servidor, puerto, NAS por sus dos nombres, versión desplegada, espacio en disco y permisos de la carpeta temporal, y lo deja listo para copiar y pegar en un mensaje.
- **El log dice dónde se quedó.** Cada fase del arranque se registra con su duración; si algo tarda más de 5 s sale marcado como aviso. El log ahora rota (3 MB × 4) en vez de crecer sin fin.
- **Una sola ventana.** Si la app ya está abierta, un segundo doble clic no crea otro proceso invisible: avisa de que ya está abierta y dónde buscarla. Los candados de procesos muertos se limpian solos.
- **Sin base de datos, la app no se rompe.** Las preferencias caen a su valor por defecto en vez de impedir que se monte la ventana.

*Sin cambios para los procesos nocturnos: siguen abortando si no hay base de datos, que es lo que deben hacer.*

## [2.0.9] - 2026-08-19 (Abrir carpeta fiable)
- **"Abrir carpeta" ya no falla porque la app arrancara antes que la red.** El host del NAS se detectaba UNA sola vez al abrir la aplicación: si en ese instante el servidor no respondía —lo típico al encender el equipo e iniciar la app enseguida— *todos* los "Abrir carpeta" fallaban el resto de la sesión, aunque la red se recuperase a los cinco segundos. Ahora se comprueba en el momento de abrir, probando las dos formas de llegar al NAS, y se recuerda la que funcione.
- **El aviso dice qué pasa de verdad.** Antes siempre culpaba al servidor. Ahora distingue tres casos: el archivo se ha movido o renombrado (y abre la carpeta igualmente, que es más útil), no tienes permisos sobre esa carpeta del NAS, o no se llega al servidor. Además queda registrado en el log con la ruta, para poder diagnosticarlo.
- Los diálogos de resultados usan el mismo camino: antes, si fallaban, no decían nada.

## [2.0.8] - 2026-08-17 (Peso y superficie · refinado "que NO contengan")
- **Peso y superficie de cada pieza y conjunto**, leídos de SolidWorks (los mismos valores que ves en Herramientas → Propiedades físicas). Medido sobre 65 archivos reales: hay dato en el 96% de las piezas y el 80% de los conjuntos, a 0,2 s por archivo.
- **Peso total y superficie a pintar en el despiece.** Al abrir "Ver componentes" sale el peso sumado del conjunto y **los m² de superficie**, para poder decirle a pintura cuántos metros cuadrados hay que pintar. Si a algún componente le falta el dato, lo dice: *"3 de 6 componentes sin datos, el total es parcial"* — un total incompleto presentado como definitivo sería peor que no darlo.
- **Columnas Peso (kg) y Sup. (m²) en el despiece**, ordenables como números, y ambas incluidas al exportar a CSV para mandarlo a pintura o a compras.
- **Filtro de cordura**: se descarta cualquier valor cuya densidad sea imposible. En la muestra apareció una "pieza" de 373 toneladas que era un modelo descargado de internet; con el filtro no entra. De 114 piezas reales no se descartó ni una legítima.
- **Fix del actualizador**: a algún compañero le saltaba *"taskkill.exe - La aplicación no se pudo iniciar correctamente (0xc0000142)"* al actualizar. El ejecutable empaquetado deja su carpeta temporal dentro del PATH, y ahí van las DLL del runtime de Visual C++; `taskkill.exe`, lanzado por el actualizador, cargaba esas DLL en vez de las suyas y no arrancaba. Ahora se limpia el PATH antes de lanzar la actualización y se llama a `taskkill` y `timeout` por su ruta absoluta de Windows.
- **La app ya no muere si se abre desde otra carpeta.** `config.ini` se busca ahora en varios sitios (junto al ejecutable, la instalación local, la carpeta del usuario y la de red) en vez de en uno solo, y se avisa de dónde se ha mirado si de verdad no aparece. Un `config.ini` incompleto se descarta y se sigue buscando, en vez de cerrar la app con un error críptico.
- **Los procesos nocturnos ya no se pueden quedar colgados.** El aviso de configuración era una ventana modal que se abría siempre, también en el reindexado y los pases de propiedades que corren de noche sin nadie delante: bloqueaban el proceso indefinidamente esperando un clic que nadie iba a dar, y por la mañana no había reindexado ni rastro del motivo. Ahora los scripts escriben el error en el log y terminan; la ventana solo sale en la app.
- **Peso y Sup. se pueden ocultar** desde el menú Columnas, igual que el resto.
- **Al contraer el panel de filtros**, la zona de resultados ocupa ya todo el ancho: antes quedaba un hueco muerto porque el divisor mantenía el reparto anterior.
- En el panel derecho se muestra **solo el Peso**. La superficie se queda en la columna de la lista: decía "a pintar" sin que la app sepa si la pieza se pinta, y afirmarlo no era correcto. Por lo mismo, el total del despiece pasa a llamarse "Superficie total".
- **Refinado "que NO contengan"** (botón ⊘ azul en la barra de refinar): quita de los resultados los conjuntos que llevan esa pieza. Ejemplo: cintas A450 → NO contengan MOTOR REM = las que llevan otro motor. Atajo: escribe un `-` delante del término y pulsa Enter. Los niveles negativos salen en azul para no confundirlos con los que sí exigen la pieza.

*Nota: los datos de peso se van rellenando en el pase nocturno. Los conjuntos consultados antes de que pase mostrarán el aviso de que aún no hay datos.*

## [2.0.7] - 2026-08-17 (La búsqueda, de 3 a 46 veces más rápida)
- **Todas las búsquedas son mucho más rápidas, con resultados idénticos.** La consulta normalizaba el nombre del archivo con una función que PostgreSQL no puede indexar, así que cada búsqueda recorría las 589.459 filas de la tabla entera: ese era el ~medio segundo fijo que tenía cualquier búsqueda, y la razón de fondo de los atascos al combinar filtros. Ahora la misma consulta usa un índice: TUERCA M16 pasa de 548 ms a 12 ms (46x), CHASIS PATA de 539 a 34 ms (16x), PLETINA MONTAJE de 561 a 59 ms (9,5x). Verificado archivo por archivo: los resultados son exactamente los mismos.
- **Resultados estables.** Cuando una búsqueda daba el máximo de 5.000 resultados, cuáles de ellos se mostraban dependía de cómo la base de datos hubiera recorrido la tabla: repetir la misma búsqueda podía enseñar 5.000 archivos distintos. Ahora el orden es determinista y repetir una búsqueda da siempre lo mismo.

## [2.0.6] - 2026-08-14 (Los diálogos de resultados funcionan como la búsqueda general)
Una búsqueda dentro de la búsqueda debe permitir lo mismo que la búsqueda principal. Ahora **los cinco diálogos de resultados** — "¿En qué ensamblajes se usa?", "Ver componentes (despiece)", "Piezas idénticas", "Ensamblajes similares" y "Comparar 2 ensamblajes" — se comportan igual que la rejilla:
- **Arrastrar a SolidWorks para insertar**, con selección múltiple para soltar varios de una vez.
- **Botón "Abrir en SolidWorks"** en el pie de cada diálogo. Con más de 3 seleccionados avisa antes de abrirlos todos.
- **Menú del botón derecho completo**, con las mismas opciones que en la rejilla y habilitadas según el tipo de archivo: Abrir/Insertar en SolidWorks · Abrir Carpeta · Copiar Ruta · Copiar Nombre · ¿En qué ensamblajes se usa? · Ver componentes (despiece) · Ensamblajes similares · Buscar piezas idénticas · Comparar los 2 ensamblajes seleccionados.
- Se puede encadenar: desde el despiece abrir el "dónde se usa" de un componente, y desde ahí su despiece.
- La primera fila queda preseleccionada, para que los botones funcionen sin tener que clicar antes.
- Los diálogos no aceptan soltar archivos (solo arrastrar), para que nadie mueva nada del NAS sin querer.

**Vista previa grande al pasar el ratón** (estilo Pack&Go de SolidWorks), en la rejilla, la galería y los cinco diálogos:
- Al dejar el ratón medio segundo sobre una fila aparece la imagen a 320 px junto al cursor, con el nombre del archivo. No roba el foco ni interrumpe nada, y se aparta sola si no cabe en la pantalla.
- Sale de la caché de miniaturas de la base de datos, **nunca del NAS**, y se guarda en memoria: pasar el ratón arriba y abajo por la lista no repite consultas.
- No aparece mientras arrastras, ni en la galería en XL (ahí la tarjeta ya es más grande que la ventanita).

## [2.0.5] - 2026-08-14 (Filtros más cómodos y miniaturas DWG)
- **Todas las listas de filtros muestran el mismo número de casillas (6)**: antes cada una tenía un alto distinto y, al no caber en la barra lateral, se encogían a su mínimo — unas enseñaban 4 casillas y otras 5. Las listas cortas (ORIGEN con 3, CIERRE con 5) se ajustan a su contenido para no dejar filas en blanco.
- **Rueda del ratón más fina en los filtros**: Qt desplazaba 3 casillas por muesca y, con 5 a la vista, un solo giro se llevaba media lista. Ahora avanza de 2 en 2 y en píxeles, así que el movimiento es suave. Si la lista ya está al tope, la rueda sigue moviendo la barra lateral entera como siempre.
- **Sin barra de desplazamiento horizontal en los filtros**: los nombres largos se recortan con puntos suspensivos y el nombre completo aparece al pasar el ratón por encima. Antes esa barra robaba una casilla de alto en unas listas sí y en otras no.
- **Fix miniaturas DWG en la galería**: dejaban de crecer a mitad del deslizador mientras las de SolidWorks y PDF seguían aumentando. Causa: un tope de ampliación de 2x la resolución nativa, y los DWG solo llevan una previsualización embebida de 163 px (SolidWorks y PDF se guardan a 256). Ahora todas las tarjetas escalan al mismo tamaño sea cual sea el formato. Nota: a zoom máximo los DWG se ven algo más blandos porque el archivo no contiene más resolución.

## [2.0.4] - 2026-08-07 (Conjuntos que llevan una pieza, zoom de galería y profundidad)
- **Buscar conjuntos que lleven una pieza**: junto al botón Buscar hay un selector (▾) con "Buscar conjuntos que lleven esa pieza" — escribes una referencia (ej. AC30-Q6A014) y salen los ENSAMBLAJES que la contienen, respetando todos los filtros (años, cliente, Placa CE…). Sintaxis: `;` = que lleven todas · `,` = cualquiera de ellas.
- **Refinar resultados (búsqueda en cascada)**: sobre los resultados puedes ir acotando por piezas que deben contener, encadenando niveles. Cada nivel deja un chip quitable y Esc deshace el último hasta volver a la búsqueda general.
- **Botón "Subconjuntos" (profundidad)**: encuentra la pieza aunque esté dentro de un subconjunto, a cualquier nivel (ej. MOTOR REM 0.37: 241 conjuntos directos → 627 en total).
- **Vista previa ampliable**: al arrastrar el divisor del panel derecho la imagen crece de verdad (antes se quedaba en un recuadro fijo).
- **Galería con XL y zoom libre**: presets S/M/L/XL, deslizador para el tamaño exacto y Ctrl + rueda del ratón. Se recuerda en cada equipo.
- **Última búsqueda por equipo**: la app arranca con la última búsqueda de cada ordenador (antes se compartía la de quien buscara por último).
- **Fix**: error al quitar el chip del filtro de Clientes ("'bool' object has no attribute 'blockSignals'").
- **Fix**: tras pulsar "Actualizar ahora" la app vuelve a abrirse sola (fallaba el rearranque con "Failed to load Python DLL").

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
