# -*- coding: utf-8 -*-
"""Pruebas del explorador de conjuntos (18/11/2026).

    python pruebas_explorador.py

Sustituye a los diálogos de «Ver componentes» y «¿En qué ensamblajes se usa?».
Lo que vigila, sacado de las quejas y de lo medido al hacerlo:
  - los nombres salían en MAYÚSCULAS (se enseñaba la clave del cruce);
  - las miniaturas eran de 48 px, sin forma de agrandarlas;
  - para bajar a un subconjunto se abría un diálogo encima de otro;
  - «dónde se usa» de una pieza común (5.221 conjuntos) congelaba la ventana
    unos 3 s y descomprimía 5.000 miniaturas (1,3 GB).

Contra el servidor real, SOLO LECTURA. Las muestras se eligen con las mismas
funciones que usa el producto (obtener_componentes_de, buscar_ensamblajes_de).
"""
import csv
import os
import runpy
import sys
import tempfile
import time
import traceback

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ALSI_SIN_DIALOGOS"] = "1"
os.environ["ALSI_SIN_CANDADO"] = "1"
os.environ["ALSI_SIN_PREFERENCIAS"] = "1"
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

INFORME = os.path.join(RAIZ, "pruebas_explorador_resultado.txt")
RESULTADOS = []


class _Tee:
    def __init__(self, ruta):
        self.f = open(ruta, "w", encoding="utf-8")

    def write(self, t):
        try:
            sys.__stdout__.write(t)
        except Exception:
            pass
        self.f.write(t)
        self.f.flush()

    def flush(self):
        self.f.flush()


TEE = _Tee(INFORME)
sys.stdout = TEE


