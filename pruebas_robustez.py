# -*- coding: utf-8 -*-
"""Bateria de pruebas de robustez del Buscador de Piezas ALSI (V2.1.1).

Nace de la incidencia "no me abre la app" (Pablo y Marcos, agosto 2026). No
pretende cubrir cada funcion: blinda lo que puede dejar a un companero sin
poder trabajar -- el arranque, la perdida del servidor, la coordinacion de la
busqueda con el refinado, y que un error se pueda mandar tal cual.

    python pruebas_robustez.py            escenario con el servidor OK
    python pruebas_robustez.py --caido    simula el servidor inaccesible
    python pruebas_robustez.py --todo     lanza los dos, uno por proceso

Devuelve 0 si todo pasa y distinto de 0 si algo falla, para poder automatizarla.
"""
import os
import subprocess
import sys
import time
import traceback

RAIZ = os.path.dirname(os.path.abspath(__file__))
CAIDO = "--caido" in sys.argv

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ALSI_SIN_DIALOGOS"] = "1"      # ningun dialogo debe bloquear la bateria
os.environ["ALSI_SIN_CANDADO"] = "1"
# V2.3.1: las pruebas NO escriben en la tabla de preferencias, que es
# compartida por toda la oficina.
os.environ["ALSI_SIN_PREFERENCIAS"] = "1"       # sin esto no se puede probar con la app abierta
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

if CAIDO:
    # Se fabrica un config.ini que apunta a una IP del rango reservado para
    # pruebas (RFC 5737): existe, se enruta y NO contesta -- justo el caso del
    # equipo que no llega al servidor. Asi la bateria es autosuficiente.
    import configparser
    import tempfile
    _origen = os.path.join(RAIZ, "config.ini")
    _cfg = configparser.ConfigParser()
    _cfg.read(_origen, encoding="utf-8")
    _cfg["database"]["host"] = "192.0.2.1"
    _falso = os.path.join(tempfile.gettempdir(), "alsi_config_caido.ini")
    with open(_falso, "w", encoding="utf-8") as _f:
        _cfg.write(_f)
    os.environ["ALSI_CONFIG_INI"] = _falso

class _Tee:
    """La salida del .exe se pierde al canalizarla en algunos entornos, y un
    informe de pruebas que no se puede leer no sirve. Se escribe siempre a
    disco ademas de a la consola."""

    def __init__(self, ruta):
        self.f = open(ruta, "w", encoding="utf-8")

    def write(self, texto):
        try:
            sys.__stdout__.write(texto)
        except Exception:
            pass
        self.f.write(texto)
        self.f.flush()
        try:
            os.fsync(self.f.fileno())   # sobrevive a un cuelgue duro
        except Exception:
            pass

    def flush(self):
        try:
            sys.__stdout__.flush()
        except Exception:
            pass
        self.f.flush()


INFORME = os.path.join(RAIZ, "pruebas_resultado%s.txt" % ("_caido" if CAIDO else ""))
# OJO: buscar_piezas.py redirige sys.stdout/sys.stderr a startup_error.log en
# cuanto se importa (resto de una depuracion antigua de PyInstaller). Por eso se
# guarda el Tee aparte y se vuelve a poner despues de arrancar la app.
TEE = _Tee(INFORME)
sys.stdout = TEE

RESULTADOS = []


def comprobar(bloque, texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((bloque, texto, ok, detalle))
    marca = "OK" if ok else "FALLO"
    extra = ("  · " + detalle) if detalle else ""
    print("  %-58s %s%s" % (texto, marca, extra))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 66 - len(t))))


def esperar(cond, seg=30):
    from PyQt5.QtWidgets import QApplication
    t0 = time.time()
    while not cond() and time.time() - t0 < seg:
        QApplication.processEvents()
        time.sleep(0.05)
    return cond()


def _log_contiene(txt):
    try:
        ruta = os.path.expanduser("~/.alsi_busqueda/app.log")
        with open(ruta, encoding="utf-8", errors="ignore") as f:
            return txt in f.read()[-200000:]
    except Exception:
        return False


def _fuente_sin_qmessagebox_critical():
    """Solo debe quedar el de avisar_usuario (respaldo cuando no hay interfaz)."""
    with open(os.path.join(RAIZ, "buscar_piezas.py"), encoding="utf-8") as f:
        return f.read().count("QMessageBox.critical") <= 1


# ---------------------------------------------------------------------------
#  BLOQUES DE PRUEBA
# ---------------------------------------------------------------------------

