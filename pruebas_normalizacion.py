# -*- coding: utf-8 -*-
"""Pruebas de que el término de búsqueda y el nombre del archivo se normalizan
IGUAL (21/09/2026).

    python pruebas_normalizacion.py

Por qué existen: buscar `rodillo Ø50` devolvía 0 resultados y `rodillo o50`,
390. Y `curva 90º`, 0, frente a 3.082 de `curva 90`. El término se normalizaba
en Python con NFKD y el nombre en la base con unaccent, y no coinciden en 12
caracteres que están en los nombres de verdad: Ø (8.521 archivos), º (2.300),
ª (601), ø, ¾, espacio duro, ´, ¡, ±, ×, ®, Ð.

Son de solo lectura: consultan el servidor de verdad (SELECT y EXPLAIN), no
escriben nada y no abren la ventana. La muestra se elige del propio índice con
la misma regla que usa el producto.
"""
import os
import sys
import time

os.environ.setdefault("ALSI_SIN_PREFERENCIAS", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import psycopg2                                              # noqa: E402
import models                                                # noqa: E402
from models import PG_CONFIG, NOMBRE_NORM                    # noqa: E402

# La batería vigila el COMPORTAMIENTO, no cómo esté escrito por dentro: si un
# día desaparece la constante, estas pruebas tienen que seguir corriendo (y
# suspender), no reventar al importar.
PATRON_NORM = getattr(models, "PATRON_NORM",
                      "('%%' || UPPER(buscador.sin_tildes(%s)) || '%%')")

ORIGENES = ['PROYECTOS', 'BIBLIOTECA_3D', 'ALSI_ESTANDAR']
EXTS = ['.sldprt', '.sldasm', '.slddrw', '.dwg', '.pdf', '.step', '.stp', '.iges', '.igs']
RESULTADOS = []


def comprobar(bloque, texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((bloque, texto, ok, detalle))
    print("  %-58s %s%s" % (texto, "OK" if ok else "FALLO",
                            ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


def limpio(nombre):
    """Un nombre que se puede buscar tal cual: sin los separadores de la
    gramática (',' ';') ni un guion que abra palabra, que EXCLUYE."""
    base = os.path.splitext(nombre)[0]
    return not any(c in base for c in ',;') and ' -' not in base and not base.startswith('-')


def muestra_con(cu, caracter, cuantos=4):
    cu.execute("""SELECT nombre_archivo, ruta_completa FROM buscador.archivos
                  WHERE strpos(nombre_archivo, %s) > 0 ORDER BY id LIMIT 400""", (caracter,))
    filas = [(n, r) for n, r in cu.fetchall() if limpio(n)]
    return filas[:: max(1, len(filas) // cuantos)][:cuantos]


def probar_caracteres(cu):
    titulo("1. LA APP Y LA BASE NORMALIZAN IGUAL")
    cu.execute("""SELECT ch, count(*) FROM (
                    SELECT DISTINCT id, ch FROM (
                      SELECT id, regexp_split_to_table(nombre_archivo, '') AS ch
                      FROM buscador.archivos) s
                    WHERE ascii(ch) > 127) t
                  GROUP BY ch ORDER BY 2 DESC""")
    presentes = cu.fetchall()
    distintos = []
    for ch, n in presentes:
        cu.execute("SELECT upper(buscador.sin_tildes(%s))", (ch,))
        if cu.fetchone()[0] != models.IndexManager.normalizar_texto(ch):
            distintos.append((ch, n))
    comprobar("caracteres", "ningún carácter del índice se normaliza distinto",
              not distintos,
              "%d no ASCII mirados · descuadran: %s" % (len(presentes),
                                                        [c for c, _ in distintos] or "ninguno"))
    comprobar("caracteres", "y se han mirado los que hay de verdad", len(presentes) >= 40,
              "%d caracteres distintos" % len(presentes))
    for ch, esperado in (('Ø', 'O'), ('ø', 'O'), ('Ð', 'D'), ('¡', '!'), ('×', '*')):
        comprobar("caracteres", "«%s» pasa a «%s», como unaccent" % (ch, esperado),
                  models.IndexManager.normalizar_texto(ch) == esperado)
    for ch in ('º', 'ª', '´'):
        comprobar("caracteres", "«%s» se queda como está, como unaccent" % ch,
                  models.IndexManager.normalizar_texto(ch) == ch)
    comprobar("caracteres", "las tildes se siguen quitando",
              models.IndexManager.normalizar_texto("Ángulo peñón") == "ANGULO PENON")


def probar_busquedas(db, cu):
    titulo("2. LO QUE ANTES DABA CERO")
    def n(t, años=None):
        return len(db.buscar(t, compañeros=ORIGENES, años=años, extensiones=EXTS))

    for con, sin in (('rodillo Ø50', 'rodillo o50'), ('tubo Ø20', 'tubo o20')):
        a, b = n(con), n(sin)
        comprobar("buscar", "«%s» encuentra lo mismo que «%s»" % (con, sin),
                  a == b and a > 0, "%d y %d resultados" % (a, b))
    con_grado = n('curva 90º')
    comprobar("buscar", "«curva 90º» encuentra curvas", con_grado > 0,
              "%d resultados" % con_grado)
    comprobar("buscar", "y son menos que «curva 90» a secas", 0 < con_grado < n('curva 90'))

    titulo("3. NOMBRES REALES DEL ÍNDICE, BUSCADOS TAL CUAL")
    for ch in ('Ø', 'º', 'ª', 'Ñ'):
        filas = muestra_con(cu, ch)
        if not filas:
            comprobar("nombres", "hay nombres con «%s» para probar" % ch, False)
            continue
        encontrados = 0
        for nombre, ruta in filas:
            rutas = [f[10] for f in db.buscar(os.path.splitext(nombre)[0],
                                              compañeros=ORIGENES, años=None, extensiones=EXTS)]
            encontrados += ruta in rutas
        comprobar("nombres", "con «%s»: cada archivo sale por su nombre exacto" % ch,
                  encontrados == len(filas), "%d de %d" % (encontrados, len(filas)))

    titulo("4. LA GRAMÁTICA DE SIEMPRE NO CAMBIA")
    comprobar("gramática", "';' sigue exigiendo todas las palabras", n('cinta;450') > 0)
    comprobar("gramática", "',' sigue ampliando", n('cinta,tapa') >= n('cinta;450'))
    con, sin_inox = n('rodillo Ø50'), n('rodillo Ø50;-inox')
    comprobar("gramática", "'-palabra' quita, también con Ø", 0 < sin_inox <= con,
              "%d → %d" % (con, sin_inox))
    comprobar("gramática", "un código con guion no se toma por exclusión", n('26003.P270') > 0)
    comprobar("gramática", "los comodines de SQL no rompen nada", n('100%_pieza') >= 0)
    comprobar("gramática", "una inyección SQL no devuelve nada ni revienta",
              n("'; DROP TABLE buscador.archivos; --") == 0)
    cu.execute("SELECT count(*) FROM buscador.archivos")
    comprobar("gramática", "y la tabla sigue en su sitio", cu.fetchone()[0] > 600000)


def probar_componentes(db, cu):
    titulo("5. CONJUNTOS QUE LLEVAN UNA PIEZA CON Ø")
    cu.execute("""SELECT componente_nombre, count(*) FROM buscador.componentes
                  WHERE strpos(componente_nombre, 'Ø') > 0
                  GROUP BY 1 ORDER BY 2 DESC LIMIT 20""")
    filas = [(n, c) for n, c in cu.fetchall() if limpio(n)]
    if not filas:
        comprobar("conjuntos", "hay componentes con Ø para probar", False)
        return
    nombre, usos = filas[0]
    termino = os.path.splitext(nombre)[0]
    conjuntos = db.buscar_ensamblajes_que_contienen(termino, compañeros=ORIGENES) \
        if hasattr(db, 'buscar_ensamblajes_que_contienen') else None
    if conjuntos is None:
        wrapper = db.get_connection()
        try:
            cur = wrapper._conn.cursor()
            directos = db._rutas_que_contienen(cur, termino, False)
        finally:
            wrapper.close()
        comprobar("conjuntos", "los conjuntos que llevan «%s…»" % termino[:26],
                  len(directos) > 0, "%d conjuntos (la tabla dice %d usos)" % (len(directos), usos))
    else:
        comprobar("conjuntos", "los conjuntos que llevan «%s…»" % termino[:26],
                  len(conjuntos) > 0, "%d conjuntos" % len(conjuntos))


def probar_plan(cu):
    titulo("6. EL ÍNDICE GIN SE SIGUE USANDO")
    sql = f"SELECT count(*) FROM buscador.archivos WHERE {NOMBRE_NORM} LIKE {PATRON_NORM}"
    t0 = time.time()
    cu.execute("EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) " + sql, ('rodillo Ø50',))
    plan = "\n".join(r[0] for r in cu.fetchall())
    comprobar("plan", "el plan entra por idx_ba_nombre_norm_trgm",
              "idx_ba_nombre_norm_trgm" in plan)
    comprobar("plan", "y no recorre la tabla entera", "Seq Scan on archivos" not in plan)
    comprobar("plan", "la consulta tarda menos de 1 s", time.time() - t0 < 1.0,
              "%.0f ms" % ((time.time() - t0) * 1000))


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
    print("PRUEBAS DE NORMALIZACIÓN: que Ø, º y ª se busquen como se escriben")
    try:
        cn = psycopg2.connect(**PG_CONFIG)
        cn.set_session(readonly=True)
    except Exception as e:
        print("  Sin conexión con la base de datos (%s). Se abortan." % e)
        return 2
    cu = cn.cursor()
    db = models.IndexManager(tolerante=True)
    try:
        probar_caracteres(cu)
        probar_busquedas(db, cu)
        probar_componentes(db, cu)
        probar_plan(cu)
    finally:
        cn.close()
    return resumen()


if __name__ == "__main__":
    sys.exit(main())
