# -*- coding: utf-8 -*-
"""Pruebas de la cascada de filtros de propiedades SW (V2.3.0).

Que hace: Material, Tratamiento, Cierre y Espesor se estrechan al contexto
(origen / anos / clientes / proyectos), igual que Clientes y Proyectos. Antes
se ofrecian los 243 materiales del indice entero aunque el cliente marcado
solo tuviera 69.

Lo que estas comprobaciones vigilan, por orden de importancia:
  - que estrecha de verdad y no se inventa ni pierde valores,
  - que lo MARCADO nunca se esconde (si no, no se podria desmarcar),
  - que no bloquea el hilo de la interfaz,
  - que si la base falla se ve todo, como antes.

    python pruebas_cascada.py
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

INFORME = os.path.join(RAIZ, "pruebas_cascada_resultado.txt")
RESULTADOS = []
_f = open(INFORME, "w", encoding="utf-8")


def emitir(t=""):
    try:
        sys.__stdout__.write(t + "\n")
        sys.__stdout__.flush()
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
    from PyQt5.QtCore import Qt
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
            # La carga inicial puede haber corrido antes de que el servidor
            # estuviera listo (la conexion va en un worker). Con la base ya
            # disponible se rellenan las listas, que es lo que hace la app.
            win.cargar_filtros_propiedades()

            emitir("=" * 70)
            emitir("  CASCADA DE FILTROS DE PROPIEDADES SW")
            emitir("=" * 70)

            import psycopg2
            from models import PG_CONFIG
            cn = psycopg2.connect(**PG_CONFIG)
            cur = cn.cursor()

            # ── 1. La consulta ────────────────────────────────────────────
            titulo("1. La consulta responde, completa y rapida")
            ORIGENES = ['PROYECTOS', 'BIBLIOTECA_3D', 'ALSI_ESTANDAR']
            t0 = time.time()
            todo = win.db.obtener_propiedades_contexto(compañeros=ORIGENES)
            tardanza = time.time() - t0
            comprobar("devuelve las cuatro familias",
                      set(todo) == {'materiales', 'tratamientos', 'espesores', 'cierres'},
                      str(sorted(todo)))
            comprobar("tarda menos de 3 s", tardanza < 3.0, "%.2f s" % tardanza)
            comprobar("hay materiales", len(todo.get('materiales', ())) > 0,
                      "%d materiales" % len(todo.get('materiales', ())))
            comprobar("todo llega normalizado a mayusculas",
                      all(v == v.upper() for v in todo['materiales']))

            # ── 2. Cuadra con SQL a pelo ──────────────────────────────────
            titulo("2. El conjunto global cuadra con la base")
            cur.execute("""SELECT COUNT(DISTINCT UPPER(TRIM(sw_material)))
                           FROM buscador.archivos
                           WHERE sw_material IS NOT NULL AND TRIM(sw_material) <> ''""")
            n_sql = cur.fetchone()[0]
            comprobar("mismo numero de materiales que el SQL directo",
                      len(todo['materiales']) == n_sql,
                      "cascada %d · sql %d" % (len(todo['materiales']), n_sql))

            # ── 3. Estrechar de verdad ────────────────────────────────────
            titulo("3. Estrecha al contexto")
            cur.execute("""SELECT cliente FROM buscador.archivos
                           WHERE cliente IS NOT NULL AND cliente <> ''
                             AND origen = 'PROYECTOS'
                           GROUP BY cliente ORDER BY COUNT(*) DESC LIMIT 1""")
            cliente = cur.fetchone()[0]
            solo_proy = win.db.obtener_propiedades_contexto(compañeros=['PROYECTOS'])
            acotado = win.db.obtener_propiedades_contexto(compañeros=['PROYECTOS'],
                                                          clientes=[cliente])
            comprobar("con un cliente salen menos materiales",
                      len(acotado['materiales']) < len(solo_proy['materiales']),
                      "%s: %d de %d" % (cliente, len(acotado['materiales']),
                                        len(solo_proy['materiales'])))
            comprobar("y son un subconjunto, no otros distintos",
                      acotado['materiales'] <= solo_proy['materiales'],
                      str(list(acotado['materiales'] - solo_proy['materiales'])[:3]))

            cur.execute("""SELECT COUNT(DISTINCT UPPER(TRIM(sw_material)))
                           FROM buscador.archivos
                           WHERE origen = 'PROYECTOS' AND cliente = %s
                             AND sw_material IS NOT NULL AND TRIM(sw_material) <> ''""",
                        (cliente,))
            n_cli = cur.fetchone()[0]
            comprobar("el recuento acotado cuadra con el SQL",
                      len(acotado['materiales']) == n_cli,
                      "cascada %d · sql %d" % (len(acotado['materiales']), n_cli))

            # ── 4. Las bibliotecas se saltan los filtros jerarquicos ──────
            titulo("4. Las bibliotecas ignoran los filtros jerarquicos")
            # Misma semantica que buscar(): las piezas de biblioteca entran
            # siempre, no las recorta el cliente ni el proyecto.
            con_biblio = win.db.obtener_propiedades_contexto(
                compañeros=['PROYECTOS', 'BIBLIOTECA_3D'], clientes=[cliente])
            solo_biblio = win.db.obtener_propiedades_contexto(compañeros=['BIBLIOTECA_3D'])
            comprobar("la biblioteca aporta sus valores pese al cliente",
                      solo_biblio['materiales'] <= con_biblio['materiales'],
                      "faltan %d" % len(solo_biblio['materiales'] - con_biblio['materiales']))
            comprobar("y el resultado incluye los del cliente",
                      acotado['materiales'] <= con_biblio['materiales'])

            # ── 5. La interfaz esconde lo que no toca ─────────────────────
            titulo("5. La interfaz esconde lo que no aplica")
            lista = win.list_materiales
            comprobar("la lista de materiales esta poblada", lista.count() > 0,
                      "%d elementos" % lista.count())

            for i in range(lista.count()):
                lista.item(i).setCheckState(Qt.Unchecked)
                lista.item(i).setHidden(False)
            win._gen_props = 99
            win._on_props_contexto(99, acotado)
            visibles = [lista.item(i).text() for i in range(lista.count())
                        if not lista.item(i).isHidden()]
            ocultos = [lista.item(i).text() for i in range(lista.count())
                       if lista.item(i).isHidden()]
            comprobar("esconde alguno", len(ocultos) > 0, "%d ocultos" % len(ocultos))
            comprobar("deja visible alguno", len(visibles) > 0, "%d visibles" % len(visibles))
            comprobar("todo lo visible existe en el contexto",
                      all(v.strip().upper() in acotado['materiales'] for v in visibles),
                      str([v for v in visibles
                           if v.strip().upper() not in acotado['materiales']][:3]))
            comprobar("nada de lo oculto existe en el contexto",
                      not any(v.strip().upper() in acotado['materiales'] for v in ocultos),
                      str([v for v in ocultos
                           if v.strip().upper() in acotado['materiales']][:3]))

            # ── 6. Lo marcado nunca se esconde ────────────────────────────
            titulo("6. Lo marcado nunca se esconde")
            if ocultos:
                idx = next(i for i in range(lista.count())
                           if lista.item(i).text() == ocultos[0])
                lista.item(idx).setCheckState(Qt.Checked)
                win._gen_props = 100
                win._on_props_contexto(100, acotado)
                comprobar("un valor marcado sigue visible aunque no aplique",
                          not lista.item(idx).isHidden(), lista.item(idx).text())
                # 'Todos' no debe marcar lo oculto
                lista.item(idx).setCheckState(Qt.Unchecked)
                win._on_props_contexto(100, acotado)
                win.toggle_checkboxes(lista, True)
                marcados_ocultos = [lista.item(i).text() for i in range(lista.count())
                                    if lista.item(i).isHidden()
                                    and lista.item(i).checkState() == Qt.Checked]
                comprobar("'Todos' no marca los valores ocultos",
                          not marcados_ocultos, str(marcados_ocultos[:3]))
                win.toggle_checkboxes(lista, False)
                comprobar("'Ninguno' desmarca todo, ocultos incluidos",
                          all(lista.item(i).checkState() == Qt.Unchecked
                              for i in range(lista.count())))

            # ── 7. Si la base falla, se ve todo ───────────────────────────
            titulo("7. Si la base falla se ve todo, como antes")
            win._gen_props = 101
            win._on_props_contexto(101, {})
            comprobar("con respuesta vacia no se esconde nada",
                      all(not lista.item(i).isHidden() for i in range(lista.count())))

            # ── 8. Respuestas obsoletas ───────────────────────────────────
            titulo("8. Una respuesta obsoleta no pisa a la buena")
            for i in range(lista.count()):
                lista.item(i).setHidden(False)
                lista.item(i).setCheckState(Qt.Unchecked)
            win._gen_props = 200
            win._on_props_contexto(150, acotado)   # generacion vieja
            comprobar("se descarta la respuesta de una generacion anterior",
                      all(not lista.item(i).isHidden() for i in range(lista.count())))
            win._on_props_contexto(200, acotado)   # generacion en curso
            comprobar("la respuesta en curso si se aplica",
                      any(lista.item(i).isHidden() for i in range(lista.count())))

            # ── 9. No bloquea la interfaz ─────────────────────────────────
            titulo("9. No corre en el hilo de la interfaz")
            win._props_ctx_kwargs = None
            t0 = time.time()
            win._refrescar_props_contexto()
            devuelto_en = time.time() - t0
            comprobar("lanzar la cascada devuelve al instante",
                      devuelto_en < 0.25, "%.3f s" % devuelto_en)
            comprobar("hay un worker en marcha",
                      len(getattr(win, '_props_workers', [])) >= 1)
            t0 = time.time()
            while getattr(win, '_props_workers', []) and time.time() - t0 < 20:
                QApplication.processEvents()
                time.sleep(0.05)
            comprobar("el worker termina y se limpia solo",
                      not getattr(win, '_props_workers', []))
            win._props_ctx_kwargs = None
            win._refrescar_props_contexto()
            gen1 = win._gen_props
            win._refrescar_props_contexto()   # mismo contexto
            comprobar("con el mismo contexto no se relanza",
                      win._gen_props == gen1, "gen %d -> %d" % (gen1, win._gen_props))

            # ── 10. Espesores ─────────────────────────────────────────────
            titulo("10. Los espesores se traducen a mm enteros")
            esp = win.list_espesores
            for i in range(esp.count()):
                esp.item(i).setHidden(False)
                esp.item(i).setCheckState(Qt.Unchecked)
            win._gen_props = 300
            win._on_props_contexto(300, {'materiales': set(), 'tratamientos': set(),
                                         'cierres': set(), 'espesores': {'3', '3.00', '5.5'}})
            vis = [esp.item(i).text() for i in range(esp.count())
                   if not esp.item(i).isHidden()]
            comprobar("'3' y '3.00' dejan visible el espesor de 3 mm",
                      any(x.replace('mm', '').strip() == '3' for x in vis), str(vis))
            comprobar("'5.5' deja visible el de 5 mm",
                      any(x.replace('mm', '').strip() == '5' for x in vis), str(vis))
            comprobar("un espesor no presente queda oculto",
                      not any(x.replace('mm', '').strip() == '10' for x in vis), str(vis))

            # ── 11. Cierre limpio ─────────────────────────────────────────
            titulo("11. Los hilos se paran al cerrar")
            win._props_ctx_kwargs = None
            win._refrescar_props_contexto()
            comprobar("hay un worker vivo antes de cerrar",
                      len(getattr(win, '_props_workers', [])) >= 1)
            # Lo mismo que hacen closeEvent y aboutToQuit en la app real. Sin
            # esto el proceso se cae al salir: Qt destruye un QThread en marcha.
            win._detener_props_workers()
            comprobar("_detener_props_workers los deja en cero",
                      not getattr(win, '_props_workers', []))

            cur.close()
            cn.close()

        except Exception as e:
            import traceback
            emitir(traceback.format_exc())
            comprobar("la bateria termina sin excepciones", False, str(e))

        emitir("")
        emitir("=" * 70)
        fallos = [r for r in RESULTADOS if not r[1]]
        emitir("  TOTAL: %d de %d" % (len(RESULTADOS) - len(fallos), len(RESULTADOS)))
        if fallos:
            emitir("")
            emitir("  FALLOS:")
            for t, _ok, d in fallos:
                emitir("    - %s %s" % (t, ("(%s)" % d) if d else ""))
        emitir("=" * 70)
        salida["codigo"] = 0 if not fallos else 1
        return 0

    QApplication.exec_ = _exec
    sys.argv = ["buscar_piezas.py"]
    try:
        runpy.run_path(os.path.join(RAIZ, "buscar_piezas.py"), run_name="__main__")
    except SystemExit:
        pass
    return salida.get("codigo", 1)


if __name__ == "__main__":
    sys.exit(main())
