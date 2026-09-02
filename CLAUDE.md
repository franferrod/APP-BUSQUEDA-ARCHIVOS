# Buscador de Piezas ALSI — guía para cada sesión

App PyQt5 de escritorio (Windows) que busca archivos SolidWorks del NAS contra un índice
PostgreSQL. La usan ~10 técnicos de oficina. En producción: **v2.3.1**.
El estado completo del proyecto está en `ESTADO.md`; las decisiones de fondo, en `docs/ADR-002`.

## Dónde trabajar

La **carpeta raíz** es la copia de trabajo buena (sincronizada con `master` el 25/08/2026) **y** la
máquina que ejecuta los pases nocturnos (`ALSI_Reindexar_Diario` a las 15:45,
`ALSI_Poblar_Props_Miniaturas` a las 16:30). Las dos cosas a la vez, así que:

- **Nunca dejes la raíz en un estado intermedio.** Un `stash` sin terminar el `merge` deja los
  scripts nocturnos en la versión antigua. Si tienes que sincronizar, hazlo entero y comprueba
  después que `reindexar_diario.py` y `models.py` importan.
- El worktree `recursing-shamir-b9fab6` sigue siendo donde se desarrolla la línea 2.x.
- Los pases usan la ruta corta 8.3 `BSQUED~1` porque el Programador de tareas de Windows falla con
  la `Ú` (`0x8007010B`). No "arregles" esa ruta.

## NO DEJAR COLGADA A LA OFICINA — leer antes de tocar nada

Diez personas dependen de esto **mientras trabajan**, y comparten un servidor y una
carpeta de red. Estas reglas salieron de romperlo, no de la teoría.

1. **El servidor PostgreSQL es de producción y está compartido con otras aplicaciones.**
   No lances baterías de pruebas contra él en horario de oficina sin decirlo. Si hay que
   hacerlo, **de una en una**, nunca en paralelo: varias a la vez se estorban entre sí y
   parece que la app se ha colgado.
2. **Nada de DDL sobre tablas en uso.** Un `ALTER TABLE` o un `CREATE INDEX`, aunque lleven
   `IF NOT EXISTS` y no tengan nada que hacer, piden un bloqueo. Si alguien mantiene una
   transacción larga encima (el 26/08/2026 fue un `pg_dump` de otra base, 8 horas), el DDL
   se encola **y todas las consultas que llegan después se encolan detrás de él**. Se
   comprueba antes con `information_schema` y solo se altera si de verdad falta algo.
3. **Las pruebas no escriben en `buscador.preferencias`.** Es una tabla **compartida**:
   lo que guarda el último que cierra la app se lo encuentra puesto el siguiente. Todas las
   baterías corren con `ALSI_SIN_PREFERENCIAS=1`. Si escribes una batería nueva, ponlo.