def comprobar(texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((texto, ok, detalle))
    print("  %-60s %s%s" % (texto, "OK" if ok else "FALLO",
                            ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


def esperar(cond, seg):
    from PyQt5.QtWidgets import QApplication
    t0 = time.time()
    while not cond() and time.time() - t0 < seg:
        QApplication.processEvents()
        time.sleep(0.02)
    return cond()


def bombear(seg):
    esperar(lambda: False, seg)


def sin_tareas(dlg, seg=20):
    return esperar(lambda: not dlg._tareas, seg)


# ---------------------------------------------------------------------------
def elegir_muestras(db):
    """Un conjunto con subconjunto y pieza indexados (y alguna pieza con
    minúsculas en el nombre), y la pieza más usada de todas."""
    import psycopg2
    from models import PG_CONFIG
    c = psycopg2.connect(**PG_CONFIG)
    c.set_session(readonly=True)
    cu = c.cursor()
    cu.execute("""SELECT c.ensamblaje_ruta FROM buscador.componentes c
                  JOIN buscador.archivos e ON e.ruta_completa = c.ensamblaje_ruta
                  GROUP BY 1
                  HAVING count(*) BETWEEN 6 AND 60
                     AND bool_or(c.componente_nombre LIKE '%%.SLDASM')
                     AND bool_or(c.componente_nombre LIKE '%%.SLDPRT')
                  LIMIT 80""")
    candidatos = [r[0] for r in cu.fetchall()]
    ens = None
    for r in candidatos:
        filas = db.obtener_componentes_de(r)
        sub = [f for f in filas if f[1] and f[6] and f[1].lower().endswith('.sldasm')]
        pie = [f for f in filas if f[1] and f[6] and f[1].lower().endswith('.sldprt')
               and f[1] != f[1].upper()]
        if sub and pie:
            ens = r
            break
    cu.execute("""SELECT componente_nombre FROM buscador.componentes
                  GROUP BY 1 ORDER BY count(DISTINCT ensamblaje_ruta) DESC LIMIT 1""")
    nombre = cu.fetchone()[0]
    cu.execute("SELECT ruta_completa FROM buscador.archivos WHERE upper(nombre_archivo) = %s LIMIT 1",
               (nombre,))
    fila = cu.fetchone()
    c.close()
    return ens, (fila[0] if fila else None)


def buscar_fila(dlg, mod, cond):
    """(fila de la tabla, dict) de la primera fila que cumple cond."""
    t = dlg.tabla
    for r in range(t.rowCount()):
        it = t.item(r, 0)
        i = it.data(mod.ROL_FILA) if it else None
        if i is not None and cond(dlg.filas[i]):
            return r, dlg.filas[i]
    return None, None


# ---------------------------------------------------------------------------
def probar_despiece(win, mod, ens):
    from PyQt5.QtCore import Qt, QSize
    E = mod.ExploradorConjunto
    titulo("1. EL DESPIECE: nombres de verdad, miniaturas y peso")
    t0 = time.time()
    dlg = E(win, ens, E.COMP)
    t_abrir = time.time() - t0
    dlg.resize(1300, 820)
    dlg.show()
    comprobar("la ventana se abre sin esperar a la base", t_abrir < 0.5, "%.2f s" % t_abrir)
    comprobar("las filas llegan", esperar(lambda: dlg.cargado, 20))
    esperadas = win.db.obtener_componentes_de(ens)
    comprobar("una fila por componente, como el producto",
              len(dlg.filas) == len(esperadas) == dlg.tabla.rowCount(),
              "%d filas" % len(dlg.filas))

    nombres_bd = {f[6]: f[1] for f in esperadas if f[1] and f[6]}
    textos = {}
    for r in range(dlg.tabla.rowCount()):
        ruta = dlg.tabla.item(r, 0).data(Qt.UserRole)
        if ruta in nombres_bd:
            textos[ruta] = dlg.tabla.item(r, 1).text()
    comprobar("cada componente indexado sale con el nombre del ARCHIVO",
              textos and all(textos[r] == nombres_bd[r] for r in textos),
              "%d comprobados" % len(textos))
    comprobar("y no en mayúsculas (antes: la clave del cruce)",
              any(t != t.upper() for t in textos.values()))
    no_idx = [d for d in dlg.filas if not d['indexado']]
    if no_idx:
        comprobar("los que no están en el índice siguen saliendo, sin ruta",
                  all(not d['ruta'] for d in no_idx), "%d" % len(no_idx))

    masas = [float(f[7]) for f in esperadas if f[7]]
    if masas:
        comprobar("el peso total suma lo mismo que la base",
                  mod._num_es(sum(masas), 1) in dlg.lbl_total.text(),
                  mod._num_es(sum(masas), 1) + " kg")
    sin_tareas(dlg)
    bombear(0.3)
    con_mini = win.db.obtener_miniaturas_lote([f[6] for f in esperadas if f[6]])
    comprobar("trae las miniaturas que hay en la base",
              all(r in dlg._jpeg for r in con_mini), "%d" % len(con_mini))
    visibles_con_mini = 0
    for r in range(dlg.tabla.rowCount()):
        it = dlg.tabla.item(r, 0)
        if it.data(Qt.UserRole) in con_mini and dlg.tabla.visualItemRect(it).intersects(
                dlg.tabla.viewport().rect()):
            visibles_con_mini += 1
            if it.data(mod.ROL_ICONO) != dlg._icono:
                visibles_con_mini = -999
    comprobar("las filas a la vista llevan su miniatura al tamaño elegido",
              visibles_con_mini > 0, "%d filas" % max(0, visibles_con_mini))

    titulo("2. TAMAÑO DE LAS MINIATURAS")
    for px in (48, 160, 240):
        dlg._poner_icono(px, guardar=False)
        bombear(0.15)
        comprobar("a %d px: la tabla las pinta a %d" % (px, px),
                  dlg.tabla.iconSize() == QSize(px, px)
                  and dlg.tabla.rowHeight(0) >= px + 8)
    it = dlg.tabla.item(dlg.tabla.rowAt(0), 0)
    comprobar("y las que se ven se rehacen a ese tamaño (no se quedan en 48)",
              it.data(Qt.UserRole) not in con_mini or it.data(mod.ROL_ICONO) == 240)
    dlg._poner_icono(9999, guardar=False)
    comprobar("no pasa del lado de la miniatura guardada (256)", dlg._icono == 256)
    dlg._poner_icono(1, guardar=False)
    comprobar("ni baja de 40", dlg._icono == 40)
    antes = win.qsettings.value("explorador/icono")
    dlg._poner_icono(200, guardar=True)
    comprobar("con ALSI_SIN_PREFERENCIAS no guarda nada de nadie",
              win.qsettings.value("explorador/icono") == antes)
    dlg._poner_icono(96, guardar=False)

    titulo("3. GALERÍA")
    dlg._poner_vista("galeria", guardar=False)
    bombear(0.3)
    comprobar("la galería tiene una tarjeta por componente",
              dlg.galeria.count() == len(dlg.filas))
    comprobar("y sus tarjetas, el nombre de verdad",
              all(dlg.galeria.item(k).text().split("\n")[0] == dlg.filas[
                  dlg.galeria.item(k).data(mod.ROL_FILA)]['nombre']
                  for k in range(dlg.galeria.count())))
    dlg.caja.setText("zzzz-no-existe")
    comprobar("el buscador de dentro filtra también la galería",
              all(dlg.galeria.item(k).isHidden() for k in range(dlg.galeria.count())))
    dlg.caja.setText("")
    comprobar("y al limpiar vuelven todas",
              not any(dlg.galeria.item(k).isHidden() for k in range(dlg.galeria.count())))
    sel = dlg._sel_ruta
    dlg._poner_vista("lista", guardar=False)
    comprobar("al cambiar de vista se conserva la selección", dlg._sel_ruta == sel)
    return dlg


def probar_navegacion(win, mod, dlg, ens):
    from PyQt5.QtCore import Qt, QEvent, QPointF
    from PyQt5.QtGui import QMouseEvent
    E = mod.ExploradorConjunto
    titulo("4. NAVEGAR: entrar, volver, migas")
    r, sub = buscar_fila(dlg, mod, lambda d: d['ext'] == '.sldasm' and d['ruta'])
    dlg.tabla.selectRow(r)
    dlg.tabla.activated.emit(dlg.tabla.model().index(r, 1))
    comprobar("doble clic en un subconjunto: entra en él, en la misma ventana",
              dlg.nodo()['ruta'] == sub['ruta'] and dlg.nodo()['modo'] == E.COMP
              and len(dlg.hist) == 2)
    comprobar("y carga sus componentes", esperar(lambda: dlg.cargado, 20))
    comprobar("las migas muestran el camino (2 pasos)",
              sum(1 for b in dlg.migas.findChildren(mod.QPushButton) if b.isVisible()) == 2)
    comprobar("se puede volver; no adelante", dlg.btn_atras.isEnabled()
              and not dlg.btn_adelante.isEnabled())
    dlg.atras()
    esperar(lambda: dlg.cargado, 20)
    comprobar("atrás: vuelve al conjunto de arriba", dlg.nodo()['ruta'] == ens)
    comprobar("con el subconjunto del que veníamos seleccionado", dlg._sel_ruta == sub['ruta'])
    comprobar("las migas ya no enseñan el paso de adelante",
              sum(1 for b in dlg.migas.findChildren(mod.QPushButton) if b.isVisible()) == 1)
    dlg.adelante()
    esperar(lambda: dlg.cargado, 20)
    comprobar("adelante: otra vez dentro del subconjunto", dlg.nodo()['ruta'] == sub['ruta'])
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), Qt.BackButton,
                     Qt.BackButton, Qt.NoModifier)
    from PyQt5.QtWidgets import QApplication
    QApplication.sendEvent(dlg.tabla.viewport(), ev)
    esperar(lambda: dlg.cargado, 20)
    comprobar("el botón «atrás» del ratón también vuelve", dlg.nodo()['ruta'] == ens)
    n = len(dlg.hist)
    dlg.ir_a(ens, E.COMP)
    comprobar("ir al mismo sitio no ensucia el historial", len(dlg.hist) == n)

    r, pieza = buscar_fila(dlg, mod, lambda d: d['ext'] == '.sldprt' and d['ruta'])
    dlg.tabla.activated.emit(dlg.tabla.model().index(r, 1))
    comprobar("doble clic en una pieza: dónde se usa",
              dlg.nodo()['ruta'] == pieza['ruta'] and dlg.nodo()['modo'] == E.DONDE)
    esperar(lambda: dlg.cargado, 20)
    comprobar("y el conjunto del que venimos está en la lista",
              any(d['ruta'] == ens for d in dlg.filas), "%d conjuntos" % len(dlg.filas))
    comprobar("en una pieza no se puede pedir «Componentes»",
              not dlg.btn_modo_comp.isEnabled() and dlg.btn_modo_donde.isChecked())
    comprobar("al navegar se vacía el buscador de dentro", dlg.caja.text() == "")
    dlg.ir_a_posicion(0)
    esperar(lambda: dlg.cargado, 20)

    titulo("5. LA FICHA DE LA DERECHA")
    r, sub = buscar_fila(dlg, mod, lambda d: d['ext'] == '.sldasm' and d['ruta'])
    dlg.tabla.selectRow(r)
    comprobar("al seleccionar, la ficha lleva su nombre", dlg.lbl_nombre.text() == sub['nombre'])
    comprobar("y llega su ficha completa", esperar(lambda: bool(dlg._ficha), 15))
    f = win.db.ficha_archivo(sub['ruta'])
    comprobar("con el nº de componentes del botón igual que la base",
              "(%d)" % f['n_componentes'] in dlg.btn_f_comp.text(), dlg.btn_f_comp.text())
    comprobar("y el de «en qué conjuntos se usa»",
              "(%d)" % f['n_donde'] in dlg.btn_f_donde.text(), dlg.btn_f_donde.text())
    dlg.btn_f_comp.click()
    comprobar("el botón de la ficha entra en el subconjunto",
              dlg.nodo()['ruta'] == sub['ruta'] and dlg.nodo()['modo'] == E.COMP)
    esperar(lambda: dlg.cargado, 20)
    dlg.atras()
    esperar(lambda: dlg.cargado, 20)

    titulo("6. EL MENÚ DEL BOTÓN DERECHO NAVEGA AQUÍ")
    from PyQt5.QtWidgets import QMenu, QDialog
    dialogos = []
    orig_menu, orig_dlg = QMenu.exec_, QDialog.exec_

    def menu_que_elige(self, *a, **k):
        for act in self.actions():
            if "En qué ensamblajes" in act.text():
                act.trigger()
                break
    QMenu.exec_ = menu_que_elige
    QDialog.exec_ = lambda self: (dialogos.append(self), 0)[1]
    try:
        r, sub = buscar_fila(dlg, mod, lambda d: d['ext'] == '.sldasm' and d['ruta'])
        dlg.tabla.selectRow(r)
        dlg._menu(dlg.tabla, dlg.tabla.viewport().mapToGlobal(dlg.tabla.visualItemRect(
            dlg.tabla.item(r, 0)).center()))
    finally:
        QMenu.exec_, QDialog.exec_ = orig_menu, orig_dlg
    comprobar("«¿En qué ensamblajes se usa?» navega en esta misma ventana",
              dlg.nodo()['ruta'] == sub['ruta'] and dlg.nodo()['modo'] == E.DONDE)
    comprobar("sin abrir otra ventana encima", not dialogos)
    esperar(lambda: dlg.cargado, 20)

    titulo("7. EXPORTAR")
    dlg.ir_a_posicion(0)
    esperar(lambda: dlg.cargado, 20)
    from PyQt5.QtWidgets import QFileDialog
    destino = os.path.join(tempfile.mkdtemp(prefix="pruebas_explorador_"), "despiece.csv")
    orig = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (destino, ""))
    try:
        dlg._exportar()
    finally:
        QFileDialog.getSaveFileName = orig
    filas = list(csv.reader(open(destino, encoding="utf-8-sig"), delimiter=";"))
    comprobar("el CSV lleva cabecera y una fila por componente",
              len(filas) == len(dlg.filas) + 1, "%d filas" % (len(filas) - 1))
    comprobar("con los nombres de verdad",
              sorted(f[0] for f in filas[1:]) == sorted(d['nombre'] for d in dlg.filas))
    dlg.done(0)
    comprobar("al cerrar no queda ningún hilo vivo",
              all(not w.isRunning() for w in dlg._tareas))


