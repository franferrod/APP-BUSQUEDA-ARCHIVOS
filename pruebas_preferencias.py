# -*- coding: utf-8 -*-
"""Pruebas de que los filtros son de CADA EQUIPO, no de la oficina (V2.3.2).

El fallo: los cuatro filtros que la app recuerda entre sesiones --origenes,
anos, carpetas y tipos-- se guardaban en `buscador.preferencias`, una tabla de
dos columnas (clave, valor) COMPARTIDA por toda la oficina. Una sola fila por
clave para todos. Asi que los filtros del ultimo que cerraba la app se los
encontraba puestos el siguiente que la abria, y le devolvia de menos sin que
supiera por que: ni un error en pantalla, solo resultados que faltan.

Es el mismo fallo que ya se corrigio con la ultima busqueda (V2.0.3) y con la
geometria de ventana (V2.0.8). Estos cuatro se quedaron atras.

    python pruebas_preferencias.py
"""
import os
import runpy
import sys
import tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ALSI_SIN_DIALOGOS"] = "1"
os.environ["ALSI_SIN_CANDADO"] = "1"
# V2.3.1: las pruebas NO escriben en la tabla de preferencias, que es
# compartida por toda la oficina.
os.environ["ALSI_SIN_PREFERENCIAS"] = "1"
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