def probar_arranque(win, mod, t_ventana):
    titulo("1. ARRANQUE")
    comprobar("arranque", "la ventana se muestra", win.isVisible())
    comprobar("arranque", "aparece en menos de 4 s pase lo que pase",
              t_ventana < 4, "%.2fs" % t_ventana)
    comprobar("arranque", "no se toca la base de datos antes de mostrarla",
              win.db._pool is None)
    comprobar("arranque", "el registro guarda las fases del arranque",
              _log_contiene("[arranque] ventana visible"))


def probar_red(win, mod):
    titulo("2. RED Y BASE DE DATOS")
    t0 = time.time()
    win._carga_inicial_diferida()
    bloqueo = time.time() - t0
    comprobar("red", "la carga inicial no congela la ventana (< 2 s)",
              bloqueo < 2.0, "%.2fs" % bloqueo)

    if CAIDO:
        comprobar("red", "sale el aviso de que no hay servidor",
                  esperar(lambda: win.bd_banner.isVisible(), 30))
        comprobar("red", "el aviso dice a que servidor no llega",
                  "192.0.2.1" in win.lbl_bd.text())
        comprobar("red", "la app sabe que no hay base de datos",
                  not win.db.esta_disponible())
        t0 = time.time()
        win._reintentar_bd(manual=True)
        comprobar("red", "el boton Reintentar no congela la ventana",
                  time.time() - t0 < 1.0, "%.2fs" % (time.time() - t0))
        comprobar("red", "una preferencia sin servidor cae a su valor por defecto",
                  win.db.obtener_preferencia("no_existe_xyz", "DEFECTO") == "DEFECTO")
        comprobar("red", "guardar una preferencia sin servidor no revienta",
                  win.db.guardar_preferencia("prueba_xyz", "1") is None)
        esperar(lambda: not win._conex_worker.isRunning(), 20)
    else:
        esperar(lambda: win.list_clientes.count() > 0)
        comprobar("red", "conecta con la base de datos", win.db.esta_disponible())
        comprobar("red", "no sale ningun aviso de error", not win.bd_banner.isVisible())
        comprobar("red", "los filtros se pueblan",
                  win.list_clientes.count() > 0,
                  "%d clientes" % win.list_clientes.count())

    titulo("3. SONDEO DEL NAS CON TOPE DE TIEMPO")
    b = chr(92)
    for ruta in (b + b + "192.0.2.1" + b + "Oficina Tecnica",
                 b + b + "NOEXISTE-ZZZ" + b + "x"):
        t0 = time.time()
        r = mod.existe_con_limite(ruta, 3.0)
        seg = time.time() - t0
        comprobar("nas", "%s se descarta en menos de 3,6 s" % ruta[:28],
                  (not r) and seg <= 3.6, "%.1fs" % seg)


def probar_refinado(win, mod):
    """El fallo reportado: refinar sin haber pulsado Enter en la busqueda."""
    titulo("4. COORDINACION BUSQUEDA GENERAL <-> REFINADO")
    if CAIDO:
        print("  (se omite: necesita base de datos)")
        return

    # 4.1 escribir arriba SIN Enter y aplicar el refinado
    win._res_base = []
    win._termino_base = None
    win._refinados = []
    win._refinado_pendiente = None
    win.input_buscar.setText("cinta a450")
    win.input_refinar.setText("motor")
    win._agregar_refinado()
    lanzada = esperar(lambda: getattr(win, "_termino_base", None) == "cinta a450", 60)
    comprobar("refinado", "refinar sin pulsar Enter lanza la busqueda general",
              lanzada, "termino_base=%r" % getattr(win, "_termino_base", None))
    aplicado = esperar(lambda: len(getattr(win, "_refinados", [])) == 1, 60)
    comprobar("refinado", "y aplica el refinado cuando llegan los resultados",
              aplicado, "%r" % (getattr(win, "_refinados", []),))
    comprobar("refinado", "el refinado aplicado es el que se escribio",
              (getattr(win, "_refinados", []) or [None])[0] == ("contiene", "motor"))
    comprobar("refinado", "no queda ningun refinado pendiente colgado",
              getattr(win, "_refinado_pendiente", None) is None)

    # 4.2 con la base al dia no se repite la busqueda
    win.input_refinar.setText("rem")
    win._agregar_refinado()
    comprobar("refinado", "si la base ya corresponde, refina sin repetir la busqueda",
              len(win._refinados) == 2
              and getattr(win, "_refinado_pendiente", None) is None)

    # 4.3 refinado negativo
    win.input_refinar.setText("tornillo")
    win._agregar_refinado(negativo=True)
    comprobar("refinado", "el refinado negativo se apila como 'no_contiene'",
              win._refinados[-1][0] == "no_contiene")

    # 4.4 quitar y limpiar
    n = len(win._refinados)
    win._quitar_refinado()
    comprobar("refinado", "quitar un nivel conserva los demas",
              len(win._refinados) == n - 1)
    win._limpiar_refinados()
    comprobar("refinado", "limpiar vuelve a la busqueda base", win._refinados == [])

    # 4.5 refinar sin nada escrito: avisa y no inventa
    win.input_buscar.setText("")
    win._res_base = []
    win._termino_base = None
    win.input_refinar.setText("algo")
    win._agregar_refinado()
    comprobar("refinado", "refinar sin busqueda no deja nada pendiente",
              getattr(win, "_refinado_pendiente", None) is None)

    # 4.6 si la busqueda general no llega a lanzarse, no queda pendiente
    for i in range(win.list_companeros.count()):
        win.list_companeros.item(i).setCheckState(0)      # sin origenes
    win.input_buscar.setText("pletina")
    win.input_refinar.setText("montaje")
    win._agregar_refinado()
    comprobar("refinado", "sin origenes marcados el refinado no queda colgado",
              getattr(win, "_refinado_pendiente", None) is None)
    comprobar("refinado", "y el texto del refinado vuelve a su cuadro",
              win.input_refinar.text() == "montaje")
    for i in range(win.list_companeros.count()):
        win.list_companeros.item(i).setCheckState(2)      # restaurar