4. **Nunca ejecutes el `.exe` de la carpeta de red**, ni para pedirle un `--diagnostico`:
   abre una ventana en la pantalla de quien esté delante. Se ejecuta siempre la copia de
   `releases\vX.Y.Z\`.
5. **Copiar el `.exe` a la red son 82 MB sobre SMB.** Durante ese rato, quien abra la app se
   encuentra el binario a medio reemplazar y se le queda colgada. **Despliega fuera de
   horario**, o avisa antes.
6. **Nunca `taskkill /F /IM python.exe`** ni nada por nombre de imagen: eso mató un pase
   nocturno a mitad. Se mata por PID, y solo el proceso concreto.
7. **Si algo va mal, mira el servidor antes que el código.** `pg_stat_activity`,
   `pg_locks` con `NOT granted`, y transacciones abiertas ordenadas por antigüedad. La
   incidencia del 26/08 no estaba en la app: eran 31 consultas esperando un bloqueo.

## Reglas del usuario — ya decididas, no volver a discutir

1. **Desplegar solo cuando diga "despliega".** El ciclo acordado, sin atajos:
   probar en `releases\vX.Y.Z\` → subir de versión → copiar a la carpeta de red → al resto de
   la oficina le sale solo el aviso de "nueva versión disponible" y actualizan ellos.
   Antes de sobrescribir la red, guarda lo que hay en `releases\_backup_red_vX.Y.Z_AAAAMMDD\`.
   Las reglas 4 y 5 de arriba mandan sobre el momento de copiar.
2. **El número de versión lo decide él.** No lo subas por iniciativa propia.
   Textual: *"Eso lo decido yo... no me lies."*

   **Y si el despliegue va a salir con un número distinto del que te pidió, pregúntaselo ANTES
   de copiar nada — no lo anuncies después.** Pasó el 25/08/2026: pidió desplegar la v2.2.0,
   entró un porte limpio encima y desplegué la **v2.3.0** doblando las dos para no dar dos
   avisos de actualización el mismo día. El razonamiento era bueno y lo aceptó, pero la
   decisión no era mía. La oficina saltó de la v2.1.4 a la v2.3.0 sin pasar por la v2.2.0.
   Cuando dos versiones se doblen en una, hay que **etiquetar igualmente la que no se
   desplegó** para que el historial no tenga huecos.
3. **Etiquetar es tu trabajo, no hace falta que lo pida.** Cada versión lleva su tag anotado y se
   empuja a GitHub. Tiene que quedar registro de cada cambio.
4. **Nada de cambios de lógica no pedidos.** Propón primero: *"para la próxima me pides permiso."*
5. **Ninguna afirmación sin medir.** Este proyecto se ha quemado varias veces con diagnósticos por
   intuición. Mide contra el servidor real y enseña los números.
6. **Muchas pruebas, siempre.** *"no puede volver a fallar."* Cada feature trae su batería.
7. **Se le habla en español**, en su idioma de negocio (piezas, conjuntos, planos).
8. **Nunca escribir en archivos de producción de SolidWorks.** Abrir siempre `allowReadOnly=true`.
   Un pase que abra y reguarde modelos de madrugada está descartado de antemano.
9. **Credenciales fuera del repositorio.** El repo es público. `config.ini` está en `.gitignore`;
   nunca lo añadas ni pegues una contraseña en el código, un test o un mensaje de commit.

## Compilar y probar

```bat
compilar.bat
```
Compila `SwPropExtractor.cs` con `csc.exe` y empaqueta con PyInstaller (*onefile*, ~82 MB). Desde
Git Bash, `csc` necesita flags con guion (`-reference:`), no con barra.

```bash
python pruebas_preferencias.py    # 18 · que los filtros sean de cada equipo
python pruebas_fluidez.py         # 19 · que tocar un filtro no congele la ventana
python pruebas_cascada.py         # 30 · cascada de filtros de propiedades
python pruebas_credenciales.py    # 16 · de dónde salen las credenciales
python pruebas_analisis.py        # 31 · conjuntos con piezas sin vista previa
python pruebas_exclusiones.py     # 47 · gramática de búsqueda y exclusiones
python pruebas_robustez.py --todo # 90 · servidor OK (51) + servidor caído (39)
python pruebas_datos.py           # 48 · consultas reales contra el servidor
python pruebas_v212.py            # 19 · diálogos, filtro interno, Abrir PDF
python pruebas_preview.py         #  7 · panel de vista previa e icono genérico
python pruebas_ejecutable.py      # 29 · sobre el .exe empaquetado
```

Total: **353**. Reglas del banco de pruebas:

- `pruebas_ejecutable.py` **exige la app cerrada** (instancia única, candado). Pídeselo.
- La carpeta de pruebas del `.exe` necesita su `config.ini`.
- Patrón del arnés: `runpy.run_path(..., run_name="__main__")` con `QApplication.exec_` parcheado,
  `QT_QPA_PLATFORM=offscreen`, y los flags `ALSI_SIN_DIALOGOS`, `ALSI_SIN_CANDADO`,
  `ALSI_CONFIG_INI`. Para un diálogo modal, parchea `QDialog.exec_` y captura el `self`.
- Servidor inalcanzable: IP de test RFC 5737 `192.0.2.1`.
- Diagnóstico de una build: `BuscadorPiezas.exe --diagnostico`.
- **Las pruebas que eligen su muestra del servidor tienen que usar la misma regla que el
  producto.** Ya ha fallado dos veces por lo contrario: un icono genérico sintético que no se
  parecía al real, y una muestra de PDF más laxa que `_codigo_de_nombre`. Si una prueba falla,
  la primera hipótesis es que la prueba está mal, no el producto — pero compruébalo.

## Trampas del proyecto (todas han mordido ya)

- **`buscar_piezas.py` líneas 8-9 redirigen `sys.stdout`/`sys.stderr`** a
  `~\.alsi_busqueda\startup_error.log`. Por eso la salida "desaparece" al canalizarla.
- **Nombres de método en ASCII.** Un identificador con `ñ` colgó `connect()` de PyQt al arrancar.
- **Heredocs y barras invertidas.** Editar Python o `.bat` con rutas UNC desde un heredoc ha
  corrompido escapes tres veces. Usa las herramientas de escritura de ficheros, y **ejecuta** el
  `.bat` generado antes de fiarte.
- **CRLF.** Los ficheros del repo están en CRLF y los blobs de git en LF: un `diff` crudo entre
  `git show` y el fichero de disco marca **todas** las líneas como distintas. Normaliza con
  `tr -d '\r'` antes de concluir que algo cambió.
- **`SwPropExtractor.exe` emite cp850**, no UTF-8. La cascada cp850→utf-8→cp1252→latin-1 no se
  toca, y ningún fallo de decodificación se traga en silencio.
- **Postgres rinde en UTC; la oficina va en UTC+2.** Nunca compares `NOW()` con `datetime.now()`.
  El barrido del índice es por **conjunto de rutas**, sin relojes. Esto ya vació dos orígenes.
- **`unaccent()` es `STABLE` y no se indexa.** Se usa `buscador.sin_tildes()` (`IMMUTABLE`), y
  `NOMBRE_NORM` debe coincidir **letra por letra** con la expresión del índice GIN.
- **`IN (subquery)` vs `EXISTS`**: el mismo filtro pasó de 20 s a 0,07 s.
- **Filtros opcionales: acopla el SQL, no uses `(%s IS NULL OR col = %s)`.** Con el `OR` el
  planificador descarta el índice; una consulta pasó de 7 s a más de dos minutos.
- **Qt pasa `checked` (bool) a los slots de `triggered`/`clicked`.** Usa siempre
  `lambda _checked=False, r=ruta: ...` o acabarás en `os.startfile(True)`.
- **PyInstaller contamina el entorno del hijo** (`_MEI*`, `_PYI*`, y el temporal en el `PATH`).
  Cualquier `subprocess` a un exe del sistema va con entorno limpio y ruta absoluta.
- **Windows devuelve el mismo icono genérico** para `.SLDASM` distintos; umbral de parecido 85 %.
- **`componentes` guarda el NOMBRE del componente, no su ruta.** Unir por nombre contra `archivos`
  multiplica por todas las copias del NAS: una pieza común aparece en decenas de proyectos.
- **Las baterias que abren la ventana salen con `arnes_pruebas.salir()`, DENTRO del arnes.**
  Si se deja volver a `runpy`, este desmonta el modulo de la app con los hilos de fondo aun
  vivos y Windows mata el proceso (`0xC0000409`) *despues* de imprimir todo en verde. Y ojo:
  Git Bash enseña ese codigo como `127`. Pideselo a Python si algo no cuadra.
- **Peso (21) y Sup. (22) van al final de la tabla** a propósito: no desplaces índices de columna.

## Sintaxis de búsqueda (medida, no supuesta)

`tuerca m16` = frase exacta · `tuerca;m16` = todas las palabras · `tuerca,m16` = cualquiera ·
`-banda` = quita del resultado. El guion solo excluye cuando abre palabra, así que `26-0006`,
`AC30-Q6A014` y `NO USAR - COLORES ERRONEOS` siguen buscándose tal cual. Hay **un solo**
analizador, `parsear_termino`, compartido por consulta SQL, filtro local y modo Conjuntos.

## Al cerrar una feature

Actualiza `CHANGELOG.md` (en español, orientado a lo que el compañero nota, no al diff) y
`docs\GUIA_RAPIDA.md` si cambia algo visible — la guía va empaquetada dentro del `.exe`, así que
raíz y worktree deben coincidir. Commit, push, y **etiqueta la versión** al desplegarla.
