# -*- coding: utf-8 -*-
r"""Pruebas del botón «Reindexar NAS» de la app (v2.3.5).

    python pruebas_indexador.py

Por qué existen: el 04-05/11/2026 alguien pulsó «Reindexar NAS» y PROYECTOS se
quedó sin nada de 2013 a 2027 (567.000 archivos). El botón BORRABA primero y
recorría el NAS después; se canceló o el equipo no llegó al NAS, y lo borrado
se quedó borrado. Desde la v2.3.5 lee primero y solo quita lo que, tras una
lectura completa, de verdad no está en el disco.

Se prueba el hilo de verdad (IndexadorThread.run), con:
  - un NAS de mentira en una carpeta temporal, con rutas de más de 260;
  - la BD real con un ORIGEN SINTÉTICO, que la app no enseña y se borra al acabar;
  - el extractor de SolidWorks cambiado por uno falso;
  - y el paso final de placas CE anulado: si no, reescribiría la tabla de
    placas de producción leyendo los Excel reales.
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("ALSI_SIN_PREFERENCIAS", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

from PyQt5.QtCore import QCoreApplication     # noqa: E402
import psycopg2                               # noqa: E402
import models                                 # noqa: E402
from models import PG_CONFIG, ruta_larga      # noqa: E402
import controllers                            # noqa: E402

APP = QCoreApplication.instance() or QCoreApplication(sys.argv)
ORIGEN = "PRUEBA_INDEXADOR"
RESULTADOS = []


def comprobar(bloque, texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((bloque, texto, ok, detalle))
    print("  %-62s %s%s" % (texto, "OK" if ok else "FALLO",
                            ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


# --- Lo que no se puede tocar de verdad --------------------------------------
LEIDOS = []
ACCION_AL_LEER = {}          # nombre de archivo -> función que se ejecuta al leerlo


class ExtractorFalso:
    def extract_properties(self, ruta):
        LEIDOS.append(ruta)
        nombre = os.path.basename(ruta)
        if nombre in ACCION_AL_LEER:
            ACCION_AL_LEER[nombre]()
        return {"Material": "S275JR"}


controllers.extractor = ExtractorFalso()
controllers.escanear_placas_ce = lambda *a, **k: []     # nada de tocar placas_ce


# --- El NAS de mentira --------------------------------------------------------
TMP = os.path.realpath(tempfile.mkdtemp(prefix="alsi_indexador_"))
BASE = os.path.join(TMP, "ALSI PROYECTOS APROBADOS")


def crear(rel):
    p = os.path.join(BASE, rel)
    os.makedirs(ruta_larga(os.path.dirname(p)), exist_ok=True)
    with open(ruta_larga(p), "wb") as f:
        f.write(b"x")
    return p


HONDA = "\\".join("SUBCARPETA MUY LARGA %02d %s" % (i, "Y" * 30) for i in range(4))
P26 = r"CLI\26999 PRUEBA\001 ORDEN\MECANICA"
P18 = r"CLI\18999 VIEJO\001 ORDEN\MECANICA"
A = crear(P26 + r"\26999.P001 Pieza.SLDPRT")
B = crear(P26 + r"\26999.P002 Otra.SLDPRT")
C = crear(P26 + r"\26999.P003 Plano.PDF")
DEEP = crear(P26 + "\\" + HONDA + r"\26999.P004 Honda.SLDPRT")
VIEJA = crear(P18 + r"\18999.P001 Vieja.SLDPRT")
SIN_ANIO = crear(r"ALSI\PALETIZADOR\PAL.999 Sin año.SLDPRT")
FANTASMA = os.path.join(BASE, P26, "26999.P099 Ya no existe.SLDPRT")
EN_DISCO = {A, B, C, DEEP, VIEJA, SIN_ANIO}


# --- BD real, origen sintético ------------------------------------------------
def cn_cu():
    cn = psycopg2.connect(**PG_CONFIG)
    return cn, cn.cursor()


def limpiar():
    cn, cu = cn_cu()
    cu.execute("SELECT ruta_completa FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
    rutas = [r[0] for r in cu.fetchall()]
    cu.execute("DELETE FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
    cu.execute("DELETE FROM buscador.estado_indexacion WHERE origen = %s", (ORIGEN,))
    cu.execute("DELETE FROM buscador.miniaturas WHERE ruta_completa = ANY(%s)", (rutas,))
    cu.execute("DELETE FROM buscador.componentes WHERE ensamblaje_ruta = ANY(%s)", (rutas,))
    cn.commit()
    cn.close()


def meter(ruta, anio, material="ANTIGUO"):
    """Una fila 'que ya estaba' en el índice."""
    cn, cu = cn_cu()
    cu.execute("""INSERT INTO buscador.archivos (nombre_archivo, origen, anio, ruta_completa,
                                                 extension, sw_material)
                  VALUES (%s, %s, %s, %s, %s, %s)
                  ON CONFLICT (ruta_completa) DO UPDATE SET anio = EXCLUDED.anio,
                                                            sw_material = EXCLUDED.sw_material""",
               (os.path.basename(ruta), ORIGEN, anio, ruta,
                os.path.splitext(ruta)[1].lower(), material))
    cn.commit()
    cn.close()


def filas():
    cn, cu = cn_cu()
    cu.execute("SELECT ruta_completa, anio, sw_material FROM buscador.archivos WHERE origen = %s",
               (ORIGEN,))
    r = {x[0]: (x[1], x[2]) for x in cu.fetchall()}
    cn.close()
    return r


def sello():
    cn, cu = cn_cu()
    cu.execute("SELECT count(*) FROM buscador.estado_indexacion WHERE origen = %s", (ORIGEN,))
    n = cu.fetchone()[0]
    cn.close()
    return n


def pulsar_boton(rutas=None, anios=None, cancelar_al_leer=None, antes=None):
    """Lo mismo que hace la app al pulsar «Reindexar NAS» y aceptar."""
    db = models.IndexManager(tolerante=True)
    t = controllers.IndexadorThread(db, {ORIGEN: rutas or BASE}, [ORIGEN], anios)
    original = t.extraer_metadata
    # El analizador de la app solo saca el año si el origen se llama PROYECTOS.
    t.extraer_metadata = lambda f, r, origen=None, ruta_base=None: original(
        f, r, origen='PROYECTOS', ruta_base=ruta_base)
    ACCION_AL_LEER.clear()
    if cancelar_al_leer:
        ACCION_AL_LEER[os.path.basename(cancelar_al_leer)] = t.cancelar
    if antes:
        antes(t)
    del LEIDOS[:]
    t.run()
    return t


# ---------------------------------------------------------------------------
def probar():
    titulo("1. YA NO SE BORRA NADA ANTES DE LEER")
    with open(os.path.join(RAIZ, "controllers.py"), encoding="utf-8") as f:
        fuente = f.read()
    comprobar("código", "no queda ningún 'DELETE ... WHERE origen' en el indexador",
              "DELETE FROM buscador.archivos WHERE origen" not in fuente)

    titulo("2. CANCELAR A MITAD (lo que pasó el 04/11)")
    limpiar()
    meter(A, 2026); meter(VIEJA, 2018); meter(FANTASMA, 2026)
    pulsar_boton(anios=None, cancelar_al_leer=A)
    f = filas()
    comprobar("cancelar", "lo que ya estaba sigue ahí", {A, VIEJA, FANTASMA} <= set(f),
              "%d filas" % len(f))
    comprobar("cancelar", "ni siquiera el fantasma se quita (no se leyó entero)", FANTASMA in f)
    comprobar("cancelar", "y no se pone el sello de 'índice al día'", sello() == 0)

    titulo("3. EL EQUIPO NO LLEGA AL NAS")
    antes = filas()
    pulsar_boton(rutas=os.path.join(TMP, "NO EXISTE"))
    f = filas()
    comprobar("sin NAS", "no se toca nada: la base queda idéntica", f == antes and FANTASMA in f,
              "%d filas antes y %d después" % (len(antes), len(f)))
    comprobar("sin NAS", "ni se pone el sello", sello() == 0)

    titulo("4. LECTURA COMPLETA: ACTUALIZA Y QUITA SOLO LO QUE NO ESTÁ")
    pulsar_boton()
    f = filas()
    comprobar("completa", "el fantasma (no está en el disco) se quita", FANTASMA not in f)
    comprobar("completa", "lo que está en el disco sigue o entra", EN_DISCO <= set(f),
              "faltan: %s" % [os.path.basename(x) for x in EN_DISCO - set(f)])
    comprobar("completa", "lo que ya estaba se actualiza", f.get(A, (None, None))[1] == "S275JR")
    comprobar("completa", "entra la carpeta de 260+ caracteres, con su ruta normal",
              DEEP in f and len(DEEP) >= 260, "%d caracteres" % len(DEEP))
    comprobar("completa", "ninguna ruta con el prefijo largo colado",
              not any(r.startswith("\\\\?\\") for r in f))
    comprobar("completa", "ahora sí: sello de 'índice al día'", sello() == 1)
    pulsar_boton()
    comprobar("completa", "una segunda pasada no quita nada que exista", EN_DISCO <= set(filas()))

    titulo("5. CON AÑOS MARCADOS")
    meter(FANTASMA, 2026)
    otro = os.path.join(BASE, P18, "18999.P099 Fantasma viejo.SLDPRT")
    meter(otro, 2018)
    sin = os.path.join(BASE, r"ALSI\PALETIZADOR\PAL.998 Fantasma sin año.SLDPRT")
    meter(sin, 0)
    meter(B, 2018)        # año en la BD distinto del de la carpeta (2026)
    pulsar_boton(anios=["2026"])
    f = filas()
    comprobar("años", "quita el fantasma del año marcado", FANTASMA not in f)
    comprobar("años", "no toca los de un año no marcado", otro in f)
    comprobar("años", "ni los sin año", sin in f)
    pulsar_boton(anios=["2018"])
    f = filas()
    comprobar("años", "un archivo que existe nunca se quita, aunque su año no cuadre",
              B in f and otro not in f, "B sigue: %s · fantasma 2018 quitado: %s" % (B in f, otro not in f))

    titulo("6. LAS REDES DE SEGURIDAD")
    for i in range(12):
        meter(os.path.join(BASE, P26, "26999.F%03d Fantasma.SLDPRT" % i), 2026)
    pulsar_boton()
    f = filas()
    fantasmas = [r for r in f if ".F0" in r]
    comprobar("seguridad", "si quitaría más de la mitad, no quita nada", len(fantasmas) == 12,
              "%d filas en total, 12 fantasmas" % len(f))
    limpiar()
    otra_forma = "\\\\NASCENTRAL\\X\\ALSI PROYECTOS APROBADOS\\CLI\\26999.P001 Pieza.SLDPRT"
    meter(otra_forma, 2026)
    pulsar_boton()
    comprobar("seguridad", "una ruta guardada con otro nombre del NAS no se toca",
              otra_forma in filas())

    titulo("7. UN ARCHIVO QUE FALLA NO SE LLEVA A LOS DEMÁS")
    limpiar()

    def revienta(t):
        db = t.db
        original = db.guardar_componentes

        def con_error(cursor, ruta, comps):
            cursor.execute("SELECT 1 / 0")
        db.guardar_componentes = con_error
    asm = crear(P26 + r"\26999.E001 Conjunto.SLDASM")
    EN_DISCO.add(asm)
    controllers.extractor.extract_properties = (
        lambda r: (LEIDOS.append(r), {"Material": "X", "__COMPONENTES__": ["a.SLDPRT"]}
                   if r.lower().endswith(".sldasm") else {"Material": "S275JR"})[1])
    pulsar_boton(antes=revienta)
    f = filas()
    comprobar("aislado", "el resto de archivos entra", (EN_DISCO - {asm}) <= set(f),
              "%d de %d" % (len((EN_DISCO - {asm}) & set(f)), len(EN_DISCO - {asm})))
    comprobar("aislado", "el conjunto cuyo guardado falla sigue en el índice", asm in f)


# ---------------------------------------------------------------------------
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
    print("PRUEBAS DEL BOTÓN «REINDEXAR NAS»: leer primero, quitar solo lo que no está")
    try:
        probar()
    except Exception:
        import traceback
        traceback.print_exc()
        RESULTADOS.append(("error", "la batería se ha parado por una excepción", False, ""))
    finally:
        limpiar()
        cn, cu = cn_cu()
        cu.execute("SELECT count(*) FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
        quedan = cu.fetchone()[0]
        cu.execute("SELECT count(*) FROM buscador.estado_indexacion WHERE origen = %s", (ORIGEN,))
        quedan += cu.fetchone()[0]
        cn.close()
        comprobar("limpieza", "no queda nada de prueba en la BD", quedan == 0)
        shutil.rmtree(ruta_larga(TMP), ignore_errors=True)
    return resumen()


if __name__ == "__main__":
    sys.exit(main())