def probar_errores(win, mod):
    titulo("5. ERRORES QUE SE PUEDEN MANDAR")
    informe = mod.informe_de_error("Titulo de prueba", "Mensaje de prueba",
                                   "Detalle tecnico de prueba")
    for clave in ("Version:", "Equipo:", "Fecha:", "Mensaje de prueba",
                  "Detalle tecnico de prueba", "Ultimas lineas del registro"):
        comprobar("errores", "el informe incluye '%s'" % clave, clave in informe)
    comprobar("errores", "el informe lleva la version correcta",
              mod.APP_VERSION in informe)

    dlg = mod.DialogoError("Prueba", "Mensaje de la prueba", "Detalle", win)
    dlg._copiar()
    from PyQt5.QtWidgets import QApplication
    pegado = QApplication.clipboard().text()
    comprobar("errores", "'Copiar para enviar' deja el informe en el portapapeles",
              "Mensaje de la prueba" in pegado and "Version:" in pegado)
    comprobar("errores", "el dialogo confirma que se ha copiado",
              "Copiado" in dlg.lbl_copiado.text())
    dlg.close()

    comprobar("errores", "mostrar_error nunca revienta (modo desatendido)",
              mod.mostrar_error("t", "m", "d", win) is None)
    comprobar("errores", "todos los errores pasan por el dialogo copiable",
              _fuente_sin_qmessagebox_critical())


def probar_diagnostico(win, mod):
    titulo("6. DIAGNOSTICO")
    t0 = time.time()
    informe = mod.generar_diagnostico()
    seg = time.time() - t0
    comprobar("diagnostico", "se genera en un tiempo razonable",
              seg < 40, "%.1fs" % seg)
    for clave in ("Version de la app", "Servidor", "Puerto TCP",
                  "Consulta de prueba", "Host en uso", "TEMP escribible", "Log"):
        comprobar("diagnostico", "el informe cubre '%s'" % clave, clave in informe)
    comprobar("diagnostico", "no cuela el ruido de Qt entre los errores",
              " - Qt: " not in informe)


def probar_instancia_unica(mod):
    titulo("7. INSTANCIA UNICA Y CANDADOS HUERFANOS")
    import tempfile
    from PyQt5.QtCore import QLockFile
    ruta = os.path.join(tempfile.gettempdir(), "alsi_prueba_candado.lock")
    try:
        os.remove(ruta)
    except OSError:
        pass
    primero = QLockFile(ruta)
    comprobar("instancia", "la primera instancia coge el candado", primero.tryLock(200))
    segundo = QLockFile(ruta)
    segundo.setStaleLockTime(30000)
    comprobar("instancia", "una segunda instancia NO puede abrirse",
              not segundo.tryLock(200))
    primero.unlock()
    comprobar("instancia", "al cerrar la primera, la siguiente ya puede abrir",
              segundo.tryLock(200))
    segundo.unlock()
    try:
        os.remove(ruta)
    except OSError:
        pass

    # La valvula de seguridad: un candado de un proceso muerto no bloquea
    comprobar("instancia", "el proceso actual se detecta como vivo",
              mod.proceso_vivo(os.getpid()))
    comprobar("instancia", "un PID inexistente se detecta como muerto",
              not mod.proceso_vivo(999999))