def probar_pieza_comun(win, mod, pieza):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication
    E = mod.ExploradorConjunto
    titulo("8. «DÓNDE SE USA» DE LA PIEZA MÁS USADA: sin congelar")
    huecos = []
    ultimo = [time.perf_counter()]

    def tic():
        ahora = time.perf_counter()
        huecos.append(ahora - ultimo[0])
        ultimo[0] = ahora
    reloj = QTimer()
    reloj.setInterval(20)
    reloj.timeout.connect(tic)
    reloj.start()
    t0 = time.perf_counter()
    dlg = E(win, pieza, E.DONDE)
    dlg.resize(1300, 820)
    dlg.show()
    t_abrir = time.perf_counter() - t0
    esperar(lambda: dlg.cargado, 30)
    sin_tareas(dlg, 30)
    bombear(0.5)
    reloj.stop()
    peor = max(huecos) if huecos else 99
    comprobar("se abre al instante", t_abrir < 0.5, "%.2f s" % t_abrir)
    comprobar("trae todos los conjuntos",
              len(dlg.filas) == len(win.db.buscar_ensamblajes_de(pieza)),
              "%d conjuntos" % len(dlg.filas))
    comprobar("la ventana nunca se queda congelada más de 1 s",
              peor < 1.0, "peor: %.2f s (antes ~3 s)" % peor)
    comprobar("tiene las miniaturas en memoria (JPEG)", len(dlg._jpeg) > 1000,
              "%d" % len(dlg._jpeg))
    comprobar("pero solo descomprime las que se ven",
              0 < len(dlg._iconos) < 200, "%d de %d" % (len(dlg._iconos), len(dlg._jpeg)))
    dlg.done(0)

    titulo("9. CERRAR A MITAD DE CARGA")
    dlg = E(win, pieza, E.DONDE)
    dlg.show()
    try:
        dlg.done(0)
        ok = True
    except Exception as e:
        ok = False
        print("   ", e)
    comprobar("cerrar mientras carga no revienta", ok)
    comprobar("y para los hilos antes de irse", all(not w.isRunning() for w in dlg._tareas))
    bombear(0.5)


