# Buscador de Piezas ALSI — guía para cada sesión

App PyQt5 de escritorio (Windows) que busca archivos SolidWorks del NAS contra un índice
PostgreSQL. La usan ~10 técnicos de oficina. En producción: **v2.3.0**.
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

## Reglas del usuario — ya decididas, no volver a discutir

1. **Desplegar solo cuando diga "despliega".** El ciclo acordado, sin atajos:
   probar en `releases\vX.Y.Z\` → subir de versión → copiar a la carpeta de red → al resto de
   la oficina le sale solo el aviso de "nueva versión disponible" y actualizan ellos.
   Antes de sobrescribir la red, guarda lo que hay en `releases\_backup_red_vX.Y.Z_AAAAMMDD\`.

   **La carpeta de red es producción de ~10 personas mientras trabajan.** Dos reglas que
   salieron de romperlo:
   - **Nunca ejecutes el `.exe` de la carpeta de red.** Ni para probar, ni para pedirle un
     `--diagnostico`. Se ejecuta siempre la copia de `releases\vX.Y.Z\`. Lanzar el de la red
     abre una ventana en la pantalla de quien esté delante y compite con la gente.
   - **Copiar el `.exe` son 82 MB sobre SMB**: durante ese rato, quien abra la app se
     encuentra el binario a medio reemplazar y se le queda colgada. Avisa antes de copiar, o
     hazlo fuera de horario. No es un fallo del producto: es el minuto del despliegue.
2. **Etiquetar es tu trabajo, no hace falta que lo pida.** Cada versión lleva su tag anotado y se
   empuja a GitHub. Tiene que quedar registro de cada cambio.
3. **Nada de cambios de lógica no pedidos.** Propón primero: *"para la próxima me pides permiso."*
4. **Ninguna afirmación sin medir.** Este proyecto se ha quemado varias veces con diagnósticos por
   intuición. Mide contra el servidor real y enseña los números.
5. **Muchas pruebas, siempre.** *"no puede volver a fallar."* Cada feature trae su batería.
6. **Se le habla en español**, en su idioma de negocio (piezas, conjuntos, planos).
7. **Nunca escribir en archivos de producción de SolidWorks.** Abrir siempre `allowReadOnly=true`.
   Un pase que abra y reguarde modelos de madrugada está descartado de antemano.
8. **Credenciales fuera del repositorio.** El repo es público. `config.ini` está en `.gitignore`;
   nunca lo añadas ni pegues una contraseña en el código, un test o un mensaje de commit.

## Compilar y probar

```bat
compilar.bat
```
Compila `SwPropExtractor.cs` con `csc.exe` y empaqueta con PyInstaller (*onefile*, ~82 MB). Desde
Git Bash, `csc` necesita flags con guion (`-reference:`), no con barra.

```bash
python pruebas_cascada.py         # 30 · cascada de filtros de propiedades
python pruebas_credenciales.py    # 16 · de dónde salen las credenciales
python pruebas_analisis.py        # 31 · conjuntos con piezas sin vista previa
python pruebas_exclusiones.py     # 47 · gramática de búsqueda y exclusiones
python pruebas_robustez.py --todo # 90 · servidor OK (51) + servidor caído (39)
python pruebas_datos.py           # 48 · consultas reales contra el servidor
python pruebas_v212.py            # 19 · diálogos, filtro interno, Abrir PDF
python pruebas_preview.py         # 11 · panel de vista previa e icono genérico
python pruebas_ejecutable.py      # 29 · sobre el .exe empaquetado
```

Total: **321**. Reglas del banco de pruebas:

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
- **El proceso padre pequeño (~6 MB) del `.exe` onefile es normal**, no es un zombi.
- **Nunca `taskkill /F /IM python.exe`.** Eso mató un pase nocturno a mitad. Se mata por PID.
- **Windows devuelve el mismo icono genérico** para `.SLDASM` distintos; umbral de parecido 85 %.
- **`componentes` guarda el NOMBRE del componente, no su ruta.** Unir por nombre contra `archivos`
  multiplica por todas las copias del NAS: una pieza común aparece en decenas de proyectos.
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
