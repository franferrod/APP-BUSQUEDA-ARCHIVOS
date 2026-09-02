# -*- coding: utf-8 -*-
"""Pruebas de la exclusion con '-palabra' en la barra de busqueda (V2.1.4).

Lo que se comprueba:
  · la gramatica: que '-banda' excluya y que '26-0006' NO se rompa
  · la consulta real contra el servidor: que lo excluido desaparece de verdad
    y que no desaparece nada mas de la cuenta (se compara con SQL a pelo)
  · que el cliente (refinado por nombre) y el servidor opinan lo mismo
  · el modo "Conjuntos que lo lleven"
  · la interfaz: aviso cuando solo hay exclusiones, chip visible y quitable

    python pruebas_exclusiones.py
"""
import os
import runpy
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ALSI_SIN_DIALOGOS"] = "1"
os.environ["ALSI_SIN_CANDADO"] = "1"
# V2.3.1: las pruebas NO escriben en la tabla de preferencias, que es
# compartida por toda la oficina.
os.environ["ALSI_SIN_PREFERENCIAS"] = "1"
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

INFORME = os.path.join(RAIZ, "pruebas_exclusiones_resultado.txt")
RESULTADOS = []
_f = open(INFORME, "w", encoding="utf-8")

NORM = "UPPER(buscador.sin_tildes(nombre_archivo))"


def emitir(t=""):
    try:
        sys.__stdout__.write(t + "\n")
    except Exception:
        pass
    _f.write(t + "\n")
    _f.flush()