def probar_rutas_unc():
    """Una ruta UNC se rompe con un solo caracter y no da error visible."""
    titulo("8. RUTAS DE RED BIEN FORMADAS")
    import re
    b = chr(92)
    esperado = b + b + "SERVIDOR" + b + "Oficina Tecnica"
    malas = []
    with open(os.path.join(RAIZ, "buscar_piezas.py"), encoding="utf-8") as f:
        for n, linea in enumerate(f, 1):
            m = re.search(r'existe_con_limite\((r?"[^"]*")', linea)
            if m and "%s" in m.group(1):
                if (eval(m.group(1)) % "SERVIDOR") != esperado:
                    malas.append("linea %d" % n)
    comprobar("unc", "todas las rutas UNC del codigo son validas",
              not malas, ", ".join(malas))


def probar_datos(win):
    titulo("9. CONSULTAS REALES CONTRA LA BASE DE DATOS")
    if CAIDO:
        print("  (se omite: necesita base de datos)")
        return
    for termino, minimo in (("tuerca m16", 1), ("pletina", 10), ("cinta", 10)):
        t0 = time.time()
        r = win.db.buscar(termino)
        comprobar("datos", "buscar '%s' devuelve resultados" % termino,
                  len(r) >= minimo, "%d en %.2fs" % (len(r), time.time() - t0))
    comprobar("datos", "una busqueda sin resultados devuelve lista vacia",
              win.db.buscar("zzzz-no-existe-zzzz") == [])


# ---------------------------------------------------------------------------
def resumen():
    print()
    print("=" * 74)
    fallos = [r for r in RESULTADOS if not r[2]]
    porbloque = {}
    for bloque, _t, ok, _d in RESULTADOS:
        acum = porbloque.setdefault(bloque, [0, 0])
        acum[0] += 1
        acum[1] += 1 if ok else 0
    for bloque, (total, ok) in porbloque.items():
        print("  %-14s %d/%d" % (bloque, ok, total))
    print("-" * 74)
    print("  TOTAL: %d de %d  ·  ESCENARIO: %s"
          % (len(RESULTADOS) - len(fallos), len(RESULTADOS),
             "SERVIDOR CAIDO" if CAIDO else "SERVIDOR OK"))
    if fallos:
        print()
        print("  FALLOS:")
        for _b, t, _ok, d in fallos:
            print("    - %s %s" % (t, ("(%s)" % d) if d else ""))
    print("=" * 74)
    return 0 if not fallos else 1


def main():
    import runpy
    from PyQt5.QtWidgets import QApplication
    t_inicio = time.time()
    salida = {}

    def _exec(self):
        sys.stdout = TEE          # la app se habia quedado con la salida
        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            mod = sys.modules["__main__"]
            t_ventana = time.time() - t_inicio
            print("BATERIA DE ROBUSTEZ - Buscador de Piezas ALSI v%s" % mod.APP_VERSION)
            print("Escenario: %s" % ("SERVIDOR CAIDO" if CAIDO else "SERVIDOR OK"))
            probar_arranque(win, mod, t_ventana)
            probar_red(win, mod)
            probar_refinado(win, mod)
            probar_errores(win, mod)
            probar_diagnostico(win, mod)
            probar_instancia_unica(mod)
            probar_rutas_unc()
            probar_datos(win)
        except Exception:
            print("EXCEPCION EN LA BATERIA:")
            traceback.print_exc()
            RESULTADOS.append(("bateria", "la bateria termina sin excepciones",
                               False, ""))
        # V2.3.1: parar los hilos de fondo antes de salir, igual que hacen
        # closeEvent y aboutToQuit en la app real. Este arnes no pasa por
        # ninguno de los dos, y Qt destruyendo un QThread en marcha tumba el
        # proceso al terminar aunque las comprobaciones hayan pasado.
        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            win._detener_workers_de_fondo()
        except Exception:
            pass
        salida["codigo"] = resumen()
        return 0

    QApplication.exec_ = _exec
    sys.argv = ["buscar_piezas.py"]
    try:
        runpy.run_path(os.path.join(RAIZ, "buscar_piezas.py"), run_name="__main__")
    except SystemExit:
        pass
    return salida.get("codigo", 1)


if __name__ == "__main__":
    if "--todo" in sys.argv:
        codigo = 0
        for extra in ([], ["--caido"]):
            print()
            res = subprocess.run([sys.executable, os.path.abspath(__file__)] + extra)
            codigo = codigo or res.returncode
        sys.exit(codigo)
    sys.exit(main())
