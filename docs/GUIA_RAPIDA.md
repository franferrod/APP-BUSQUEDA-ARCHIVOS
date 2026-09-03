# 🚀 Guía Rápida - Buscador de Piezas ALSI

Encuentra cualquier pieza, conjunto, plano o PDF del NAS en décimas de segundo, y averigua dónde se usa, qué lleva dentro y cuánto pesa.

El índice tiene **más de 560.000 archivos** de PROYECTOS, BIBLIOTECA 3D y ALSI ESTÁNDAR, y se actualiza solo cada noche.

## 1. Buscar: la barra de arriba

Escribe y pulsa **Enter**. La forma de separar las palabras cambia lo que encuentras:

*   `tuerca m16` — **frase exacta**: las palabras juntas y en ese orden. La búsqueda más precisa.
*   `tuerca;m16` — **todas** las palabras, en cualquier orden y posición del nombre. Más amplia.
*   `tuerca,m16` — **cualquiera** de las palabras. La más amplia de todas.
*   `-banda` — **quita** de la lista todo lo que lleve esa palabra en el nombre.

> Regla rápida: el punto y coma **exige**, la coma **amplía**, el guion **quita**. Si salen pocos resultados prueba con `;`, y si aún así no aparece, con `,`.

### Quitar palabras que no quieres ver

Un guion delante de una palabra la deja fuera. Se mezcla con todo lo demás:

*   `cinta;450;-banda` — cintas de 450 **que no sean de banda**.
*   `cinta;450;-banda;-inox` — se pueden poner **las que hagan falta**.
*   `cinta,tapa,-inox` — cinta **o** tapa, pero **ninguna** de inox. Con coma también quita.

Cada palabra que estés quitando aparece bajo la barra como un chip **«Sin …»**: así siempre se ve por qué salen menos resultados, y con su ✕ vuelve a entrar sin reescribir nada.

Dos cosas que conviene saber:

*   El guion solo quita cuando **abre palabra**. Los nombres y referencias que llevan guion de verdad se buscan tal cual: `26-0006`, `AC30-Q6A014` o `NO USAR - COLORES` funcionan como siempre.
*   `-banda` a solas no busca nada, porque quitar no es buscar. Escribe primero **qué quieres encontrar** y luego lo que sobra.

También puedes buscar por **código** (`24120.P027`), por **número de placa CE** (`24-0947`) o por parte del nombre del proyecto.

*   **Recientes**: arriba a la derecha están tus últimas búsquedas, para repetirlas de un clic.
*   **Guardadas**: guarda las búsquedas que repites a menudo.

## 2. Buscar conjuntos que lleven una pieza

Pulsa la **flecha ▾ al lado del botón Buscar** y elige *"Buscar conjuntos que lo lleven"*.

Escribe una referencia (por ejemplo `AC30-Q6A014` o `MOTOR REM 0.37KW`) y saldrán **los ensamblajes que la contienen**, no la pieza. Sirve para responder a "¿en qué máquinas montamos esto?" antes de cambiar nada.

Se le pueden aplicar todos los filtros de la izquierda, igual que a una búsqueda normal, y vale la misma sintaxis: `pata curva;-soporte` son los conjuntos que llevan una pata curva **y no llevan ningún soporte**.

## 3. Refinar: buscar dentro de tus resultados

Debajo de la barra de búsqueda aparece **"De estos resultados, deja los que…"**. Es una segunda búsqueda **sobre lo que ya tienes en pantalla**, y se pueden encadenar varios niveles.

*   **SÍ contengan** — deja solo los conjuntos que llevan esa pieza.
*   **NO contengan** — quita los que la llevan. Ejemplo: *cintas A450* → NO contengan *MOTOR REM* = las que llevan otro motor.
*   **Atajo**: escribe un `-` delante del término y pulsa Enter para el modo NO.
*   **Subconjuntos**: busca también **dentro de los subconjuntos**, a cualquier profundidad. Sin ese botón solo mira los componentes directos. Ejemplo real: *MOTOR REM 0.37* pasa de 241 conjuntos directos a 627 contando subconjuntos.

