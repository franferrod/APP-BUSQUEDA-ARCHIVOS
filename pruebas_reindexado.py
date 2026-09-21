# -*- coding: utf-8 -*-
r"""Pruebas del pase nocturno: recuperación de lo que falta y rutas largas
(2026-09-18).

    python pruebas_reindexado.py

Por qué existen: el PDF de 26003.P270 no salía en la app. El pase de PROYECTOS
solo miraba los últimos 7 días, y del 17 al 23 de julio no llegó al NAS: lo que
se modificó esos días no entró nunca. En septiembre faltaban 70.909 archivos,
7.605 de ellos por tener una ruta de 260 caracteres o más, que Windows no abre
sin el prefijo \\?\UNC\.

Cómo trabajan sin tocar nada de nadie:
  - El NAS es de mentira: una carpeta temporal con la forma de ALSI PROYECTOS
    APROBADOS, incluidas rutas de más de 260 caracteres.
  - La BD es la real, pero con un ORIGEN SINTÉTICO ('PRUEBA_RECUPERACION'),
    como se probó el barrido en agosto. La app filtra por origen, así que
    ningún compañero ve estas filas, y se borran al acabar pase lo que pase.
  - El extractor de SolidWorks se cambia por uno falso que apunta con qué
    ruta le llaman: no se abre ningún archivo de SolidWorks.
  - El pase entero (main) se prueba contra una BD FALSA en memoria. Con la
    real, el barrido de BIBLIOTECA_3D borraría la de verdad.
"""
import base64
import io
import logging
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("ALSI_SIN_PREFERENCIAS", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import psycopg2                      # noqa: E402
import reindexar_diario as rd        # noqa: E402
from models import PG_CONFIG         # noqa: E402

ORIGEN = "PRUEBA_RECUPERACION"
RESULTADOS = []


def comprobar(bloque, texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((bloque, texto, ok, detalle))
    print("  %-60s %s%s" % (texto, "OK" if ok else "FALLO",
                            ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


# --- Que las pruebas no ensucien app.log ni reindexacion.log -----------------
CAPTURA = []


class _Captura(logging.Handler):
    def emit(self, record):
        CAPTURA.append((record.levelno, record.getMessage()))


rd.logger.propagate = False
rd.logger.addHandler(_Captura())


def avisos(texto):
    return [m for n, m in CAPTURA if n >= logging.WARNING and texto in m]


# --- Extractor de SolidWorks falso: apunta la ruta y "cuesta" 10 s de reloj ---
LLAMADAS = []
TIEMPO = [0.0]


def _png_b64():
    from PIL import Image
    im = Image.new("RGB", (8, 8), (200, 30, 30))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


PNG = _png_b64()


def extractor_falso(filepath, preview=False, masa=True):
    LLAMADAS.append(filepath)
    TIEMPO[0] += 10
    props = {"MATERIAL": "S275JR", "__PREVIEW_PNG__": PNG}
    if filepath.lower().endswith(".sldasm"):
        props["__COMPONENTES__"] = [r"C:\x\26003.P271 Otra pieza.SLDPRT",
                                    "26003.P270 Ángulo montaje inductivo.SLDPRT"]
    return props


EXTRACTOR_REAL = rd.extraer_sw_props
rd.extraer_sw_props = extractor_falso

# --- El NAS de mentira ------------------------------------------------------
TMP = os.path.realpath(tempfile.mkdtemp(prefix="alsi_recup_"))
BASE = os.path.join(TMP, "ALSI PROYECTOS APROBADOS")
AHORA = time.time()
VIEJO = int(AHORA - 60 * 86400)
RECIENTE = int(AHORA - 1 * 86400)
PROY = r"LA ÑECA\26003 LÍNEA CALIBRADO\012 DISTRIBUIDOR CAJAS"
CREADAS = []   # todo lo que se crea, para limpiar la BD por ruta exacta (por índice)


def crear(rel, mtime=VIEJO, contenido=b"contenido de prueba"):
    p = os.path.join(BASE, rel)
    os.makedirs(rd.ruta_larga(os.path.dirname(p)), exist_ok=True)
    with open(rd.ruta_larga(p), "wb") as f:
        f.write(contenido)
    os.utime(rd.ruta_larga(p), (mtime, mtime))
    CREADAS.append(p)
    return p


def ruta_de_largo(rel_carpeta, prefijo, ext, largo):
    """Un nombre de archivo que deja la ruta completa en `largo` caracteres."""
    carpeta = os.path.join(BASE, rel_carpeta)
    relleno = largo - len(carpeta) - 1 - len(prefijo) - len(ext)
    return os.path.join(rel_carpeta, prefijo + "X" * relleno + ext)


A = crear(PROY + r"\MECANICA\26003.P270 Ángulo montaje inductivo.SLDPRT")      # ya indexada
B = crear(PROY + r"\MECANICA\PDF\26003.P270 Ángulo montaje inductivo.PDF")     # el PDF perdido
C = crear(PROY + r"\MECANICA\26003.P271 Otra pieza.SLDPRT")
D = crear(PROY + r"\MECANICA\26003.E001 Conjunto.SLDASM")
E = crear(PROY + r"\MECANICA\26003.P272 Nueva.SLDPRT", RECIENTE)               # reciente, falta
F = crear(PROY + r"\MECANICA\26003.P273 Reciente en BD.SLDPRT", RECIENTE, b"1234567890")
G = crear(PROY + r"\MECANICA\26003.P274 Vieja en BD.SLDPRT")                    # vieja, ya está
EXCLUIDOS = [crear(PROY + r"\MECANICA\BACKUPS\26003.P275.SLDPRT"),
             crear(PROY + r"\MECANICA\~tmp\26003.P276.SLDPRT"),
             crear(PROY + r"\MECANICA\~$26003.P270.SLDPRT"),
             crear(PROY + r"\MECANICA\Thumbs.db"),
             crear(PROY + r"\MECANICA\notas.txt")]
H = crear(ruta_de_largo(PROY + r"\PLIEGO DE CONDICIONES", "26003 Pliego ", ".PDF", 275))
HONDA = "\\".join("SUBCARPETA MUY LARGA %02d %s" % (i, "Y" * 30) for i in range(4))
I = crear(PROY + "\\" + HONDA + r"\26003.P280 Honda.SLDPRT")
J = crear(r"ALSI\PALETIZADOR\MECANICA\PAL.001 Brazo.SLDPRT")                     # sin año
K = crear(r"CLIENTE VIEJO\15012 LINEA VIEJA\001 ORDEN\MECANICA\15012.P001 Eje.SLDPRT")
L = crear(PROY + r"\LAYOUT\26003 Layout general.DWG")
FANTASMA = os.path.join(BASE, PROY, "MECANICA", "26003.P299 Borrada.SLDPRT")     # en BD, no en disco

FALTAN_ESPERADAS = {B, C, D, H, I, J, K, L}


# --- BD real, origen sintético -----------------------------------------------
def limpiar(cu, cn):
    """Todo por índice (origen o ruta exacta): nada de recorrer tablas de la
    oficina enteras. Las rutas cuelgan de una carpeta temporal única, así que
    no pueden coincidir con ninguna de verdad."""
    cn.rollback()
    cu.execute("SELECT ruta_completa FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
    rutas = list({r[0] for r in cu.fetchall()} | set(CREADAS) | {FANTASMA})
    cu.execute("DELETE FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
    cu.execute("DELETE FROM buscador.archivos WHERE ruta_completa = ANY(%s)", (rutas,))
    cu.execute("DELETE FROM buscador.miniaturas WHERE ruta_completa = ANY(%s)", (rutas,))
    cu.execute("DELETE FROM buscador.componentes WHERE ensamblaje_ruta = ANY(%s)", (rutas,))
    cn.commit()


def filas(cu):
    cu.execute("""SELECT ruta_completa FROM buscador.archivos WHERE origen = %s""", (ORIGEN,))
    return {r[0] for r in cu.fetchall()}


def fila(cu, ruta):
    cu.execute("""SELECT anio, cliente, proyecto, tipo_carpeta, extension,
                         ultima_modificacion, tamano_bytes, codigo_proyecto,
                         nombre_orden, sw_material, sw_masa_kg, indexado_en
                  FROM buscador.archivos WHERE ruta_completa = %s""", (ruta,))
    return cu.fetchone()


class StatFalso:
    st_mtime = VIEJO
    st_size = 99


def meter_a_mano(cu, ruta, stats=None):
    carpeta, nombre = os.path.split(ruta)
    md = rd.extraer_metadata_proyecto(carpeta, BASE)
    rd.upsert_archivo(cu, nombre, ORIGEN, md, ruta, stats or os.stat(rd.ruta_larga(ruta)), {})


# ---------------------------------------------------------------------------
def probar_piezas_sueltas():
    titulo("1. RUTAS LARGAS: el prefijo solo para el disco")
    unc = r"\\192.168.1.10\Oficina Tecnica\ALSI PROYECTOS APROBADOS\X\a.pdf"
    comprobar("rutas", "UNC -> \\\\?\\UNC\\...", rd.ruta_larga(unc) == "\\\\?\\UNC\\" + unc[2:])
    comprobar("rutas", "y vuelta a la ruta normal", rd.ruta_normal(rd.ruta_larga(unc)) == unc)
    comprobar("rutas", "disco local -> \\\\?\\C:\\...",
              rd.ruta_larga(r"C:\x\y.pdf") == "\\\\?\\" + r"C:\x\y.pdf")
    comprobar("rutas", "y vuelta", rd.ruta_normal(rd.ruta_larga(r"C:\x\y.pdf")) == r"C:\x\y.pdf")
    comprobar("rutas", "una ruta ya larga no se dobla",
              rd.ruta_larga(rd.ruta_larga(unc)) == rd.ruta_larga(unc))
    comprobar("rutas", "una ruta normal no cambia al 'normalizarla'", rd.ruta_normal(unc) == unc)

    comprobar("rutas", "el árbol de prueba tiene una carpeta de 260+",
              len(os.path.dirname(I)) >= 260, "%d caracteres" % len(os.path.dirname(I)))
    viejo = {os.path.join(r, f) for r, _d, fs in os.walk(BASE) for f in fs}
    comprobar("rutas", "con el os.walk de antes esa carpeta ni se ve", I not in viejo)
    try:
        os.stat(H)
        stat_normal_falla = False
    except OSError:
        stat_normal_falla = True
    comprobar("rutas", "y os.stat sin prefijo falla con 260+ (MAX_PATH)", stat_normal_falla,
              "%d caracteres" % len(H))

    titulo("2. EL RECORRIDO COMÚN")
    vistos = {ruta for _r, _f, ruta in rd.recorrer_nas(BASE)}
    comprobar("recorrido", "ve la carpeta honda y el nombre largo", I in vistos and H in vistos)
    comprobar("recorrido", "devuelve rutas normales, nunca con prefijo",
              not any(v.startswith("\\\\?\\") for v in vistos))
    comprobar("recorrido", "deja fuera BACKUPS, ~carpetas, ~$, Thumbs y .txt",
              not (set(EXCLUIDOS) & vistos))
    errores = []
    fantasma = os.path.join(TMP, "NO EXISTE")
    comprobar("recorrido", "una carpeta que no se puede listar se apunta",
              list(rd.recorrer_nas(fantasma, errores)) == [] and errores == [fantasma],
              repr(errores))

    titulo("3. MISMA BASE: nada de comparar el NAS leído por otro nombre")
    ip = rd.RUTAS_NAS["PROYECTOS"]
    comprobar("base", "por la IP de siempre: sí", rd.misma_base(ip, "PROYECTOS"))
    comprobar("base", "por \\\\NASCENTRAL: no",
              not rd.misma_base(ip.replace("192.168.1.10", "NASCENTRAL"), "PROYECTOS"))

    titulo("4. EL LOG DEL PASE, EN SU SITIO")
    log_tmp = os.path.join(TMP, "reindexacion_prueba.log")
    raiz = logging.getLogger()
    de_antes = raiz.handlers[:]
    raiz.handlers = []          # que la línea de prueba no acabe en app.log
    try:
        h1 = rd._log_propio(log_tmp)
        h2 = rd._log_propio(log_tmp)
        raiz.warning("linea de prueba del log propio")
        h1.flush()
    finally:
        raiz.handlers = de_antes
        h1.close()
    with open(log_tmp, encoding="utf-8") as f:
        texto = f.read()
    comprobar("log", "reindexacion.log recibe lo que se registra",
              "linea de prueba del log propio" in texto)
    comprobar("log", "llamarlo dos veces no duplica el fichero", h1 is h2)
    antes = len(CAPTURA)
    rd._avisar_ilegibles("PRUEBA", [("r%d" % i, OSError("x")) for i in range(8)])
    nuevos = [m for n, m in CAPTURA[antes:] if n >= logging.WARNING]
    comprobar("log", "los ilegibles salen como AVISO (cabecera + 5)", len(nuevos) == 6,
              "%d avisos" % len(nuevos))

    titulo("4b. LA CLAVE DE LICENCIA NO VA AL LOG")
    # Un conjunto que tarda más de 20 s: el mensaje de subprocess trae la línea
    # de comandos entera, clave de Document Manager incluida. Se simula el
    # tiempo agotado; el extractor de verdad no se lanza. La clave no se imprime.
    import subprocess
    run_original = subprocess.run
    vista = []

    def run_que_tarda(cmd, **kw):
        vista.append(cmd[1])
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 20))

    def run_que_falla(cmd, **kw):
        vista.append(cmd[1])
        raise RuntimeError("fallo raro con %s dentro" % cmd[1])

    for texto, falso, esperado in (("tiempo agotado", run_que_tarda, "no respondió en 20 s"),
                                   ("cualquier otro fallo", run_que_falla, "<clave>")):
        del vista[:]
        antes = len(CAPTURA)
        subprocess.run = falso
        try:
            EXTRACTOR_REAL(os.path.join(TMP, "conjunto que tarda.SLDASM"), preview=True)
        finally:
            subprocess.run = run_original
        nuevos = [m for _n, m in CAPTURA[antes:]]
        clave = vista[0] if vista else None
        comprobar("clave", "%s: el aviso sale, sin la clave" % texto,
                  clave and nuevos and not any(clave in m for m in nuevos)
                  and any(esperado in m for m in nuevos),
                  "" if clave else "sin config.ini con clave en este equipo: no se ha podido probar")

    titulo("5. ARGUMENTOS")
    a = rd._leer_argumentos(["--recuperar", "--minutos", "30"])
    comprobar("args", "--recuperar --minutos 30", a.recuperar and a.minutos == 30)
    a = rd._leer_argumentos([])
    comprobar("args", "sin nada: el pase de siempre", not a.recuperar
              and a.minutos == rd.MINUTOS_MAX_PASE)


def probar_extractor(cn, cu):
    """El 25/08 la raíz se quedó con una compilación del extractor anterior a
    --masa y hasta el 18/09 los pases no calcularon el peso de nada nuevo, sin
    que saltara ningún aviso. Esto lo caza."""
    titulo("4c. EL EXTRACTOR DE LA RAÍZ SABE CALCULAR EL PESO")
    exe = os.path.join(RAIZ, "SwPropExtractor.exe")
    binario = open(exe, "rb").read() if os.path.exists(exe) else b""
    fuente = ""
    if os.path.exists(os.path.join(RAIZ, "SwPropExtractor.cs")):
        fuente = open(os.path.join(RAIZ, "SwPropExtractor.cs"), encoding="utf-8",
                      errors="replace").read()
    comprobar("extractor", "el .exe lleva la opción --masa",
              "--masa".encode("utf-16-le") in binario, "%d bytes" % len(binario))
    comprobar("extractor", "y el .cs también (binario y fuente de acuerdo)", "--masa" in fuente)
    comprobar("extractor", "sigue llevando --preview (miniaturas)",
              "--preview".encode("utf-16-le") in binario)

    cu.execute("""SELECT ruta_completa, sw_masa_kg FROM buscador.archivos
                  WHERE origen = 'PROYECTOS' AND extension = '.sldprt'
                    AND sw_masa_kg IS NOT NULL AND length(ruta_completa) < 260
                  ORDER BY id DESC LIMIT 20""")
    for ruta, masa_bd in cu.fetchall():
        if not os.path.exists(ruta):
            continue
        props = EXTRACTOR_REAL(ruta, preview=False, masa=True)
        from models import fisicas_creibles
        masa = fisicas_creibles(props.get("__MASA_KG__"), props.get("__VOLUMEN_M3__"),
                                props.get("__AREA_M2__"))[0]
        comprobar("extractor", "una pieza real del índice vuelve a dar peso", masa is not None,
                  "%s → %s kg (en la BD %s)" % (os.path.basename(ruta)[:28], masa, masa_bd))
        return
    comprobar("extractor", "una pieza real del índice vuelve a dar peso", False,
              "ninguna de las 20 piezas con peso del índice es accesible ahora mismo")


def probar_recuperacion(cn, cu):
    titulo("6. EL PASE DE CADA NOCHE APUNTA LO QUE FALTA")
    meter_a_mano(cu, A)
    meter_a_mano(cu, F)
    meter_a_mano(cu, G)
    meter_a_mano(cu, FANTASMA, StatFalso())
    cu.execute("""UPDATE buscador.archivos SET sw_material = 'NO TOCAR', tamano_bytes = 1,
                  indexado_en = '2020-01-01' WHERE ruta_completa = %s""", (G,))
    cu.execute("""UPDATE buscador.archivos SET tamano_bytes = 1, sw_masa_kg = 12.5
                  WHERE ruta_completa = %s""", (F,))
    cn.commit()
    g_antes = fila(cu, G)

    faltan = []
    rd.indexar_proyectos_recientes(cn, cu, BASE, dias=7, origen=ORIGEN, faltan=faltan)
    apuntadas = {it[2] for it in faltan}
    comprobar("apunta", "apunta justo lo que falta y no es reciente",
              apuntadas == FALTAN_ESPERADAS,
              "sobran %s · faltan %s" % (sorted(os.path.basename(x) for x in apuntadas - FALTAN_ESPERADAS),
                                         sorted(os.path.basename(x) for x in FALTAN_ESPERADAS - apuntadas)))
    comprobar("apunta", "lo reciente que falta entra por el camino de siempre", E in filas(cu))
    f = fila(cu, F)
    comprobar("apunta", "lo reciente que ya estaba se actualiza como siempre",
              f and f[6] == 10, "tamano %s" % (f and f[6]))
    comprobar("apunta", "sin perder la masa ya calculada (COALESCE)", f and float(f[10]) == 12.5)

    titulo("7. RECUPERACIÓN CON TOPE: lo barato y lo reciente primero")
    LLAMADAS.clear()
    TIEMPO[0] = 1000.0
    rec, pend = rd.recuperar_faltantes(cn, cu, ORIGEN, BASE, faltan, hasta=TIEMPO[0] + 25,
                                       reloj=lambda: TIEMPO[0])
    comprobar("tope", "con 25 s de reloj: 3 baratos + 3 SolidWorks", (rec, pend) == (6, 2),
              "recuperados %d, pendientes %d" % (rec, pend))
    ahora = filas(cu)
    comprobar("tope", "el PDF de la P270 ya está en el índice", B in ahora)
    comprobar("tope", "los que se quedan: el de 2015 y el sin año",
              K not in ahora and J not in ahora and {C, D, I, H, L} <= ahora)
    comprobar("tope", "el extractor recibe la ruta NORMAL, nunca con prefijo",
              LLAMADAS and not any(x.startswith("\\\\?\\") for x in LLAMADAS))
    comprobar("tope", "y no se le llama para PDF ni DWG",
              set(LLAMADAS) == {C, D, I}, str([os.path.basename(x) for x in LLAMADAS]))

    faltan = []
    rd.indexar_proyectos_recientes(cn, cu, BASE, dias=7, origen=ORIGEN, faltan=faltan)
    comprobar("tope", "la noche siguiente solo quedan esos dos",
              {it[2] for it in faltan} == {J, K})
    rec, pend = rd.recuperar_faltantes(cn, cu, ORIGEN, BASE, faltan)
    comprobar("tope", "y entran los dos", (rec, pend) == (2, 0), "%d, %d" % (rec, pend))
    faltan = []
    rd.indexar_proyectos_recientes(cn, cu, BASE, dias=7, origen=ORIGEN, faltan=faltan)
    n_antes = len(filas(cu))
    rec, pend = rd.recuperar_faltantes(cn, cu, ORIGEN, BASE, faltan)
    comprobar("tope", "la tercera noche no falta nada y no cambia nada",
              not faltan and (rec, pend) == (0, 0) and len(filas(cu)) == n_antes)

    titulo("8. LO RECUPERADO ESTÁ BIEN")
    b = fila(cu, B)
    comprobar("datos", "PDF: año 2026, LA ÑECA, 26003 LÍNEA CALIBRADO",
              b and b[0] == 2026 and b[1] == "LA ÑECA" and b[2] == "26003 LÍNEA CALIBRADO", str(b and b[:3]))
    comprobar("datos", "PDF: MECANICA, .pdf, orden DISTRIBUIDOR CAJAS",
              b and b[3] == "MECANICA" and b[4] == ".pdf" and b[8] == "DISTRIBUIDOR CAJAS")
    comprobar("datos", "fecha y tamaño los del disco",
              b and b[5] == VIEJO and b[6] == len(b"contenido de prueba"))
    c = fila(cu, C)
    comprobar("datos", "pieza: propiedades de SolidWorks", c and c[9] == "S275JR")
    cu.execute("SELECT count(*) FROM buscador.miniaturas WHERE ruta_completa = %s", (C,))
    comprobar("datos", "pieza: su miniatura", cu.fetchone()[0] == 1)
    cu.execute("""SELECT componente_nombre FROM buscador.componentes
                  WHERE ensamblaje_ruta = %s ORDER BY 1""", (D,))
    comps = [r[0] for r in cu.fetchall()]
    comprobar("datos", "conjunto: sus componentes, por nombre",
              comps == ["26003.P270 ÁNGULO MONTAJE INDUCTIVO.SLDPRT", "26003.P271 OTRA PIEZA.SLDPRT"],
              str(comps))
    j = fila(cu, J)
    comprobar("datos", "carpeta sin número de proyecto: año 0, cliente ALSI",
              j and j[0] == 0 and j[1] == "ALSI")
    comprobar("datos", "ruta de 275: guardada tal cual, sin prefijo", H in filas(cu), "%d" % len(H))
    comprobar("datos", "carpeta de 260+: guardada tal cual", I in filas(cu), "%d" % len(I))

    titulo("9. SOLO AÑADE: lo que ya estaba no se toca")
    comprobar("añade", "la pieza vieja que ya estaba, idéntica", fila(cu, G) == g_antes,
              str(fila(cu, G)[9:]))
    comprobar("añade", "la fila de un archivo borrado sigue ahí (no borra)", FANTASMA in filas(cu))
    md = rd.extraer_metadata_proyecto(os.path.dirname(G), BASE)
    escrito = rd.upsert_archivo(cu, os.path.basename(G), ORIGEN, md, G, os.stat(rd.ruta_larga(G)),
                                {"MATERIAL": "OTRO", "__COMPONENTES__": ["X.SLDPRT"]},
                                solo_si_nuevo=True)
    cn.commit()
    cu.execute("SELECT count(*) FROM buscador.componentes WHERE ensamblaje_ruta = %s", (G,))
    comps_g = cu.fetchone()[0]
    comprobar("añade", "solo_si_nuevo sobre una fila que existe: no escribe nada",
              escrito is False and fila(cu, G) == g_antes and comps_g == 0)
    cu.execute("""SELECT count(*), count(DISTINCT ruta_completa),
                         count(*) FILTER (WHERE strpos(ruta_completa, '?') > 0)
                  FROM buscador.archivos WHERE origen = %s""", (ORIGEN,))
    n, distintas, con_prefijo = cu.fetchone()
    esperadas = len({A, F, G, FANTASMA, E} | FALTAN_ESPERADAS)
    comprobar("añade", "ni duplicados ni prefijos colados",
              n == distintas == esperadas and con_prefijo == 0,
              "%d filas, %d distintas, %d con '?'" % (n, distintas, con_prefijo))

    titulo("10. UN ARCHIVO QUE FALLA NO SE LLEVA A LOS DEMÁS")
    m1 = crear(PROY + r"\MECANICA\26003.P281 Uno.PDF")
    m2 = crear(PROY + r"\MECANICA\26003.P282 Dos.PDF")
    m3 = crear(PROY + r"\MECANICA\26003.P283 Tres.PDF")
    original = rd.upsert_archivo

    def upsert_que_revienta(cursor, file, *args, **kw):
        if file == os.path.basename(m2):
            cursor.execute("SELECT 1 / 0")        # un error de verdad de PostgreSQL
        return original(cursor, file, *args, **kw)

    rd.upsert_archivo = upsert_que_revienta
    try:
        faltan = []
        rd.indexar_proyectos_recientes(cn, cu, BASE, dias=7, origen=ORIGEN, faltan=faltan)
        rec, _p = rd.recuperar_faltantes(cn, cu, ORIGEN, BASE, faltan)
    finally:
        rd.upsert_archivo = original
    ahora = filas(cu)
    comprobar("aislado", "los otros dos entran", rec == 2 and m1 in ahora and m3 in ahora)
    comprobar("aislado", "el que falla no entra y queda para otra noche", m2 not in ahora)
    comprobar("aislado", "y se avisa", bool(avisos("P282")))
    cu.execute("SELECT 1")
    comprobar("aislado", "la conexión sigue viva", cu.fetchone() == (1,))

    titulo("11. NUNCA CON OTRA FORMA DE RUTA")
    fuera = os.path.join(TMP, "OTRO SITIO", "26003.P290 Fuera.PDF")
    CREADAS.append(fuera)
    os.makedirs(os.path.dirname(fuera))
    with open(fuera, "wb") as f:
        f.write(b"x")
    st = os.stat(fuera)
    rec, _p = rd.recuperar_faltantes(cn, cu, ORIGEN, BASE,
                                     [(os.path.dirname(fuera), os.path.basename(fuera), fuera, st)])
    comprobar("forma", "una ruta que no cuelga de la base no entra",
              rec == 0 and fuera not in filas(cu))
    raro = "\\\\?\\" + B
    rec, _p = rd.recuperar_faltantes(cn, cu, ORIGEN, BASE,
                                     [(os.path.dirname(B), os.path.basename(B), raro, st)])
    comprobar("forma", "una ruta con el prefijo largo tampoco", rec == 0 and raro not in filas(cu))

    titulo("12. LA PURGA DE LOS VIERNES VE LO MISMO")
    n_antes = len(filas(cu))
    borradas = rd.purgar_rutas_huerfanas(cn, cu, ORIGEN, BASE)
    ahora = filas(cu)
    comprobar("purga", "borra la fila del archivo que ya no existe",
              borradas == 1 and FANTASMA not in ahora, "%d borradas" % borradas)
    comprobar("purga", "y NO lo que la recuperación sacó de rutas largas",
              H in ahora and I in ahora and len(ahora) == n_antes - 1)
    rd.RUTAS_NAS[ORIGEN] = BASE
    try:
        n_antes = len(filas(cu))
        borradas = rd.purgar_rutas_huerfanas(cn, cu, ORIGEN, BASE.upper())
    finally:
        del rd.RUTAS_NAS[ORIGEN]
    comprobar("purga", "leído por otro nombre: no purga nada",
              borradas == 0 and len(filas(cu)) == n_antes and avisos("PURGA %s OMITIDA" % ORIGEN))

    titulo("13. A MANO: python reindexar_diario.py --recuperar")
    n1 = crear(PROY + r"\MECANICA\26003.P291 A mano.SLDPRT")
    log_original = rd.LOG_FILE
    rd.LOG_FILE = os.path.join(TMP, "reindexacion_a_mano.log")
    try:
        codigo_cero = rd.main_recuperar(minutos=0, origen=ORIGEN, ruta=BASE)
        sin_tiempo = n1 not in filas(cu)
        codigo = rd.main_recuperar(minutos=5, origen=ORIGEN, ruta=BASE)
    finally:
        for h in list(logging.getLogger().handlers):
            if getattr(h, "baseFilename", "").startswith(TMP):
                logging.getLogger().removeHandler(h)
                h.close()
        rd.LOG_FILE = log_original
    comprobar("a mano", "con 0 minutos no mete nada", codigo_cero == 0 and sin_tiempo)
    comprobar("a mano", "con tiempo, lo mete", codigo == 0 and n1 in filas(cu))


# --- El pase entero, contra una BD falsa en memoria --------------------------
class BDFalsa:
    def __init__(self):
        self.rutas = {}
        self.sentencias = []


class CursorFalso:
    def __init__(self, bd):
        self.bd = bd
        self.rowcount = 0
        self._res = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.bd.sentencias.append(s)
        self.rowcount = 0
        self._res = []
        if s.startswith("SELECT ruta_completa FROM buscador.archivos WHERE origen"):
            self._res = [(r,) for r in self.bd.rutas.get(params[0], set())]
        elif s.startswith("SELECT count(*) FROM buscador.archivos WHERE origen"):
            self._res = [(len(self.bd.rutas.get(params[0], ())),)]
        elif s.startswith("SELECT column_name FROM information_schema"):
            self._res = [("ensamblaje_ruta",), ("componente_nombre",)]
        elif s.startswith("INSERT INTO buscador.archivos"):
            ruta, origen = params[6], params[1]
            ya = any(ruta in rs for rs in self.bd.rutas.values())
            if not ("DO NOTHING" in s and ya):
                self.bd.rutas.setdefault(origen, set()).add(ruta)
                self.rowcount = 1
        elif s.startswith("DELETE FROM buscador.archivos WHERE ruta_completa = ANY"):
            for rs in self.bd.rutas.values():
                rs.difference_update(params[0])

    def executemany(self, sql, seq):
        self.bd.sentencias.append(" ".join(sql.split()))

    def fetchall(self):
        return list(self._res)

    def fetchone(self):
        return self._res[0] if self._res else None


class ConexionFalsa:
    def __init__(self, bd):
        self.bd = bd

    def cursor(self, *a, **k):
        return CursorFalso(self.bd)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def probar_pase_entero():
    titulo("14. EL PASE ENTERO (BD falsa): la recuperación va la última")
    raiz = os.path.join(TMP, "NAS PASE")
    rutas = {"BIBLIOTECA_3D": os.path.join(raiz, "BIBLIOTECA"),
             "ALSI_ESTANDAR": os.path.join(raiz, "ESTANDAR"),
             "PROYECTOS": os.path.join(raiz, "PROYECTOS")}

    def poner(origen, rel, mtime=VIEJO):
        p = os.path.join(rutas[origen], rel)
        os.makedirs(rd.ruta_larga(os.path.dirname(p)), exist_ok=True)
        with open(rd.ruta_larga(p), "wb") as f:
            f.write(b"x")
        os.utime(rd.ruta_larga(p), (mtime, mtime))
        return p

    poner("BIBLIOTECA_3D", r"TORNILLERIA\M16.SLDPRT")
    poner("ALSI_ESTANDAR", r"PERFILES\P40.SLDPRT")
    ya = poner("PROYECTOS", r"CLI\26001 UNO\001 A\MECANICA\26001.P001.SLDPRT")
    vieja = poner("PROYECTOS", r"CLI\26001 UNO\001 A\MECANICA\PDF\26001.P001.PDF")
    reciente = poner("PROYECTOS", r"CLI\26001 UNO\001 A\MECANICA\26001.P002.SLDPRT", RECIENTE)
    honda = poner("PROYECTOS", r"CLI\26001 UNO\001 A" + "\\" + HONDA + r"\26001.P003.SLDPRT")

    guardado = dict(rd.RUTAS_NAS), rd.psycopg2.connect, rd.actualizar_placas_ce, \
        rd.MINUTOS_MAX_PASE, rd.LOG_FILE
    resultados = {}
    try:
        rd.RUTAS_NAS.clear()
        rd.RUTAS_NAS.update(rutas)
        rd.actualizar_placas_ce = lambda conn, cur: 0
        rd.LOG_FILE = os.path.join(TMP, "reindexacion_pase.log")
        for minutos in (0, 100):
            bd = BDFalsa()
            bd.rutas["PROYECTOS"] = {ya}
            rd.psycopg2.connect = lambda **kw: ConexionFalsa(bd)
            rd.MINUTOS_MAX_PASE = minutos
            del CAPTURA[:]
            rd.main()
            resultados[minutos] = (bd, list(CAPTURA))
    finally:
        rd.RUTAS_NAS.clear()
        rd.RUTAS_NAS.update(guardado[0])
        rd.psycopg2.connect, rd.actualizar_placas_ce, rd.MINUTOS_MAX_PASE, rd.LOG_FILE = guardado[1:]
        for h in list(logging.getLogger().handlers):
            if getattr(h, "baseFilename", "").startswith(TMP):
                logging.getLogger().removeHandler(h)
                h.close()

    bd, log = resultados[100]
    sent = bd.sentencias
    i_estado = max(i for i, s in enumerate(sent) if "estado_indexacion" in s)
    i_recup = [i for i, s in enumerate(sent) if s.startswith("INSERT INTO buscador.archivos")
               and "DO NOTHING" in s]
    comprobar("pase", "recupera lo viejo que falta, también la carpeta honda",
              {vieja, honda} <= bd.rutas["PROYECTOS"] and len(i_recup) == 2,
              "%d inserciones de recuperación" % len(i_recup))
    comprobar("pase", "lo reciente entra por el camino de siempre", reciente in bd.rutas["PROYECTOS"])
    comprobar("pase", "la recuperación va DESPUÉS del sello de 'última indexación'",
              i_recup and min(i_recup) > i_estado)
    comprobar("pase", "BIBLIOTECA y ESTÁNDAR se indexan como siempre",
              len(bd.rutas.get("BIBLIOTECA_3D", ())) == 1 and len(bd.rutas.get("ALSI_ESTANDAR", ())) == 1)
    comprobar("pase", "el resumen final cuenta los recuperados",
              any("REINDEXACIÓN COMPLETADA" in m and "2 recuperados" in m for _n, m in log))
    bd0, log0 = resultados[0]
    i_recup0 = [s for s in bd0.sentencias if "DO NOTHING" in s]
    comprobar("pase", "sin tiempo: no recupera nada y lo deja dicho",
              not i_recup0 and any("quedan 2 para la próxima noche" in m for _n, m in log0))
    comprobar("pase", "pero el resto del pase se hace entero",
              any("estado_indexacion" in s for s in bd0.sentencias)
              and reciente in bd0.rutas["PROYECTOS"])


def resumen():
    print()
    print("=" * 72)
    fallos = [r for r in RESULTADOS if not r[2]]
    porbloque = {}
    for bloque, _t, ok, _d in RESULTADOS:
        acum = porbloque.setdefault(bloque, [0, 0])
        acum[0] += 1
        acum[1] += 1 if ok else 0
    for bloque, (total, ok) in porbloque.items():
        print("  %-12s %d/%d" % (bloque, ok, total))
    print("-" * 72)
    print("  TOTAL: %d de %d" % (len(RESULTADOS) - len(fallos), len(RESULTADOS)))
    if fallos:
        print()
        print("  FALLOS:")
        for _b, t, _ok, d in fallos:
            print("    - %s %s" % (t, ("(%s)" % d) if d else ""))
    print("=" * 72)
    return 0 if not fallos else 1


def main():
    print("PRUEBAS DEL PASE NOCTURNO: recuperación y rutas largas")
    print("NAS de mentira en %s" % TMP)
    try:
        cn = psycopg2.connect(**PG_CONFIG)
    except Exception as e:
        print("  Sin conexión con la base de datos (%s). Se abortan." % e)
        return 2
    cu = cn.cursor()
    try:
        limpiar(cu, cn)
        probar_piezas_sueltas()
        probar_extractor(cn, cu)
        probar_recuperacion(cn, cu)
        probar_pase_entero()
    except Exception:
        import traceback
        traceback.print_exc()
        RESULTADOS.append(("error", "la batería se ha parado por una excepción", False, ""))
    finally:
        try:
            limpiar(cu, cn)
            cu.execute("SELECT count(*) FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
            quedan = cu.fetchone()[0]
            comprobar("limpieza", "no queda ni una fila de prueba en la BD", quedan == 0)
        finally:
            cn.close()
            shutil.rmtree(rd.ruta_larga(TMP), ignore_errors=True)
    return resumen()


if __name__ == "__main__":
    sys.exit(main())
