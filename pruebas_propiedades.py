# -*- coding: utf-8 -*-
"""Pruebas de cómo se leen las propiedades de SolidWorks (23/10/2026).

    python pruebas_propiedades.py

Por qué existen: 26046.P261 Soporte inductivo M18 es GALVANIZADO y en el
índice salía sin material. La propiedad estaba escrita 'Material' y los tres
sitios que traducen propiedades la buscaban por su nombre exacto ('MATERIAL').
Le pasaba a 18 de cada 100 piezas con plantilla ALSI y sin material.

Cómo trabajan sin tocar nada de nadie: la BD es la real pero con un ORIGEN
SINTÉTICO, que la app no enseña y que se borra al acabar; los archivos son de
mentira, en una carpeta temporal; el extractor se sustituye por uno falso,
salvo en una comprobación que lee UNA pieza real del NAS en solo lectura.
"""
import inspect
import os
import re
import shutil
import sys
import tempfile

os.environ.setdefault("ALSI_SIN_PREFERENCIAS", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import psycopg2                                        # noqa: E402
import models                                          # noqa: E402
from models import (PG_CONFIG, PROPIEDADES_SW, valor_propiedad, valores_sw,  # noqa: E402
                    es_expresion_sw)
import reindexar_diario as rd                          # noqa: E402

ORIGEN = "PRUEBA_PROPIEDADES"
COLUMNAS = [c for c, _ in PROPIEDADES_SW]
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


# ---------------------------------------------------------------------------
def probar_traduccion():
    titulo("1. EL NOMBRE DE LA PROPIEDAD DA IGUAL CÓMO ESTÉ ESCRITO")
    for nombre in ('MATERIAL', 'Material', 'material', 'MATERIAL ', ' Material', 'MATERIAl'):
        comprobar("nombre", "%-12r → GALVANIZADO" % nombre,
                  valor_propiedad({nombre: 'GALVANIZADO'}, 'MATERIAL') == 'GALVANIZADO')
    for nombre in ('LÁSER', 'LASER', 'Láser', 'laser'):
        comprobar("nombre", "%-12r cuenta como LÁSER" % nombre,
                  valor_propiedad({nombre: 'SÍ'}, 'LÁSER') == 'SÍ')
    comprobar("nombre", "'Cangilón' cuenta como CANGILÓN",
              valor_propiedad({'Cangilón': 'NO'}, 'CANGILÓN') == 'NO')
    comprobar("nombre", "'Tipo de cierre' cuenta como TIPO DE CIERRE",
              valor_propiedad({'Tipo  de cierre': 'C'}, 'TIPO DE CIERRE') == 'C')

    titulo("2. QUÉ CUENTA COMO VACÍO")
    comprobar("vacío", "una propiedad vacía no es un valor",
              valor_propiedad({'MATERIAL': ''}, 'MATERIAL') is None)
    comprobar("vacío", "solo espacios tampoco", valor_propiedad({'MATERIAL': '   '}, 'MATERIAL') is None)
    for expr in ('"SW-Material@26046.P261 Soporte.SLDPRT"',
                 'fromparent+"SW-Material@17009.530.P237 Lateral.SLDPRT"'):
        comprobar("vacío", "una expresión sin evaluar no es un material",
                  valor_propiedad({'Material': expr}, 'MATERIAL') is None and es_expresion_sw(expr),
                  expr[:34])
    comprobar("vacío", "un material normal no es una expresión", not es_expresion_sw('AISI 304'))
    comprobar("vacío", "sin propiedades → nada", valor_propiedad(None, 'MATERIAL') is None
              and valor_propiedad({}, 'MATERIAL') is None)
    comprobar("vacío", "las claves internas (__...) no cuentan",
              valor_propiedad({'__MATERIAL': 'X'}, 'MATERIAL') is None)

    titulo("3. SI HAY DOS, MANDA EL NOMBRE DE SIEMPRE")
    comprobar("orden", "'MATERIAL' con valor gana a 'Material'",
              valor_propiedad({'MATERIAL': 'AISI 304', 'Material': 'ST-37'}, 'MATERIAL') == 'AISI 304')
    comprobar("orden", "pero si 'MATERIAL' está vacío, vale 'Material'",
              valor_propiedad({'MATERIAL': '', 'Material': 'GALVANIZADO'}, 'MATERIAL') == 'GALVANIZADO')
    comprobar("orden", "el valor se guarda tal cual, sin recortar (como siempre)",
              valor_propiedad({'Material': ' AISI 304 '}, 'MATERIAL') == ' AISI 304 ')
    p = {'Material': 'GALVANIZADO', 'ESPESOR': '3', 'Láser': 'SÍ', 'MONTAJE': 'SÍ',
         'CÓDIGO': 'PZS.P048', '__MASA_KG__': 1.2}
    v = dict(zip(COLUMNAS, valores_sw(p)))
    comprobar("orden", "la pieza del ejemplo completa, columna a columna",
              v['sw_material'] == 'GALVANIZADO' and v['sw_espesor'] == '3'
              and v['sw_laser'] == 'SÍ' and v['sw_montaje'] == 'SÍ' and v['sw_torno'] is None,
              str({k: x for k, x in v.items() if x}))


def columnas_del_sql(texto):
    """Las columnas sw_* en el orden en que aparecen en un INSERT/UPDATE."""
    vistas = []
    for c in re.findall(r"\b(sw_[a-z_]+)\b", texto):
        if c in COLUMNAS and c not in vistas:
            vistas.append(c)
    return vistas


def probar_tres_sitios():
    titulo("4. LOS TRES SITIOS TRADUCEN IGUAL")
    import poblar_propiedades as pp
    fuente_rd = inspect.getsource(rd.upsert_archivo)
    with open(os.path.join(RAIZ, "controllers.py"), encoding="utf-8") as f:
        fuente_ctrl = f.read()
    insert_ctrl = fuente_ctrl[fuente_ctrl.find("INSERT INTO buscador.archivos"):]
    insert_ctrl = insert_ctrl[:insert_ctrl.find("VALUES")]
    for etiqueta, texto in (("pase de cada noche", fuente_rd[:fuente_rd.find("VALUES")]),
                            ("pase de propiedades", pp.UPDATE_SQL),
                            ("«Reindexar NAS» de la app", insert_ctrl)):
        orden = columnas_del_sql(texto)
        comprobar("sitios", "%s: columnas en el orden de la traducción" % etiqueta,
                  orden == COLUMNAS, "" if orden == COLUMNAS else str(orden))
    for nombre in ("reindexar_diario.py", "poblar_propiedades.py", "controllers.py"):
        with open(os.path.join(RAIZ, nombre), encoding="utf-8") as f:
            fuente = f.read()
        comprobar("sitios", "%s ya no busca 'MATERIAL' por su nombre exacto" % nombre,
                  ".get('MATERIAL')" not in fuente and "valores_sw" in fuente)
    p = {'Material': 'AISI 430', 'Láser': 'SÍ', 'TRATAMIENTO': 'GALVANIZADO EN CALIENTE'}
    comprobar("sitios", "el pase de propiedades da lo mismo que la traducción común",
              tuple(pp.valores_sw(p)[:len(COLUMNAS)]) == valores_sw(p))


# ---------------------------------------------------------------------------
def probar_en_la_base(cn, cu, tmp):
    titulo("5. CON LA BASE DE DATOS DE VERDAD (origen sintético)")
    ruta = os.path.join(tmp, "CLI", "26999 PRUEBA", "001 A", "MECANICA", "26999.P001 Soporte.SLDPRT")
    os.makedirs(os.path.dirname(ruta))
    with open(ruta, "wb") as f:
        f.write(b"x")
    md = rd.extraer_metadata_proyecto(os.path.dirname(ruta), tmp)
    rd.upsert_archivo(cu, os.path.basename(ruta), ORIGEN, md, ruta, os.stat(ruta),
                      {'Material': 'GALVANIZADO', 'Láser': 'SÍ', 'ESPESOR': '3'})
    cn.commit()
    cu.execute("SELECT sw_material, sw_laser, sw_espesor FROM buscador.archivos WHERE ruta_completa = %s",
               (ruta,))
    fila = cu.fetchone()
    comprobar("base", "el pase guarda 'Material' como material",
              fila == ('GALVANIZADO', 'SÍ', '3'), str(fila))


def probar_relleno(cn, cu, tmp):
    titulo("6. EL RELLENO: SOLO HUECOS, NUNCA UN VALOR BUENO")
    import poblar_material as pm
    carpeta = os.path.join(tmp, "puntos_de_control")
    os.makedirs(carpeta)
    base = os.path.join(tmp, "RELLENO")
    casos = {   # nombre -> (extensión, columnas en la BD, lo que "dice" el archivo)
        "gana":        (".SLDPRT", {}, {'Material': 'GALVANIZADO'}),
        "no_pisa":     (".SLDPRT", {'sw_espesor': '5'}, {'Material': 'AISI 304', 'ESPESOR': '3'}),
        "expresion":   (".SLDPRT", {'sw_material': '"SW-Material@x.SLDPRT"'}, {'Material': 'AISI 430'}),
        "expr_vacia":  (".SLDPRT", {'sw_material': 'fromparent+"SW-Material@y.SLDPRT"'}, {'NOMBRE': 'z'}),
        "sin_nada":    (".SLDPRT", {}, {'NOMBRE': 'pieza sin material'}),
        "con_valor":   (".SLDPRT", {'sw_material': 'ST-37'}, {'Material': 'OTRO'}),
        "conjunto":    (".SLDASM", {}, {'Material': 'ST-37', 'MONTAJE': 'SÍ'}),
    }
    rutas, dice = {}, {}
    for nombre, (ext, cols, props) in casos.items():
        r = os.path.join(base, "CLI", "26998 RELLENO", "001 A", "MECANICA", "26998.%s%s" % (nombre, ext))
        os.makedirs(os.path.dirname(r), exist_ok=True)
        with open(r, "wb") as f:
            f.write(b"x")
        md = rd.extraer_metadata_proyecto(os.path.dirname(r), base)
        rd.upsert_archivo(cu, os.path.basename(r), ORIGEN, md, r, os.stat(r), {})
        if cols:
            sets = ", ".join("%s = %%s" % c for c in cols)
            cu.execute("UPDATE buscador.archivos SET %s WHERE ruta_completa = %%s" % sets,
                       tuple(cols.values()) + (r,))
        rutas[nombre], dice[r] = r, props
    cn.commit()
    leidos = []

    def extractor_falso(ruta, preview=False, masa=False):
        leidos.append(ruta)
        return dict(dice.get(ruta, {}))

    totales = dict(leidos=0, material_ganado=0, expresiones_limpiadas=0, otras_rellenadas=0,
                   sin_cambios=0, sin_propiedades=0, inaccesibles=0, errores=0)
    # 1º: en horario de oficina no hace nada y deja el punto de control
    parado = pm.procesar_fase(cn, cu, "piezas", ".sldprt", totales, origen=ORIGEN,
                              extraer=extractor_falso, en_horario=lambda: True, carpeta=carpeta)
    comprobar("relleno", "en horario de oficina se para sin leer nada",
              parado is False and not leidos and pm.leer_checkpoint(carpeta, "piezas").isdigit())
    # 2º: fuera de horario, piezas y luego conjuntos
    ok1 = pm.procesar_fase(cn, cu, "piezas", ".sldprt", totales, origen=ORIGEN,
                           extraer=extractor_falso, en_horario=lambda: False, carpeta=carpeta)
    ok2 = pm.procesar_fase(cn, cu, "conjuntos", ".sldasm", totales, origen=ORIGEN,
                           extraer=extractor_falso, en_horario=lambda: False, carpeta=carpeta)
    comprobar("relleno", "termina las dos fases", ok1 and ok2)

    def fila(nombre):
        cu.execute("SELECT sw_material, sw_espesor, sw_montaje FROM buscador.archivos "
                   "WHERE ruta_completa = %s", (rutas[nombre],))
        return cu.fetchone()

    comprobar("relleno", "la pieza con 'Material' gana su material",
              fila("gana")[0] == 'GALVANIZADO', str(fila("gana")))
    comprobar("relleno", "rellena el material SIN pisar un espesor que ya estaba",
              fila("no_pisa") == ('AISI 304', '5', None), str(fila("no_pisa")))
    comprobar("relleno", "una expresión se cambia por el material de verdad",
              fila("expresion")[0] == 'AISI 430', str(fila("expresion")))
    comprobar("relleno", "una expresión sin material detrás se vacía",
              fila("expr_vacia")[0] is None, str(fila("expr_vacia")))
    comprobar("relleno", "una pieza sin material sigue sin él", fila("sin_nada")[0] is None)
    comprobar("relleno", "un material que ya estaba ni se lee ni se toca",
              fila("con_valor")[0] == 'ST-37' and rutas["con_valor"] not in leidos)
    comprobar("relleno", "los conjuntos van en su propia fase",
              fila("conjunto") == ('ST-37', None, 'SÍ'), str(fila("conjunto")))
    comprobar("relleno", "las cuentas cuadran",
              totales["material_ganado"] == 4 and totales["expresiones_limpiadas"] == 2
              and totales["sin_cambios"] == 1,
              "ganados %(material_ganado)d · expresiones %(expresiones_limpiadas)d · "
              "sin cambios %(sin_cambios)d" % totales)
    antes = len(leidos)
    otra = pm.procesar_fase(cn, cu, "piezas", ".sldprt", totales, origen=ORIGEN,
                            extraer=extractor_falso, en_horario=lambda: False, carpeta=carpeta)
    comprobar("relleno", "una vez terminada, no vuelve a leer nada",
              otra is True and len(leidos) == antes)


def probar_pieza_real():
    titulo("7. LA PIEZA DEL EJEMPLO, LEÍDA DEL NAS (solo lectura)")
    cn = psycopg2.connect(**PG_CONFIG)
    cn.set_session(readonly=True)
    cu = cn.cursor()
    cu.execute("""SELECT ruta_completa FROM buscador.archivos
                  WHERE nombre_archivo = '26046.P261 Soporte inductivo M18 transportador.SLDPRT'
                  LIMIT 1""")
    r = cu.fetchone()
    cn.close()
    if not r or not os.path.exists(r[0]):
        comprobar("real", "26046.P261 está en el índice y se puede leer", False)
        return
    v = dict(zip(COLUMNAS, valores_sw(rd.extraer_sw_props(r[0], preview=False, masa=False))))
    comprobar("real", "26046.P261 sale GALVANIZADO", v['sw_material'] == 'GALVANIZADO',
              str(v['sw_material']))


# ---------------------------------------------------------------------------
def limpiar(cn, cu, rutas_tmp):
    cn.rollback()
    cu.execute("SELECT ruta_completa FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
    rutas = [x[0] for x in cu.fetchall()] + rutas_tmp
    cu.execute("DELETE FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
    cu.execute("DELETE FROM buscador.miniaturas WHERE ruta_completa = ANY(%s)", (rutas,))
    cu.execute("DELETE FROM buscador.componentes WHERE ensamblaje_ruta = ANY(%s)", (rutas,))
    cn.commit()


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
    print("PRUEBAS DE PROPIEDADES: 'Material' es 'MATERIAL'")
    probar_traduccion()
    probar_tres_sitios()
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="alsi_props_"))
    try:
        cn = psycopg2.connect(**PG_CONFIG)
    except Exception as e:
        print("  Sin conexión con la base de datos (%s)." % e)
        return 2
    cu = cn.cursor()
    try:
        limpiar(cn, cu, [])
        probar_en_la_base(cn, cu, tmp)
        probar_relleno(cn, cu, tmp)
        probar_pieza_real()
    except Exception:
        import traceback
        traceback.print_exc()
        RESULTADOS.append(("error", "la batería se ha parado por una excepción", False, ""))
    finally:
        try:
            todas = [os.path.join(r, f) for r, _d, fs in os.walk(tmp) for f in fs]
            limpiar(cn, cu, todas)
            cu.execute("SELECT count(*) FROM buscador.archivos WHERE origen = %s", (ORIGEN,))
            comprobar("limpieza", "no queda ni una fila de prueba en la BD", cu.fetchone()[0] == 0)
        finally:
            cn.close()
            shutil.rmtree(tmp, ignore_errors=True)
    return resumen()


if __name__ == "__main__":
    sys.exit(main())