Cada nivel deja un **chip** que puedes quitar con su ✕. Los niveles NO salen en azul, para no confundirlos con los que sí exigen la pieza. **Esc** deshace el último nivel, uno a uno, hasta volver a la búsqueda general.

> No hace falta pulsar Enter arriba antes de refinar: si cambias el término de la barra de búsqueda y aplicas el refinado, la búsqueda general se lanza sola y el refinado se aplica encima.

## 4. Los filtros de la izquierda

Se combinan entre sí y funcionan **en cascada**: al elegir un año solo verás los clientes y proyectos de ese año, y **Material, Tratamiento, Cierre y Espesor solo ofrecen los valores que existen en lo que tienes filtrado**. Si marcas un cliente que usa 68 materiales, no tendrás que bajar por los 204 del índice entero.

*   **Origen**: PROYECTOS, BIBLIOTECA 3D, ALSI ESTÁNDAR.
*   **Años de proyecto**, **Carpetas** (MECÁNICA, LAYOUT, LISTADOS…), **Clientes** y **Proyectos**.
*   **Fabricación**: láser, torno, fresa, soldadura, pintura, montaje — leído de las propiedades de SolidWorks.
*   **Material**, **Tratamiento**, **Cierre**, **Espesor** y **Tipo de banda**.
*   **Tipos** (arriba): piezas, ensamblajes, planos, DWG, PDF, STEP.
*   **Placa CE**: deja solo los archivos que tienen placa CE asociada.

Los chips naranjas de arriba muestran qué filtros tienes puestos; **Limpiar** los quita todos.

> Si tenías marcado un valor que deja de aplicar al cambiar de contexto, **no se esconde**: sigue ahí para que puedas desmarcarlo. Y **Todos** marca solo lo que se ve, nunca lo oculto.

## 5. Ver los resultados

*   **Lista** o **Galería**, con tamaños **S / M / L / XL** y una barra para el tamaño exacto (o **Ctrl + rueda del ratón**).
*   **Pasa el ratón por encima** de una miniatura y verás la imagen en grande, sin tener que clicar.
*   **Un clic**: vista previa y datos a la derecha (cliente, proyecto, material, peso, si tiene plano…).
*   **Doble clic**: abre la carpeta de Windows con el archivo seleccionado.
*   **Arrastra** una fila **sobre SolidWorks** para insertar la pieza en el ensamblaje que tengas abierto.
*   **Columnas**: elige qué columnas ver. **Exportar**: pasa los resultados a Excel (CSV).

## 6. El botón derecho

*   **Abrir/Insertar en SolidWorks**
*   **Abrir PDF** — abre directamente el PDF del plano que comparte código con la pieza.
*   **Abrir Carpeta** · **Copiar Ruta** · **Copiar Nombre**
*   **¿En qué ensamblajes se usa?** — todas las máquinas que llevan esa pieza.
*   **Ver componentes (despiece)** — todo lo que lleva dentro un conjunto.
*   **Ensamblajes similares** — máquinas que comparten un alto porcentaje de piezas.
*   **Buscar piezas idénticas (duplicados)** — misma geometría con otro nombre.
*   **Comparar componentes de los 2 ensamblajes** — selecciona dos conjuntos y verás qué tiene cada uno y qué comparten.

> Todo esto funciona igual **dentro** de los diálogos: desde el despiece puedes abrir el "dónde se usa" de un componente, y desde ahí su propio despiece.

## 7. El despiece: qué lleva un conjunto

Botón derecho sobre un ensamblaje → **Ver componentes (despiece)**.