def probar_entradas(win, mod, ens, pieza):
    from PyQt5.QtWidgets import QDialog
    E = mod.ExploradorConjunto
    titulo("10. LOS ACCESOS DE SIEMPRE ABREN EL EXPLORADOR")
    vistos = []
    orig = QDialog.exec_
    QDialog.exec_ = lambda self: (vistos.append(self), 0)[1]
    try:
        win.mostrar_despiece(ens)
        win.mostrar_donde_se_usa(pieza)
    finally:
        QDialog.exec_ = orig
    comprobar("«Ver componentes» abre el explorador en Componentes",
              len(vistos) >= 1 and isinstance(vistos[0], E) and vistos[0].nodo()['modo'] == E.COMP)
    comprobar("«¿En qué ensamblajes se usa?» lo abre en Dónde se usa",
              len(vistos) >= 2 and isinstance(vistos[1], E) and vistos[1].nodo()['modo'] == E.DONDE)
    for d in vistos:
        esperar(lambda: d.cargado, 30)
        d.done(0)


def resumen():
    print()
    print("=" * 76)
    fallos = [r for r in RESULTADOS if not r[1]]
    print("  %d pruebas · %d OK · %d FALLO" % (len(RESULTADOS), len(RESULTADOS) - len(fallos),
                                            len(fallos)))
    for t, _ok, d in fallos:
        print("   FALLO %s %s" % (t, d))
    print("=" * 76)
    return 1 if fallos else 0


