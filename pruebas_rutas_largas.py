# -*- coding: utf-8 -*-
r"""Pruebas de los LECTORES con rutas de 260 caracteres o más (18/11/2026).

    python pruebas_rutas_largas.py

Por qué existen: las 4.407 piezas, conjuntos y planos con ruta de 260+ no tenían
miniatura (el 100 %), ni material, ni peso; y 2.196 PDF y 864 DWG tampoco. El
recorrido del NAS ya entraba en esas carpetas desde el 18/09, pero los que LEEN
el archivo no: SwPropExtractor (.NET 4) dice "File not found", Document Manager
falla aunque se le pase el prefijo \\?\, y el pase de miniaturas preguntaba
os.path.exists() sin prefijo, que da False, y se saltaba la pieza.

El arreglo: models.ruta_legible copia el archivo a una carpeta temporal LOCAL,
se lee la copia y se borra. El original solo se lee.

No toca la base de datos ni el NAS: las rutas largas se crean en una carpeta
temporal de este equipo, y el extractor y la BD son de mentira.
"""
import os
import sys
import shutil
import tempfile
import time

os.environ.setdefault("ALSI_SIN_PREFERENCIAS", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import models                         # noqa: E402
from models import ruta_larga, ruta_legible, LARGO_MAX   # noqa: E402
import reindexar_diario as rd         # noqa: E402
import poblar_propiedades as pp       # noqa: E402

RESULTADOS = []
TMP = tempfile.mkdtemp(prefix="pruebas_largas_")

# El log del pase de miniaturas es el de producción: las fases de mentira de
# esta batería no deben aparecer en él.
import logging   # noqa: E402
for _h in list(pp.log.handlers):
    if isinstance(_h, logging.FileHandler):
        pp.log.removeHandler(_h)
        _h.close()


def comprobar(bloque, texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((bloque, texto, ok, detalle))
    print("  %-62s %s%s" % (texto, "OK" if ok else "FALLO",
                            ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


def crear(largo, nombre="26001.P001 Pletina.SLDPRT", contenido=b"pieza de prueba"):
    """Un archivo cuya ruta mide `largo` caracteres (o más, si el nombre no cabe)."""
    base = os.path.join(TMP, "C")
    relleno = max(1, largo - len(base) - len(nombre) - 2)
    carpetas = []
    while relleno > 0:
        trozo = min(relleno, 80)
        carpetas.append("D" * max(1, trozo - 1))
        relleno -= trozo
    carpeta = os.path.join(base, *carpetas)
    os.makedirs(ruta_larga(carpeta), exist_ok=True)
    ruta = os.path.join(carpeta, nombre)
    with open(ruta_larga(ruta), "wb") as f:
        f.write(contenido)
    os.utime(ruta_larga(ruta), (1_600_000_000, 1_600_000_000))
    return ruta


def temporales_nuestros():
    return [x for x in os.listdir(tempfile.gettempdir())
            if x.startswith(models._PREFIJO_TEMPORAL)]


# ---------------------------------------------------------------------------
def probar_ruta_legible():
    titulo("1. ruta_legible: copia local solo cuando hace falta")
    antes = set(temporales_nuestros())

    corta = crear(120)
    with ruta_legible(corta) as r:
        comprobar("legible", "ruta corta: se usa tal cual, sin copiar", r == corta)
    comprobar("legible", "y no deja carpetas temporales", set(temporales_nuestros()) == antes)

    larga = crear(300)
    comprobar("legible", "la ruta de prueba es larga de verdad", len(larga) >= LARGO_MAX,
              "%d caracteres" % len(larga))
    comprobar("legible", "sin prefijo, Windows no la ve (por eso se saltaba)",
              not os.path.exists(larga))
    with ruta_legible(larga) as r:
        dentro = r
        comprobar("legible", "ruta larga: se lee de una copia de ruta corta",
                  len(r) < LARGO_MAX and os.path.exists(r), "%d caracteres" % len(r))
        comprobar("legible", "la copia conserva el nombre del archivo",
                  os.path.basename(r) == os.path.basename(larga))
        with open(r, "rb") as f:
            comprobar("legible", "y el contenido, byte a byte", f.read() == b"pieza de prueba")
        comprobar("legible", "la copia está fuera del NAS (temporal local)",
                  os.path.abspath(r).startswith(os.path.abspath(tempfile.gettempdir())))
    comprobar("legible", "al salir, la copia se borra", not os.path.exists(dentro))
    comprobar("legible", "y su carpeta también", set(temporales_nuestros()) == antes)

    st = os.stat(ruta_larga(larga))
    with open(ruta_larga(larga), "rb") as f:
        comprobar("legible", "el original sigue intacto (contenido)", f.read() == b"pieza de prueba")
    comprobar("legible", "y con su fecha (solo se ha leído)", int(st.st_mtime) == 1_600_000_000)

    with ruta_legible(ruta_larga(larga)) as r:
        comprobar("legible", "acepta también la ruta ya con prefijo \\\\?\\",
                  os.path.basename(r) == os.path.basename(larga) and os.path.exists(r))

    try:
        with ruta_legible(larga) as r:
            dentro = r
            raise ValueError("el lector revienta")
    except ValueError:
        pass
    comprobar("legible", "si el lector revienta, la copia se borra igual",
              not os.path.exists(dentro) and set(temporales_nuestros()) == antes)

    nombre_largo = "N" * 240 + ".SLDASM"   # un nombre no puede pasar de 255
    muy = crear(320, nombre=nombre_largo)
    with ruta_legible(muy) as r:
        comprobar("legible", "nombre de archivo enorme: copia corta con su extensión",
                  len(r) < LARGO_MAX and r.endswith(".SLDASM") and os.path.exists(r))

    falta = os.path.join(os.path.dirname(larga), "NO EXISTE " + "X" * 20 + ".SLDPRT")
    try:
        with ruta_legible(falta):
            pass
        lanzo = False
    except OSError:
        lanzo = True
    comprobar("legible", "archivo que no existe: avisa con un error, no inventa",
              lanzo and set(temporales_nuestros()) == antes)


# ---------------------------------------------------------------------------
class _Resultado:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


def probar_extractor():
    titulo("2. extraer_sw_props: el extractor recibe una ruta que puede abrir")
    import subprocess
    llamadas = []

    def run_falso(cmd, **kw):
        # cmd = [exe, CLAVE, ruta, ...]: la clave no se apunta ni se imprime
        ruta = cmd[2]
        existe = os.path.exists(ruta)
        contenido = open(ruta, "rb").read() if existe else None
        llamadas.append((ruta, existe, contenido, list(cmd[3:])))
        return _Resultado(b'{"MATERIAL": "S275JR", "__PREVIEW_PNG__": "iVBORw0KGgo="}')

    if not os.path.exists(os.path.expanduser("~/.alsi_busqueda/config.ini")):
        comprobar("extractor", "este equipo tiene la licencia de Document Manager", False,
                  "sin ~/.alsi_busqueda/config.ini no se puede probar")
        return
    original = subprocess.run
    subprocess.run = run_falso
    try:
        larga = crear(290, nombre="25005.P050 Soporte encoder.SLDPRT", contenido=b"SW larga")
        props = rd.extraer_sw_props(larga, preview=True)
        ruta, existe, contenido, extra = llamadas[-1]
        comprobar("extractor", "ruta larga: le llega una de menos de 260",
                  len(ruta) < LARGO_MAX, "%d caracteres" % len(ruta))
        comprobar("extractor", "que existe mientras lee", existe)
        comprobar("extractor", "y es el mismo archivo", contenido == b"SW larga")
        comprobar("extractor", "se le siguen pidiendo miniatura y peso",
                  extra == ["--preview", "--masa"], str(extra))
        comprobar("extractor", "devuelve las propiedades (antes: nada)",
                  props.get("MATERIAL") == "S275JR" and "__PREVIEW_PNG__" in props)
        comprobar("extractor", "la copia ya no existe al terminar", not os.path.exists(ruta))

        corta = crear(140, nombre="26001.P002.SLDPRT", contenido=b"SW corta")
        rd.extraer_sw_props(corta, preview=False, masa=False)
        comprobar("extractor", "ruta corta: le llega exactamente la misma ruta",
                  llamadas[-1][0] == corta and llamadas[-1][3] == [])
    finally:
        subprocess.run = original


# ---------------------------------------------------------------------------
class CursorApuntador:
    def __init__(self, filas=()):
        self.sql = []
        self._filas = list(filas)
        self._res = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.sql.append((s, params))
        if s.startswith("SELECT count(*)"):
            self._res = [(len(self._filas),)]
        elif s.startswith("SELECT id, ruta_completa") or s.startswith("SELECT a.id, a.ruta_completa"):
            self._res = list(self._filas)
        else:
            self._res = []

    def fetchone(self):
        return self._res[0] if self._res else None

    def fetchall(self):
        return list(self._res)


class ConexionApuntadora:
    def commit(self):
        pass

    def close(self):
        pass


def probar_pase_miniaturas():
    titulo("3. poblar_propiedades: ya no se salta las rutas largas")
    guardado = (pp.en_horario_laboral, rd.extraer_sw_props, rd.guardar_miniatura_bd,
                pp.leer_checkpoint, pp.guardar_checkpoint)
    vistas = []
    try:
        pp.en_horario_laboral = lambda: False
        pp.leer_checkpoint = lambda nombre: 0
        pp.guardar_checkpoint = lambda nombre, i: None
        rd.extraer_sw_props = lambda ruta, preview=False, masa=True: (
            vistas.append(ruta) or {"MATERIAL": "AISI 304"})
        rd.guardar_miniatura_bd = lambda cur, ruta, props, mtime: True

        larga = crear(275, nombre="23018.P102 Banda corta.SLDPRT")
        corta = crear(150, nombre="23018.P103.SLDPRT")
        cur = CursorApuntador([(1, larga, 1), (2, corta, 1)])
        pp.procesar_fase(ConexionApuntadora(), cur, "FASE1 prueba", (".sldprt",), "x.checkpoint")
        comprobar("pase", "la pieza de ruta larga pasa por el extractor", larga in vistas)
        comprobar("pase", "y la corta, como siempre", corta in vistas)
        upd = [p for s, p in cur.sql if s.startswith("UPDATE buscador.archivos")]
        comprobar("pase", "se guardan las propiedades de las dos", len(upd) == 2)

        cur = CursorApuntador([])
        pp.procesar_fase(ConexionApuntadora(), cur, "FASE2b", (".sldprt",), "x.checkpoint",
                         solo_largas=True)
        comprobar("pase", "la fase de rutas largas solo pide las de 260+",
                  all("length(ruta_completa) >= 260" in s for s, _p in cur.sql if "FROM buscador.archivos" in s))
        cur = CursorApuntador([])
        pp.procesar_fase(ConexionApuntadora(), cur, "FASE1", (".sldprt",), "x.checkpoint")
        comprobar("pase", "y las fases de siempre no se restringen",
                  not any("length(" in s for s, _p in cur.sql))

        # PDF y DWG: el renderizador recibe una ruta que puede abrir
        recibidas = []

        def render(ruta):
            recibidas.append((ruta, os.path.exists(ruta), open(ruta, "rb").read()))
            return b"\xff\xd8jpeg"
        pdf = crear(310, nombre="25011.P166 Plano.PDF", contenido=b"%PDF-1.4 prueba")
        cur = CursorApuntador([(7, pdf, 1)])
        pp.procesar_minis(ConexionApuntadora(), cur, "FASE4 pdf", (".pdf",), render)
        r, existe, cont = recibidas[-1]
        comprobar("pase", "PDF de ruta larga: el render recibe una ruta corta que existe",
                  len(r) < LARGO_MAX and existe and cont == b"%PDF-1.4 prueba")
        ins = [p for s, p in cur.sql if s.startswith("INSERT INTO buscador.miniaturas")]
        comprobar("pase", "y la miniatura se guarda con la ruta NORMAL del índice",
                  len(ins) == 1 and ins[0][0] == pdf)
        comprobar("pase", "la copia del PDF se ha borrado", not os.path.exists(r))
    finally:
        (pp.en_horario_laboral, rd.extraer_sw_props, rd.guardar_miniatura_bd,
         pp.leer_checkpoint, pp.guardar_checkpoint) = guardado

    titulo("4. el orden de las fases")
    orden = []
    guardado = (pp.procesar_fase, pp.procesar_minis, pp.en_horario_laboral, pp.psycopg2.connect)
    try:
        pp.en_horario_laboral = lambda: False

        class _Con(ConexionApuntadora):
            def cursor(self):
                return CursorApuntador()
        pp.psycopg2.connect = lambda **kw: _Con()
        pp.procesar_fase = lambda conn, cur, nombre, ext, chk, con_props=True, solo_largas=False: (
            orden.append((nombre, chk, solo_largas)) or True)
        pp.procesar_minis = lambda conn, cur, nombre, ext, fn, cada_pausa=50: (
            orden.append((nombre, None, False)) or True)
        pp.main()
    finally:
        pp.procesar_fase, pp.procesar_minis, pp.en_horario_laboral, pp.psycopg2.connect = guardado
    nombres = [o[0] for o in orden]
    comprobar("orden", "las rutas largas van después de las fases 1 y 2, antes de DWG/PDF",
              nombres[:3] == ["FASE1 prt/asm", "FASE2 slddrw", "FASE2b rutas largas"]
              and nombres[3:] == ["FASE3 dwg", "FASE4 pdf"], " → ".join(nombres))
    largas = [o for o in orden if o[0] == "FASE2b rutas largas"]
    comprobar("orden", "con su propio checkpoint (relee las viejas una sola vez)",
              largas and largas[0][1] == "poblar_largas.checkpoint" and largas[0][2] is True)
    comprobar("orden", "que no es el de las fases 1 y 2",
              len({o[1] for o in orden if o[1]}) == 3)


def resumen():
    print()
    print("=" * 74)
    fallos = [r for r in RESULTADOS if not r[2]]
    print("  %d pruebas · %d OK · %d FALLO" % (len(RESULTADOS), len(RESULTADOS) - len(fallos), len(fallos)))
    for b, t, _ok, d in fallos:
        print("   FALLO [%s] %s %s" % (b, t, d))
    print("=" * 74)
    return 1 if fallos else 0


def main():
    try:
        probar_ruta_legible()
        probar_extractor()
        probar_pase_miniaturas()
    except Exception:
        import traceback
        traceback.print_exc()
        RESULTADOS.append(("error", "la batería se ha parado por una excepción", False, ""))
    finally:
        shutil.rmtree(ruta_larga(TMP), ignore_errors=True)
        comprobar("limpieza", "no queda la carpeta de pruebas", not os.path.exists(TMP))
    return resumen()


if __name__ == "__main__":
    sys.exit(main())