*   Lista completa de componentes con cliente, proyecto, año y origen.
*   **Peso total** y **superficie total** del conjunto, para pedir material o decirle a pintura cuántos m² hay.
*   Si a algún componente le falta el dato **lo dice**: *"3 de 12 componentes sin datos, el total es parcial"*.
*   **Buscar dentro de la lista**: el cuadro de arriba filtra los componentes en vivo. Escribe varias palabras y deben aparecer todas. Funciona sin tildes y sin distinguir mayúsculas.
*   Los componentes en gris no están indexados: son **referencias rotas** o piezas en carpetas excluidas.
*   **Exportar CSV** para mandarlo a compras o a pintura.

Ese mismo cuadro de búsqueda está en el resto de listas: *dónde se usa*, *similares*, *duplicados* y *comparar*.

## 8. Placas CE

El filtro **Placa CE** deja solo los archivos con placa asociada, y puedes buscar directamente por el número de placa (`24-0947`).

La base de placas se actualiza cada tarde desde los Excel de **NÚMEROS DE SERIE**, de 2005 hasta hoy.

## 9. Si algo va mal

*   **Aviso rojo "Sin conexión con la base de datos"**: la aplicación abre igual y reintenta sola. Puedes pulsar **Reintentar** o **Diagnóstico**.
*   **Cualquier error** trae un botón **"Copiar para enviar"**: cópialo y pégalo en un mensaje. Lleva la versión, tu equipo, la hora y el registro; con eso se puede arreglar sin adivinar.
*   **Diagnóstico** comprueba servidor, puerto, NAS, versión y disco, y lo deja listo para copiar.
*   Puedes tener el Buscador abierto **dos veces a la vez**, con una búsqueda distinta en cada uno — por ejemplo uno en cada escritorio de Windows. Si intentas abrir un tercero, te avisa y te recuerda que los otros dos están en la barra de tareas.
*   Si **"Abrir carpeta"** falla, el aviso distingue si el archivo se movió, si no tienes permisos o si no se llega al servidor.

## 10. Recuperar vistas previas perdidas

Algunos archivos antiguos aparecen **sin miniatura**: en la galería y en el panel de la derecha sale el icono genérico en vez del modelo. No es culpa de la app ni del NAS. Pasa cuando SolidWorks guarda muchos archivos de golpe (al hacer *Guardar todo* sobre un conjunto): a los hijos que necesitaban reconstruirse no les graba la imagen de vista previa.

**Sólo hay una forma de arreglarlo**: abrir el archivo en SolidWorks, reconstruir con **Ctrl + Q** y volver a guardar. No se puede hacer desde el indexado nocturno — la API que usamos sabe leer la miniatura, pero no escribirla.

Para que compense el rato, el botón **Análisis › Conjuntos con más piezas sin vista previa** ordena los conjuntos por cuántas piezas suyas recuperarías de una sola pasada. Abre uno con el botón derecho (**Abrir en SolidWorks**), reconstruye, guarda todo, y esa noche el índice recoge las miniaturas nuevas.

> **Cómo evitarlo de aquí en adelante:** pulsa **Ctrl + Q** antes de *Guardar todo*. Los planos (`.slddrw`) no se ven afectados nunca.

## 11. Mantenerlo al día

El NAS **se reindexa solo cada noche**, así que normalmente no hay que hacer nada.

Si acabas de guardar un archivo y lo necesitas ya, pulsa **Reindexar NAS** abajo a la izquierda. En la esquina inferior derecha se ve cuándo se actualizó el índice por última vez.

Cuando haya una versión nueva saldrá un aviso naranja arriba con el botón **Actualizar ahora**.

## 12. Atajos

*   **Enter** — buscar (en la barra de refinar, aplica el nivel)
*   **Esc** — deshace el último nivel de refinado
*   **Ctrl + C** copiar el nombre · **Ctrl + Mayús + C** copiar la ruta
*   **Doble clic** — abrir la carpeta
*   **Ctrl + rueda** — agrandar o achicar las miniaturas
*   **Arrastrar** — soltar sobre SolidWorks para insertar