INFORME = os.path.join(RAIZ, "pruebas_preferencias_resultado.txt")
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
    from PyQt5.QtCore import QSettings, Qt
    salida = {}

    CARPETA = tempfile.mkdtemp(prefix="alsi_equipos_")
    VIVOS = []   # referencias: si Qt destruye estos QSettings a media
                 # salida, el proceso se cae aunque todo haya pasado

    def ajustes_de_equipo(nombre):
        """Un QSettings en fichero: simula el registro de OTRO ordenador."""
        qs = QSettings(os.path.join(CARPETA, nombre + ".ini"), QSettings.IniFormat)
        VIVOS.append(qs)
        return qs

    def _exec(self):
        ajustes_reales = None
        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            win._carga_inicial_diferida()
            # Los ajustes de verdad de este equipo, para devolverlos al final:
            # esta bateria los sustituye por otros de fichero para simular
            # ordenadores distintos, y dejarlos cambiados tumba el cierre.
            ajustes_reales = win.qsettings

            emitir("=" * 70)
            emitir("  LOS FILTROS SON DE CADA EQUIPO, NO DE LA OFICINA")
            emitir("=" * 70)

            CLAVES = list(win.FILTROS_RECORDADOS)

            # ── 1. Ya no se escribe en la tabla comun ─────────────────────
            titulo("1. Guardar no toca la tabla compartida")
            escrituras = []
            original_save = win.controller.save_preference
            win.controller.save_preference = (
                lambda k, v: (escrituras.append(k), original_save(k, v))[1])
            equipo_a = ajustes_de_equipo("equipoA")
            win.qsettings = equipo_a
            for i in range(win.list_companeros.count()):
                win.list_companeros.item(i).setCheckState(
                    Qt.Checked if i == 0 else Qt.Unchecked)
            try:
                win.save_window_state()
            finally:
                win.controller.save_preference = original_save
            comprobar("ninguna de las claves de filtro va a la tabla comun",
                      not [k for k in escrituras if k in CLAVES],
                      "escrituras: %s" % (escrituras or "ninguna"))

            # ── 2. Se guardan en los ajustes del equipo ───────────────────
            titulo("2. Se guardan en los ajustes de ESTE equipo")
            guardado = equipo_a.value("companeros_checked", None)
            comprobar("el filtro de origenes queda en los ajustes locales",
                      guardado is not None, repr(guardado))
            comprobar("y es lo que estaba marcado",
                      str(guardado) == win.list_companeros.item(0).text(),
                      "%r vs %r" % (guardado, win.list_companeros.item(0).text()))
            for clave in CLAVES:
                comprobar("  se guarda '%s'" % clave,
                          equipo_a.value(clave, None) is not None)

            # ── 3. Dos equipos no se pisan ────────────────────────────────
            titulo("3. Lo que guarda un equipo no lo ve el otro")
            equipo_b = ajustes_de_equipo("equipoB")
            equipo_a.setValue("tipos_checked", "PIEZAS")
            equipo_b.setValue("tipos_checked", "PIEZAS,ENSAMBLAJES,PDF")
            win.qsettings = equipo_a
            leido_a = win._leer_filtro_guardado("tipos_checked")
            win.qsettings = equipo_b
            leido_b = win._leer_filtro_guardado("tipos_checked")
            comprobar("cada equipo lee lo suyo", leido_a != leido_b,
                      "A=%r  B=%r" % (leido_a, leido_b))
            comprobar("el equipo A conserva lo suyo", leido_a == "PIEZAS")
            comprobar("el equipo B conserva lo suyo",
                      leido_b == "PIEZAS,ENSAMBLAJES,PDF")

            # ── 4. La siembra: primera vez tras actualizar ────────────────
            titulo("4. La primera vez hereda lo que hubiera en comun")
            equipo_c = ajustes_de_equipo("equipoC")   # sin nada local
            win.qsettings = equipo_c
            comun = {"carpetas_checked": "MECANICA,LAYOUT"}
            original_load = win.controller.load_preference
            win.controller.load_preference = (
                lambda k, d=None: comun.get(k, d if d is not None else ""))
            try:
                heredado = win._leer_filtro_guardado("carpetas_checked")
                comprobar("un equipo nuevo hereda el valor comun",
                          heredado == "MECANICA,LAYOUT", repr(heredado))
                comprobar("y queda grabado en sus propios ajustes",
                          str(equipo_c.value("carpetas_checked", "")) == "MECANICA,LAYOUT")
                # A partir de aqui manda lo local, aunque cambie lo comun
                comun["carpetas_checked"] = "OTRA COSA"
                comprobar("la segunda vez ya NO vuelve a heredar",
                          win._leer_filtro_guardado("carpetas_checked") == "MECANICA,LAYOUT")
            finally:
                win.controller.load_preference = original_load

            # ── 5. Un valor local vacio es una decision, no un hueco ──────
            titulo("5. 'Ninguno' se respeta, no se resiembra")
            equipo_d = ajustes_de_equipo("equipoD")
            equipo_d.setValue("tipos_checked", "")     # el usuario desmarco todo
            win.qsettings = equipo_d
            pedidos = []
            original_load = win.controller.load_preference
            win.controller.load_preference = (
                lambda k, d=None: (pedidos.append(k), "PIEZAS")[1])
            try:
                v = win._leer_filtro_guardado("tipos_checked")
                comprobar("un vacio guardado a propósito se respeta", v == "",
                          repr(v))
                comprobar("y no se pregunta a la tabla comun",
                          "tipos_checked" not in pedidos, str(pedidos))
            finally:
                win.controller.load_preference = original_load

            # ── 6. Sin servidor no se rompe ───────────────────────────────
            titulo("6. Sin servidor tampoco se rompe")
            equipo_e = ajustes_de_equipo("equipoE")
            win.qsettings = equipo_e
            original_load = win.controller.load_preference

            def load_que_falla(k, d=None):
                raise RuntimeError("sin conexion")

            win.controller.load_preference = load_que_falla
            try:
                v = win._leer_filtro_guardado("años_checked")
                comprobar("si la consulta falla devuelve vacio sin reventar", v == "",
                          repr(v))
            except Exception as e:
                comprobar("si la consulta falla devuelve vacio sin reventar", False, str(e))
            finally:
                win.controller.load_preference = original_load

            # ── 7. La tabla comun queda intacta ───────────────────────────
            titulo("7. La tabla compartida no se ha tocado")
            import psycopg2
            from models import PG_CONFIG
            cn = psycopg2.connect(**PG_CONFIG)
            cur = cn.cursor()
            cur.execute("SELECT clave FROM buscador.preferencias")
            claves_bd = {r[0] for r in cur.fetchall()}
            cn.close()
            comprobar("no se han creado claves de prueba en la tabla comun",
                      not any(k.startswith("PRUEBA") for k in claves_bd),
                      str(sorted(claves_bd)))

        except Exception as e:
            import traceback
            emitir(traceback.format_exc())
            comprobar("la bateria termina sin excepciones", False, str(e))

        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            try:
                if ajustes_reales is not None:
                    win.qsettings = ajustes_reales
            except Exception:
                pass
            win._detener_workers_de_fondo()
        except Exception:
            pass

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