def comprobar(texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((texto, ok, detalle))
    emitir("  %-58s %s%s" % (texto, "OK" if ok else "FALLO",
                             ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    emitir("")
    emitir("-- %s %s" % (t, "-" * max(0, 62 - len(t))))


def main():
    from PyQt5.QtWidgets import QApplication
    salida = {}

    def _exec(self):
        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            win._carga_inicial_diferida()
            t0 = time.time()
            while not win.db.esta_disponible() and time.time() - t0 < 30:
                QApplication.processEvents()
                time.sleep(0.05)
            db = win.db

            # ═══════════════════════════════════════════════════
            titulo("1. LA GRAMATICA")
            # (texto, incluidas, excluidas, modo_and)
            casos = [
                ("cinta; 450;- banda", ["cinta", "450"], ["banda"], True),
                ("cinta;450;-banda", ["cinta", "450"], ["banda"], True),
                ("cinta -banda", ["cinta"], ["banda"], True),
                ("cinta 450 -banda", ["cinta 450"], ["banda"], True),
                ("cinta,-banda,-inox", ["cinta"], ["banda", "inox"], False),
                ("tuerca m16", ["tuerca m16"], [], True),
                ("tuerca;m16", ["tuerca", "m16"], [], True),
                ("tuerca,m16", ["tuerca", "m16"], [], False),
                ("-banda", [], ["banda"], True),
                ("", [], [], True),
            ]
            for texto, inc, exc, es_and in casos:
                r_inc, r_exc, r_and = db.parsear_termino(texto)
                comprobar("'%s'" % texto,
                          r_inc == inc and r_exc == exc and r_and == es_and,
                          "" if (r_inc == inc and r_exc == exc and r_and == es_and)
                          else "sale inc=%r exc=%r and=%s" % (r_inc, r_exc, r_and))

            titulo("1b. EL GUION DE LOS NOMBRES DE VERDAD NO SE TOCA")
            intactos = [
                "26-0006",                    # nº de placa CE
                "AC30-Q6A014",                # referencia de proveedor
                "TAPA - IZQUIERDA",           # guion suelto entre espacios
                "NO USAR - COLORES",          # idem, caso real del indice
                "22057-188 MONTAJE",
            ]
            for texto in intactos:
                inc, exc, _a = db.parsear_termino(texto)
                comprobar("'%s' se busca tal cual" % texto,
                          inc == [texto] and exc == [],
                          "" if (inc == [texto] and exc == []) else "inc=%r exc=%r" % (inc, exc))

            # ═══════════════════════════════════════════════════
            titulo("2. LA BUSQUEDA REAL: LO EXCLUIDO DESAPARECE")
            import collections
            import re as _re
            import psycopg2
            from models import PG_CONFIG
            cx = psycopg2.connect(**PG_CONFIG)
            cur = cx.cursor()

            def contar_sql(donde):
                cur.execute("SELECT count(*) FROM buscador.archivos WHERE " + donde
                            + " AND SUBSTRING(nombre_archivo, 1, 1) != '~'")
                return cur.fetchone()[0]

            def like(p):
                return "%s LIKE '%%%s%%'" % (NORM, p)

            # La palabra a excluir se elige MIRANDO la muestra: tiene que estar
            # en una parte de los resultados, ni en todos ni en ninguno. Si se
            # fija a mano y ese dia no aparece, la prueba pasa sin probar nada.
            base_term = "cinta;450;inox"
            base_sql = " AND ".join([like("CINTA"), like("450"), like("INOX")])
            r_todo = db.buscar(base_term)
            n_base = len(r_todo)
            cuenta = collections.Counter()
            for x in r_todo:
                for w in set(_re.findall("[A-Z0-9]{4,}", db.normalizar_texto(x[0]))):
                    cuenta[w] += 1
            candidatas = sorted(
                [(k, w) for w, k in cuenta.items()
                 if 0.20 * n_base <= k <= 0.60 * n_base
                 and w not in ("SLDPRT", "SLDASM", "SLDDRW")],
                key=lambda t: (-t[0], t[1]))
            comprobar("la muestra da palabras utiles para excluir",
                      len(candidatas) >= 2 and n_base < 5000,
                      "%d candidatas sobre %d archivos" % (len(candidatas), n_base))
            fuera = candidatas[0][1] if candidatas else "PRODUCTO"
            fuera2 = candidatas[1][1] if len(candidatas) > 1 else "LATERAL"

            n_sql_base = contar_sql(base_sql)
            n_con = contar_sql(base_sql + " AND " + like(fuera))
            emitir("  muestra: %s = %d archivos · se excluye '%s' (lo llevan %d)"
                   % (base_term, n_base, fuera, n_con))
            comprobar("hay de verdad algo que excluir",
                      0 < n_con < n_base, "%d de %d" % (n_con, n_base))
            comprobar("sin exclusion salen los mismos que dice el SQL",
                      n_base == n_sql_base, "%d vs %d" % (n_base, n_sql_base))

            term = base_term + ";-" + fuera
            r_sin = db.buscar(term)
            nombres_todo = {x[10] for x in r_todo}
            nombres_sin = {x[10] for x in r_sin}

            comprobar("con la exclusion salen exactamente los que no la llevan",
                      len(r_sin) == n_base - n_con,
                      "%d vs %d" % (len(r_sin), n_base - n_con))
            comprobar("ningun resultado lleva la palabra excluida",
                      not [x for x in r_sin if fuera in db.normalizar_texto(x[0])])
            comprobar("no se ha colado ninguno que antes no estuviera",
                      nombres_sin.issubset(nombres_todo),
                      "%d de %d" % (len(nombres_sin & nombres_todo), len(nombres_sin)))
            comprobar("se ha quitado exactamente lo que se pedia",
                      len(nombres_todo - nombres_sin) == n_con,
                      "%d quitados" % len(nombres_todo - nombres_sin))

            titulo("2b. VARIAS EXCLUSIONES A LA VEZ")
            n_dos = contar_sql(base_sql + " AND NOT " + like(fuera)
                               + " AND NOT " + like(fuera2))
            r_dos = db.buscar("%s;-%s;-%s" % (base_term, fuera, fuera2))
            comprobar("'-%s;-%s' quita las dos cosas" % (fuera.lower(), fuera2.lower()),
                      len(r_dos) == n_dos, "%d vs %d" % (len(r_dos), n_dos))
            comprobar("ningun resultado lleva ninguna de las dos",
                      not [x for x in r_dos
                           if fuera in db.normalizar_texto(x[0])
                           or fuera2 in db.normalizar_texto(x[0])])

            titulo("2c. LA EXCLUSION TAMBIEN MANDA EN LAS BUSQUEDAS 'O'")
            or_sql = "(%s OR %s)" % (like("26067.E023"), like("26067.E144"))
            n_or = contar_sql(or_sql)
            n_or_sin = contar_sql(or_sql + " AND NOT " + like("PATA"))
            r_or = db.buscar("26067.E023,26067.E144")
            r_or_sin = db.buscar("26067.E023,26067.E144,-pata")
            comprobar("la muestra 'O' es util",
                      0 < n_or_sin < n_or, "%d de %d" % (n_or_sin, n_or))
            comprobar("con ',' la exclusion se aplica a todo el conjunto",
                      len(r_or) == n_or and len(r_or_sin) == n_or_sin,
                      "%d/%d y %d/%d" % (len(r_or), n_or, len(r_or_sin), n_or_sin))

            titulo("2d. MAYUSCULAS Y TILDES DAN IGUAL")
            r_may = db.buscar(base_term + ";-" + fuera.lower())
            comprobar("da igual escribirlo en mayusculas o en minusculas",
                      len(r_may) == len(r_sin), "%d vs %d" % (len(r_may), len(r_sin)))

            titulo("2e. LOS NOMBRES CON GUION SIGUEN ENCONTRANDOSE")
            n_guion = contar_sql("nombre_archivo LIKE '%NO USAR - COLORES%'")
            r_guion = db.buscar("NO USAR - COLORES")
            comprobar("'NO USAR - COLORES' no se interpreta como exclusion",
                      len(r_guion) == n_guion and n_guion > 0,
                      "%d vs %d" % (len(r_guion), n_guion))
            n_ref = contar_sql(like("22057-188"))
            r_ref = db.buscar("22057-188")
            comprobar("una referencia con guion interno se busca entera",
                      len(r_ref) == n_ref and n_ref > 0,
                      "%d vs %d" % (len(r_ref), n_ref))

            titulo("3. EL CLIENTE Y EL SERVIDOR OPINAN LO MISMO")
            fallos = [x[0] for x in r_sin[:400]
                      if not win._casa_termino_local(x[0], term)]
            comprobar("lo que devuelve el servidor lo acepta el filtro local",
                      not fallos, "%d discrepancias" % len(fallos))
            quitados = [x for x in r_todo if x[10] in (nombres_todo - nombres_sin)]
            colados = [x[0] for x in quitados[:400]
                       if win._casa_termino_local(x[0], term)]
            comprobar("y lo que el servidor descarta, el filtro local tambien",
                      not colados, "%d discrepancias" % len(colados))

            titulo("4. MODO 'CONJUNTOS QUE LO LLEVEN'")
            ens = db.buscar_ensamblajes_que_contienen("pata curva", limite=5000)
            rutas_todas = [x[10] for x in ens]
            cur.execute(
                "SELECT count(DISTINCT ensamblaje_ruta) FROM buscador.componentes "
                "WHERE ensamblaje_ruta = ANY(%s) "
                "  AND UPPER(unaccent(componente_nombre)) LIKE '%%SOPORTE%%'",
                (rutas_todas,))
            n_con_sop = cur.fetchone()[0]
            ens_sin = db.buscar_ensamblajes_que_contienen("pata curva;-soporte",
                                                          limite=5000)
            emitir("  conjuntos con 'pata curva': %d · de ellos con 'soporte': %d"
                   % (len(ens), n_con_sop))
            comprobar("la muestra de conjuntos es util",
                      0 < n_con_sop < len(ens) and len(ens) < 5000,
                      "%d de %d" % (n_con_sop, len(ens)))
            comprobar("'-soporte' quita exactamente los que lo llevan",
                      len(ens_sin) == len(ens) - n_con_sop,
                      "%d vs %d" % (len(ens_sin), len(ens) - n_con_sop))
            rutas_sin = [x[10] for x in ens_sin]
            malos = []
            if rutas_sin:
                cur.execute(
                    "SELECT DISTINCT ensamblaje_ruta FROM buscador.componentes "
                    "WHERE ensamblaje_ruta = ANY(%s) "
                    "  AND UPPER(unaccent(componente_nombre)) LIKE '%%SOPORTE%%'",
                    (rutas_sin,))
                malos = [r[0] for r in cur.fetchall()]
            comprobar("ninguno de los conjuntos lleva un componente 'soporte'",
                      not malos, "%d con componente excluido" % len(malos))
            cx.close()

            # ═══════════════════════════════════════════════════
            titulo("5. LA INTERFAZ LO EXPLICA Y SE PUEDE DESHACER")
            win.input_buscar.setText("-banda")
            win.lbl_status.setText("")
            win.ejecutar_busqueda(auto=True)
            estado = win.lbl_status.text()
            comprobar("solo con '-banda' no se lanza la busqueda a ciegas",
                      "quieres encontrar" in estado, estado[:52])

            win.input_buscar.setText("cinta;450;inox;-banda")
            win.ejecutar_busqueda(auto=True)
            t0 = time.time()
            while not getattr(win, '_res_base', []) and time.time() - t0 < 60:
                QApplication.processEvents()
                time.sleep(0.05)
            comprobar("la busqueda con exclusion llega a pintar resultados",
                      len(getattr(win, '_res_base', [])) > 0,
                      "%d resultados" % len(getattr(win, '_res_base', [])))
            comprobar("la app recuerda que hay una exclusion activa",
                      win._excluidas_activas == ["banda"],
                      repr(win._excluidas_activas))

            def textos_chips():
                lay = win.chips_activos_lay
                out = []
                for i in range(lay.count()):
                    w = lay.itemAt(i).widget()
                    if w is None:
                        continue
                    for lbl in w.findChildren(type(win.lbl_count)):
                        out.append(lbl.text())
                return out

            chips = textos_chips()
            comprobar("se ve un chip que dice que se esta excluyendo",
                      any("banda" in c for c in chips), " / ".join(chips[:4]))

            win._quitar_exclusion("banda")
            comprobar("al quitar el chip, el '-banda' sale de la barra",
                      "-banda" not in win.input_buscar.text(),
                      win.input_buscar.text())
            comprobar("y lo que si se buscaba sigue estando",
                      all(p in win.input_buscar.text() for p in ("cinta", "450", "inox")),
                      win.input_buscar.text())
            inc2, exc2, _a2 = db.parsear_termino(win.input_buscar.text())
            comprobar("el termino reconstruido sigue siendo valido",
                      inc2 == ["cinta", "450", "inox"] and exc2 == [],
                      "inc=%r exc=%r" % (inc2, exc2))

            titulo("6. LA AYUDA ESTA AL DIA")
            ruta_guia = os.path.join(RAIZ, "docs", "GUIA_RAPIDA.md")
            texto_guia = ""
            if os.path.exists(ruta_guia):
                with open(ruta_guia, encoding="utf-8") as fh:
                    texto_guia = fh.read()
            comprobar("la guia explica el '-palabra'",
                      "-banda" in texto_guia or "-palabra" in texto_guia)
            comprobar("el recuadro de busqueda lo anuncia",
                      "-banda" in win.input_buscar.placeholderText(),
                      win.input_buscar.placeholderText()[:56])
            comprobar("y el tooltip tambien",
                      "QUITA" in win.input_buscar.toolTip())

            # La pestana de Ayuda se abre de verdad y se lee su HTML: asi se
            # comprueba que el texto nuevo se PINTA, no solo que esta en el .md
            from PyQt5.QtWidgets import QDialog, QTextBrowser
            capturados = []
            exec_original = QDialog.exec_
            QDialog.exec_ = lambda self: (capturados.append(self),
                                          QDialog.Accepted)[1]
            try:
                win.mostrar_ayuda()
            finally:
                QDialog.exec_ = exec_original
            # el visor pinta UNA seccion cada vez (indice lateral): se recorren
            # todas, que es lo que hara el compañero que busque la explicacion
            from PyQt5.QtWidgets import QListWidget
            html = ""
            if capturados:
                dlg = capturados[-1]
                navs = dlg.findChildren(QListWidget)
                brs = dlg.findChildren(QTextBrowser)
                if navs and brs:
                    for fila in range(navs[0].count()):
                        navs[0].setCurrentRow(fila)
                        QApplication.processEvents()
                        html += brs[0].toHtml()
                else:
                    for br in brs:
                        html += br.toHtml()
            comprobar("la pestana de Ayuda se abre", bool(capturados))
            comprobar("y en ella se lee lo del guion",
                      "-banda" in html or "quita" in html.lower(),
                      "%d caracteres de ayuda" % len(html))
            comprobar("los subtitulos no salen como '###'",
                      "###" not in html)

        except Exception:
            import traceback
            emitir("EXCEPCION:")
            emitir(traceback.format_exc())
            RESULTADOS.append(("la bateria termina sin excepciones", False, ""))

        emitir("")
        emitir("=" * 72)
        fallos = [r for r in RESULTADOS if not r[1]]
        emitir("  TOTAL: %d de %d" % (len(RESULTADOS) - len(fallos), len(RESULTADOS)))
        if fallos:
            emitir("")
            emitir("  FALLOS:")
            for t, _ok, d in fallos:
                emitir("    - %s %s" % (t, ("(%s)" % d) if d else ""))
        emitir("=" * 72)
        salida["codigo"] = 0 if not fallos else 1
        # V2.3.2: se sale AQUI, con Qt todavia sano. Si se dejaba volver a
        # runpy, este desmontaba el modulo de la app con los hilos de fondo
        # aun vivos y el proceso se mataba solo (0xC0000409) despues de
        # imprimir todas las comprobaciones en verde.
        import arnes_pruebas
        arnes_pruebas.salir(salida["codigo"], _f)
        return 0

    QApplication.exec_ = _exec
    sys.argv = ["buscar_piezas.py"]
    try:
        runpy.run_path(os.path.join(RAIZ, "buscar_piezas.py"), run_name="__main__")
    except SystemExit:
        pass
    return salida.get("codigo", 1)


if __name__ == "__main__":
    # V2.3.2: salida determinista. Ver arnes_pruebas: con hilos Qt vivos,
    # el desmontaje del interprete tumbaba el proceso y el codigo de salida
    # dejaba de significar lo que decian las comprobaciones.
    import arnes_pruebas
    arnes_pruebas.salir(main(), _f)