def main():
    from PyQt5.QtWidgets import QApplication
    salida = {}

    def _exec(self):
        sys.stdout = TEE
        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            mod = sys.modules["__main__"]
            print("PRUEBAS DEL EXPLORADOR DE CONJUNTOS")
            win._carga_inicial_diferida()
            esperar(lambda: win.db.esta_disponible(), 30)
            ens, pieza = elegir_muestras(win.db)
            comprobar("hay un conjunto de muestra con subconjunto y pieza", ens, str(ens)[-60:])
            comprobar("y una pieza muy usada", pieza, str(pieza)[-60:])
            if ens and pieza:
                dlg = probar_despiece(win, mod, ens)
                probar_navegacion(win, mod, dlg, ens)
                probar_pieza_comun(win, mod, pieza)
                probar_entradas(win, mod, ens, pieza)
            win._detener_workers_de_fondo()
        except Exception:
            print("EXCEPCION:")
            traceback.print_exc()
            RESULTADOS.append(("la batería termina sin excepciones", False, ""))
        salida["codigo"] = resumen()
        import arnes_pruebas
        arnes_pruebas.salir(salida["codigo"], TEE)
        return 0

    QApplication.exec_ = _exec
    sys.argv = ["buscar_piezas.py"]
    try:
        runpy.run_path(os.path.join(RAIZ, "buscar_piezas.py"), run_name="__main__")
    except SystemExit:
        pass
    return salida.get("codigo", 1)


if __name__ == "__main__":
    import arnes_pruebas
    arnes_pruebas.salir(main(), TEE)
