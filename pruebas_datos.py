# -*- coding: utf-8 -*-
"""Pruebas de la capa de datos y de la configuracion (V2.1.1).

No necesitan interfaz, asi que corren en segundos y se pueden lanzar en
cualquier momento, incluso con la app abierta:

    python pruebas_datos.py

Cubren lo que la bateria de robustez no puede mirar de cerca: como responde la
base de datos a entradas raras, que hacen los dialogos cuando el dato no esta,
y que hace la app ante un config.ini malo.
"""
import os
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

RESULTADOS = []
B = chr(92)
NL = chr(10)


def comprobar(bloque, texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((bloque, texto, ok, detalle))
    print("  %-56s %s%s" % (texto, "OK" if ok else "FALLO",
                            ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


def sin_reventar(bloque, texto, fn, validar=None, detalle_ok=None):
    """Ejecuta fn(); pasa si no lanza excepcion y (si se pide) valida el
    resultado. Cualquier excepcion es un fallo con su tipo y mensaje."""
    try:
        r = fn()
    except Exception as e:
        return comprobar(bloque, texto, False,
                         "%s: %s" % (type(e).__name__, str(e).splitlines()[0][:60]))
    if validar is not None and not validar(r):
        return comprobar(bloque, texto, False, "resultado inesperado: %r" % (r,))
    return comprobar(bloque, texto, True,
                     detalle_ok(r) if detalle_ok else "")


# ---------------------------------------------------------------------------
def probar_entradas_raras(db):
    """Lo que un companero puede escribir en el buscador sin querer."""
    titulo("1. ENTRADAS RARAS EN LA BUSQUEDA")
    casos = [
        ("acentos y ene", "PLETINA MONTAJE AÑO"),
        ("mayusculas mezcladas", "TuErCa M16"),
        ("espacios de sobra", "   tuerca    m16   "),
        ("termino larguisimo (300 caracteres)", "x" * 300),
        ("solo simbolos", "!@#$%^&*()"),
        ("comodines de SQL sin escapar", "100%_pieza"),
        ("intento de inyeccion SQL", "'; DROP TABLE buscador.archivos; --"),
        ("comillas dobles", 'pieza "especial"'),
        ("barra invertida", "carpeta" + B + "pieza"),
        ("cadena vacia", ""),
        ("solo espacios", "     "),
        ("salto de linea dentro del termino", "tuerca" + NL + "m16"),
    ]
    for nombre, termino in casos:
        sin_reventar("raras", "%s -> responde sin reventar" % nombre,
                     lambda t=termino: db.buscar(t),
                     validar=lambda r: isinstance(r, list),
                     detalle_ok=lambda r: "%d resultados" % len(r))

    sin_reventar("raras", "la tabla sigue intacta tras el intento de inyeccion",
                 lambda: db.buscar("tuerca m16"),
                 validar=lambda r: len(r) > 0,
                 detalle_ok=lambda r: "%d resultados" % len(r))


def probar_dialogos(db):
    """Los dialogos de resultados, con datos que no existen."""
    titulo("2. CONSULTAS DE LOS DIALOGOS CON DATOS AUSENTES")
    fantasma = B + B + "NOEXISTE" + B + "nada" + B + "fantasma.SLDPRT"
    pruebas = [
        ("ensamblajes que usan una ruta inexistente",
         lambda: db.buscar_ensamblajes_de(fantasma)),
        ("componentes de un ensamblaje inexistente",
         lambda: db.obtener_componentes_de(fantasma)),
        ("miniaturas de rutas inexistentes",
         lambda: db.obtener_miniaturas_lote([fantasma, ""])),
        ("miniaturas de una lista vacia",
         lambda: db.obtener_miniaturas_lote([])),
        ("filtrar por componente sin rutas",
         lambda: db.filtrar_por_componente([], "motor")),
        ("piezas identicas de una ruta inexistente",
         lambda: db.piezas_identicas(fantasma)),
        ("ensamblajes similares de una ruta inexistente",
         lambda: db.ensamblajes_similares(fantasma)),
    ]
    for nombre, fn in pruebas:
        if not hasattr(db, fn.__code__.co_names[-1]) and False:
            continue
        sin_reventar("dialogos", "%s -> vacio, no error" % nombre, fn,
                     validar=lambda r: r is not None and len(r) == 0)


def probar_configuracion():
    """config.ini: la app no debe morir por una configuracion mala."""
    titulo("3. CONFIGURACION (config.ini)")
    import models
    malos = [
        ("vacio", ""),
        ("sin la seccion [database]", "[otra]" + NL + "x = 1"),
        ("sin el puerto", "[database]" + NL + "host = 1.2.3.4" + NL +
         "dbname = a" + NL + "user = b" + NL + "password = c"),
        ("con el puerto no numerico", "[database]" + NL + "host = 1.2.3.4" + NL +
         "port = XX" + NL + "dbname = a" + NL + "user = b" + NL + "password = c"),
        ("con el host vacio", "[database]" + NL + "host = " + NL + "port = 5433" +
         NL + "dbname = a" + NL + "user = b" + NL + "password = c"),
        ("que no es un ini", "esto no es un ini, es texto suelto"),
    ]
    for nombre, contenido in malos:
        ruta = os.path.join(tempfile.gettempdir(), "alsi_cfg_malo.ini")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        sin_reventar("config", "un config.ini %s se descarta" % nombre,
                     lambda r=ruta: models._leer_config(r),
                     validar=lambda r: r is None)

    bueno = ("[database]" + NL + "host = 1.2.3.4" + NL + "port = 5433" + NL +
             "dbname = a" + NL + "user = b" + NL + "password = c" + NL +
             "connect_timeout = 9")
    ruta = os.path.join(tempfile.gettempdir(), "alsi_cfg_bueno.ini")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(bueno)
    cfg = models._leer_config(ruta)
    comprobar("config", "un config.ini valido se lee entero",
              cfg is not None and cfg.get("host") == "1.2.3.4")
    comprobar("config", "connect_timeout se puede ajustar desde config.ini",
              cfg and cfg.get("connect_timeout") == 9,
              str(cfg.get("connect_timeout")) if cfg else "")
    comprobar("config", "si no se indica, connect_timeout vale 5 s",
              models._entero(None, 5) == 5 and models._entero("0", 5) == 5
              and models._entero("abc", 5) == 5)
    comprobar("config", "siempre lleva keepalives para detectar cortes de red",
              cfg and cfg.get("keepalives") == 1)


def probar_conexion(models):
    """Los topes de tiempo y el modo tolerante."""
    titulo("4. CONEXION: TOPES DE TIEMPO Y MODO TOLERANTE")
    import copy
    import psycopg2
    malo = copy.deepcopy(models.PG_CONFIG)
    malo["host"] = "192.0.2.1"          # RFC 5737: existe pero no contesta

    t0 = time.time()
    try:
        psycopg2.connect(**malo)
        comprobar("conexion", "un servidor que no responde falla, no cuelga", False,
                  "conecto (inesperado)")
    except Exception:
        seg = time.time() - t0
        comprobar("conexion", "un servidor que no responde falla en ~5 s",
                  4.0 <= seg <= 8.0, "%.1fs (antes ~21s)" % seg)

    real = models.PG_CONFIG
    models.PG_CONFIG = malo
    try:
        t0 = time.time()
        db = models.IndexManager(tolerante=True)
        comprobar("conexion", "en modo tolerante la app NO muere sin servidor",
                  not db.esta_disponible(), "%.1fs" % (time.time() - t0))
        comprobar("conexion", "guarda el motivo para poder ensenarlo",
                  db.ultimo_error is not None)
        # Aqui SI se espera una excepcion, y ademas una concreta: la interfaz
        # distingue "no hay servidor" de un fallo de programacion por el tipo.
        try:
            db.get_connection()
            comprobar("conexion", "pedir conexion lanza SinConexionBD", False,
                      "no lanzo nada")
        except models.SinConexionBD:
            comprobar("conexion", "pedir conexion lanza SinConexionBD", True)
        except Exception as e:
            comprobar("conexion", "pedir conexion lanza SinConexionBD", False,
                      "lanzo %s" % type(e).__name__)
        comprobar("conexion", "una preferencia cae a su valor por defecto",
                  db.obtener_preferencia("xyz", "DEFECTO") == "DEFECTO")
        comprobar("conexion", "guardar una preferencia no revienta",
                  db.guardar_preferencia("xyz", "1") is None)

        t0 = time.time()
        db2 = models.IndexManager(tolerante=True, diferido=True)
        comprobar("conexion", "en modo diferido no se toca la red al construir",
                  db2._pool is None and (time.time() - t0) < 0.5,
                  "%.2fs" % (time.time() - t0))

        try:
            models.IndexManager()
            comprobar("conexion", "los pases nocturnos SIGUEN abortando sin servidor",
                      False, "no lanzo excepcion")
        except Exception as e:
            comprobar("conexion", "los pases nocturnos SIGUEN abortando sin servidor",
                      True, type(e).__name__)
    finally:
        models.PG_CONFIG = real

    comprobar("conexion", "SinConexionBD es un error de base de datos normal",
              issubclass(models.SinConexionBD, psycopg2.Error))
    t0 = time.time()
    db = models.IndexManager(tolerante=True)
    comprobar("conexion", "con el servidor real vuelve a conectar",
              db.esta_disponible(), "%.1fs" % (time.time() - t0))
    ok, _motivo = db.reconectar()
    comprobar("conexion", "reconectar() funciona con el servidor bien", ok)


def probar_consultas(db):
    """Que las consultas de siempre siguen dando lo mismo."""
    titulo("5. CONSULTAS DE SIEMPRE")
    for termino, minimo in (("tuerca m16", 1), ("pletina", 10), ("cinta", 10),
                            ("chasis", 5)):
        t0 = time.time()
        r = db.buscar(termino)
        comprobar("consultas", "buscar '%s'" % termino, len(r) >= minimo,
                  "%d en %.2fs" % (len(r), time.time() - t0))
    comprobar("consultas", "una busqueda sin resultados devuelve lista vacia",
              db.buscar("zzzz-no-existe-zzzz") == [])
    t0 = time.time()
    r = db.buscar("cinta")
    comprobar("consultas", "las busquedas grandes siguen siendo rapidas",
              time.time() - t0 < 3.0, "%.2fs para %d filas" % (time.time() - t0, len(r)))
    a = db.buscar("tuerca m16")
    b = db.buscar("tuerca m16")
    comprobar("consultas", "repetir una busqueda da exactamente lo mismo",
              [x[10] for x in a] == [x[10] for x in b],
              "%d filas" % len(a))


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
    import models
    print("PRUEBAS DE DATOS Y CONFIGURACION - Buscador de Piezas ALSI")
    print("Servidor: %s:%s" % (models.PG_CONFIG.get("host"),
                               models.PG_CONFIG.get("port")))
    db = models.IndexManager(tolerante=True)
    if not db.esta_disponible():
        print()
        print("  No hay conexion con la base de datos: %s" % db.ultimo_error)
        print("  Estas pruebas necesitan el servidor. Se abortan.")
        return 2
    probar_entradas_raras(db)
    probar_dialogos(db)
    probar_configuracion()
    probar_conexion(models)
    probar_consultas(db)
    return resumen()


if __name__ == "__main__":
    sys.exit(main())
