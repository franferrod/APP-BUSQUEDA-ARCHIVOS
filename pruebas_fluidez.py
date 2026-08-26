# -*- coding: utf-8 -*-
"""Pruebas de fluidez: que tocar un filtro no congele la ventana (V2.3.1).

El fallo: refrescar_filtros_jerarquicos hacia sus dos consultas en el hilo de
la interfaz desde la V1.0.0. Medido contra el servidor, con la rejilla llena:

    refrescar_filtros_jerarquicos (UI) ....... 0,51 s   <-- ventana congelada
    get_all_clients .......................... 0,14 s
    get_all_projects sin cliente marcado ..... 0,51 s

Cada clic en un filtro dejaba la ventana muerta ~0,65 s, y el peor caso es
justo como arranca la app: sin ningun cliente marcado.

Estas comprobaciones vigilan las dos cosas a la vez: que ya no bloquea, y que
el resultado sigue siendo el mismo que daba la version sincrona.

    python pruebas_fluidez.py
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

# Tope de bloqueo aceptable en el hilo de UI. La version sincrona daba 0,65 s;
# lanzar un worker son microsegundos, asi que 0,15 s deja margen de sobra y
# sigue cazando cualquier recaida a consultas sincronas.
TOPE_BLOQUEO = 0.15

INFORME = os.path.join(RAIZ, "pruebas_fluidez_resultado.txt")
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
    emitir("  %-56s %s%s" % (texto, "OK" if ok else "FALLO",
                             ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    emitir("")
    emitir("-- %s %s" % (t, "-" * max(0, 62 - len(t))))


def main():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    salida = {}

    def esperar_workers(win, segundos=30):
        t0 = time.time()
        while time.time() - t0 < segundos:
            QApplication.processEvents()
            if not getattr(win, '_filtros_workers', []) and \
               not getattr(win, '_props_workers', []):
                return True
            time.sleep(0.02)
        return False

    def _exec(self):
        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            win._carga_inicial_diferida()
            t0 = time.time()
            while not win.db.esta_disponible() and time.time() - t0 < 30:
                QApplication.processEvents()
                time.sleep(0.05)
            win.cargar_filtros_propiedades()
            esperar_workers(win)

            emitir("=" * 70)
            emitir("  FLUIDEZ: tocar un filtro no puede congelar la ventana")
            emitir("=" * 70)

            for i in range(win.list_companeros.count()):
                win.list_companeros.item(i).setCheckState(Qt.Checked)

            # ── 1. El peor caso: sin ningun cliente marcado ───────────────
            titulo("1. El peor caso — sin cliente marcado")
            t = time.time()
            win.refrescar_filtros_jerarquicos()
            bloqueo = time.time() - t
            comprobar("lanzar el refresco no bloquea el hilo de UI",
                      bloqueo < TOPE_BLOQUEO, "%.3f s (antes 0,65 s)" % bloqueo)
            comprobar("hay un worker haciendo el trabajo",
                      len(getattr(win, '_filtros_workers', [])) >= 1)
            llego = esperar_workers(win)
            comprobar("el worker termina y se limpia solo", llego)
            comprobar("la lista de clientes se ha poblado",
                      win.list_clientes.count() > 0,
                      "%d clientes" % win.list_clientes.count())
            comprobar("la lista de proyectos se ha poblado",
                      win.list_proyectos.count() > 0,
                      "%d proyectos" % win.list_proyectos.count())

            # ── 2. Mismo resultado que la version sincrona ────────────────
            titulo("2. Da lo mismo que la consulta directa")
            comp = win.get_selected_items(win.list_companeros)
            años = win.get_selected_items(win.list_años)
            esperados_cli = win.controller.get_all_clients(companions=comp, years=años)
            pintados_cli = [win.list_clientes.item(i).text()
                            for i in range(win.list_clientes.count())]
            comprobar("los clientes coinciden uno a uno",
                      pintados_cli == list(esperados_cli),
                      "pintados %d · esperados %d" % (len(pintados_cli), len(esperados_cli)))
            esperados_pro = win.controller.get_all_projects(
                clientes=None, companions=comp or None, years=años or None)
            comprobar("los proyectos coinciden en numero",
                      win.list_proyectos.count() == len(esperados_pro),
                      "pintados %d · esperados %d" % (win.list_proyectos.count(),
                                                      len(esperados_pro)))

            # ── 3. Se conservan las marcas ────────────────────────────────
            titulo("3. Lo marcado se conserva al refrescar")
            if win.list_clientes.count() >= 2:
                marcado = win.list_clientes.item(0).text()
                win.list_clientes.item(0).setCheckState(Qt.Checked)
                win.refrescar_filtros_jerarquicos()
                esperar_workers(win)
                sigue = [win.list_clientes.item(i).text()
                         for i in range(win.list_clientes.count())
                         if win.list_clientes.item(i).checkState() == Qt.Checked]
                comprobar("el cliente marcado sigue marcado tras refrescar",
                          sigue == [marcado], "%s -> %s" % (marcado, sigue))
                # Y los proyectos deben haberse acotado a ese cliente
                acotados = win.controller.get_all_projects(
                    clientes=[marcado], companions=comp or None, years=años or None)
                comprobar("los proyectos se acotan al cliente marcado",
                          win.list_proyectos.count() == len(acotados),
                          "pintados %d · esperados %d" % (win.list_proyectos.count(),
                                                          len(acotados)))
                win.list_clientes.item(0).setCheckState(Qt.Unchecked)
                win.refrescar_filtros_jerarquicos()
                esperar_workers(win)

            # ── 4. Encadenado: primero repoblar, luego buscar ─────────────
            titulo("4. La busqueda sale DESPUES de repoblar")
            orden = []
            orig_props = win._refrescar_props_contexto
            orig_busq = win.ejecutar_busqueda

            def espia_props():
                orden.append(("props", win.list_clientes.count()))
                return orig_props()

            def espia_busq(auto=False):
                orden.append(("busqueda", win.list_clientes.count()))
                return orig_busq(auto=auto)

            win._refrescar_props_contexto = espia_props
            win.ejecutar_busqueda = espia_busq
            try:
                t = time.time()
                win._refrescar_real_jerarquico()
                bloqueo2 = time.time() - t
                comprobar("un clic de filtro no bloquea la ventana",
                          bloqueo2 < TOPE_BLOQUEO, "%.3f s" % bloqueo2)
                comprobar("nada se dispara antes de tener los datos",
                          orden == [], str(orden))
                esperar_workers(win)
                QApplication.processEvents()
                comprobar("despues se disparan cascada y busqueda, en ese orden",
                          [x[0] for x in orden] == ["props", "busqueda"], str(orden))
                comprobar("y lo hacen con las listas ya repobladas",
                          all(n > 0 for _, n in orden), str(orden))
            finally:
                win._refrescar_props_contexto = orig_props
                win.ejecutar_busqueda = orig_busq

            # ── 5. Respuestas obsoletas ───────────────────────────────────
            titulo("5. Una respuesta obsoleta no pisa a la buena")
            antes = win.list_clientes.count()
            win._gen_filtros = getattr(win, '_gen_filtros', 0) + 5
            win._on_filtros_jerarquicos(1, True, [], [])   # generacion vieja
            comprobar("se descarta la respuesta de una generacion anterior",
                      win.list_clientes.count() == antes,
                      "%d -> %d" % (antes, win.list_clientes.count()))

            # ── 6. Si la consulta falla, no se vacian los filtros ─────────
            titulo("6. Un fallo de red no deja al usuario sin filtros")
            antes = win.list_clientes.count()
            win._on_filtros_jerarquicos(win._gen_filtros, False, [], [])
            comprobar("con ok=False las listas quedan intactas",
                      win.list_clientes.count() == antes,
                      "%d -> %d" % (antes, win.list_clientes.count()))

            # ── 7. El refinado no se lo lleva otra busqueda ───────────────
            titulo("7. Un refinado en espera es de SU busqueda")
            # Al pasar los filtros a segundo plano aparecio esta carrera:
            # dentro de ejecutar_busqueda hay un processEvents, y por ahi podia
            # entrar la respuesta de una busqueda anterior aun en vuelo. Se
            # llevaba el refinado pendiente, lo aplicaba sobre la base
            # equivocada, y la busqueda buena lo borraba al llegar.
            win._res_base = []
            win._termino_base = None
            win._refinados = []
            win._refinado_pendiente = None
            win._gen_refinado_pendiente = None
            win.input_buscar.setText("cinta a450")
            win.input_refinar.setText("motor")
            win._agregar_refinado()
            comprobar("el refinado queda atado a una generacion concreta",
                      getattr(win, '_gen_refinado_pendiente', None) is not None,
                      str(getattr(win, '_gen_refinado_pendiente', None)))
            # Una respuesta de OTRA generacion no puede llevarselo
            pendiente_antes = getattr(win, '_refinado_pendiente', None)
            ajena = (getattr(win, '_gen_refinado_pendiente', 0) or 0) + 99
            win._gen_busqueda = ajena
            win._on_resultados_busqueda(ajena, [])
            comprobar("una respuesta ajena no se lleva el refinado",
                      getattr(win, '_refinado_pendiente', None) == pendiente_antes,
                      "%r -> %r" % (pendiente_antes,
                                    getattr(win, '_refinado_pendiente', None)))

            # ── 8. Cierre limpio ──────────────────────────────────────────
            titulo("7. Los hilos se paran al cerrar")
            win.refrescar_filtros_jerarquicos()
            comprobar("hay un worker vivo antes de cerrar",
                      len(getattr(win, '_filtros_workers', [])) >= 1)
            win._detener_workers_de_fondo()
            comprobar("_detener_workers_de_fondo los deja en cero",
                      not getattr(win, '_filtros_workers', [])
                      and not getattr(win, '_props_workers', []))

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
