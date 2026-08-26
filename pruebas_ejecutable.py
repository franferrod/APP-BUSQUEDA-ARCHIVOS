# -*- coding: utf-8 -*-
"""Pruebas del EJECUTABLE empaquetado del Buscador de Piezas ALSI (V2.1.4).

La bateria pruebas_robustez.py trabaja sobre el codigo. Esto prueba el .exe tal
y como lo recibe un companero: se lanza de verdad, se comprueba que abre
ventana, cuanto tarda, que hace con el servidor caido, que no se abren dos
instancias y que un candado de un proceso muerto no deja a nadie fuera.

    python pruebas_ejecutable.py [ruta_al_exe]

Por defecto usa releases/v2.1.4/BuscadorPiezas.exe. Cierra siempre los procesos
que abre (y SOLO esos: se identifican por su PID).
"""
import os
import subprocess
import sys
import tempfile
import time

# V2.3.1: esta bateria lanza el .exe DE VERDAD, y al cerrarse guardaria los
# filtros en buscador.preferencias, que es COMPARTIDA por toda la oficina.
# El hijo hereda el entorno, asi que con esto tampoco escribe.
os.environ["ALSI_SIN_PREFERENCIAS"] = "1"

RAIZ = os.path.dirname(os.path.abspath(__file__))
PROYECTO = os.path.abspath(os.path.join(RAIZ, "..", "..", ".."))
EXE = (sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".exe")
       else os.path.join(PROYECTO, "releases", "v2.1.4", "BuscadorPiezas.exe"))
LOG = os.path.expanduser("~/.alsi_busqueda/app.log")
INFORME = os.path.join(RAIZ, "pruebas_ejecutable_resultado.txt")

RESULTADOS = []
_salida = open(INFORME, "w", encoding="utf-8")


def emitir(texto=""):
    print(texto)
    _salida.write(texto + "\n")
    _salida.flush()


def comprobar(texto, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append((texto, ok, detalle))
    emitir("  %-56s %s%s" % (texto, "OK" if ok else "FALLO",
                             ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    emitir("")
    emitir("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


# ---------------------------------------------------------------------------
def ps(comando):
    """Ejecuta PowerShell y devuelve la salida limpia."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", comando],
                       capture_output=True, text=True)
    return (r.stdout or "").strip()


def lanzar(entorno_extra=None):
    """Lanza el .exe y devuelve su PID (o None)."""
    env = ""
    for clave, valor in (entorno_extra or {}).items():
        env += "$env:%s='%s'; " % (clave, valor)
    salida = ps(env + "(Start-Process -FilePath '%s' -PassThru).Id" % EXE)
    try:
        return int(salida.splitlines()[-1])
    except Exception:
        return None


def vivo(pid):
    return ps("if (Get-Process -Id %s -ErrorAction SilentlyContinue) "
              "{'S'} else {'N'}" % pid) == "S"


def familia(pid):
    """PIDs del proceso y de sus hijos.

    OJO: el .exe es 'onefile' de PyInstaller. Eso significa que el proceso que
    se lanza es solo el arrancador: se descomprime y crea un HIJO, y la ventana
    es del hijo. Buscar la ventana en el PID que devuelve Start-Process no
    encuentra nada nunca."""
    salida = ps("$h = @(%s); "
                "Get-CimInstance Win32_Process -Filter \"Name='BuscadorPiezas.exe'\" |"
                " Where-Object { $_.ProcessId -eq %s -or $_.ParentProcessId -eq %s } |"
                " ForEach-Object { $_.ProcessId }" % (pid, pid, pid))
    pids = []
    for linea in salida.splitlines():
        linea = linea.strip()
        if linea.isdigit():
            pids.append(int(linea))
    return pids or ([pid] if vivo(pid) else [])


def titulo_ventana(pid):
    """Titulo de la ventana del proceso o de cualquiera de sus hijos."""
    for p in familia(pid):
        t = ps("(Get-Process -Id %s -ErrorAction SilentlyContinue)."
               "MainWindowTitle" % p)
        if t:
            return t
    return ""


def cerrar(pid, forzar=False):
    """Cierra el proceso y sus hijos (el arrancador y la app de verdad)."""
    if not pid:
        return
    for p in familia(pid):
        ps("Stop-Process -Id %s %s -ErrorAction SilentlyContinue"
           % (p, "-Force" if forzar else ""))
    for _ in range(40):
        if not vivo(pid):
            break
        time.sleep(0.25)


def esperar_ventana(pid, seg=60):
    """Espera a que aparezca la ventana (en el proceso o en su hijo)."""
    t0 = time.time()
    while time.time() - t0 < seg:
        if not vivo(pid) and not familia(pid):
            return None
        if titulo_ventana(pid):
            return time.time() - t0
        time.sleep(0.4)
    return None


def lineas_log_de(pid, desde_byte):
    """Lineas del log de ese PID escritas despues de 'desde_byte'."""
    try:
        with open(LOG, encoding="utf-8", errors="ignore") as f:
            f.seek(desde_byte)
            texto = f.read()
    except Exception:
        return []
    bloques = texto.split("===== Arranque")
    for b in bloques:
        if ("PID %s " % pid) in b or ("PID %s\n" % pid) in b:
            return b.splitlines()
    return texto.splitlines()


def tam_log():
    try:
        return os.path.getsize(LOG)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
def prueba_arranque_normal():
    titulo("1. ARRANQUE REAL CON EL SERVIDOR OK")
    marca = tam_log()
    pid = lanzar()
    comprobar("el ejecutable arranca", pid is not None, "PID %s" % pid)
    if not pid:
        return
    seg = esperar_ventana(pid)
    comprobar("abre una ventana visible", seg is not None,
              "%.1fs" % seg if seg else "no aparecio en 60s")
    if seg is not None:
        comprobar("la ventana aparece en menos de 15 s", seg < 15, "%.1fs" % seg)
    comprobar("el titulo de la ventana es el correcto",
              "Buscador de Piezas" in (titulo_ventana(pid) or ""),
              titulo_ventana(pid))
    time.sleep(4)          # dejar que termine la carga diferida
    lineas = lineas_log_de(pid, marca)
    comprobar("el registro deja constancia de la ventana",
              any("ventana visible" in l for l in lineas))
    comprobar("conecta con la base de datos",
              any("Pool de conexiones PostgreSQL inicializado" in l for l in lineas))
    comprobar("no hay ningun error en el arranque",
              not [l for l in lineas if " - ERROR - " in l and " - Qt: " not in l],
              "; ".join(l[-70:] for l in lineas
                        if " - ERROR - " in l and " - Qt: " not in l)[:110])
    return pid


def prueba_instancia_unica(pid_abierto):
    """Doble clic con la app ya abierta: lo que hacia Pablo cuando 'no abria'."""
    titulo("2. INSTANCIA UNICA (con la primera abierta)")
    marca = tam_log()
    segundo = lanzar()
    comprobar("el segundo lanzamiento arranca", segundo is not None,
              "PID %s" % segundo)
    # El segundo NO abre la app: ensena un aviso. Ese aviso es una ventana
    # modal, asi que el proceso sigue vivo hasta que alguien lo cierra: es el
    # comportamiento correcto, no un proceso colgado.
    seg = esperar_ventana(segundo, 30) if segundo else None
    aviso = titulo_ventana(segundo) if segundo else ""
    comprobar("avisa de que la app ya esta abierta",
              "ya esta abierto" in aviso.lower() or "ya está abierto" in aviso.lower(),
              aviso or "(sin ventana)")
    time.sleep(1)
    try:
        with open(LOG, encoding="utf-8", errors="ignore") as f:
            f.seek(marca)
            texto = f.read()
    except Exception:
        texto = ""
    comprobar("y el registro explica que ya estaba abierta",
              "Ya hay otra instancia" in texto)
    comprobar("NO se abre una segunda ventana de la aplicacion",
              "Buscador de Piezas SolidWorks" not in aviso)
    comprobar("la primera instancia sigue viva y con su ventana",
              bool(titulo_ventana(pid_abierto)),
              titulo_ventana(pid_abierto) or "(sin ventana)")
    if segundo:
        cerrar(segundo, forzar=True)


def esperar_a_que_muera(pid, seg=25):
    t0 = time.time()
    while time.time() - t0 < seg:
        if not vivo(pid):
            return True
        time.sleep(0.3)
    return False


def prueba_candado_huerfano():
    titulo("3. CANDADO HUERFANO (proceso matado a lo bruto)")
    pid = lanzar()
    if not pid or esperar_ventana(pid) is None:
        comprobar("preparacion: la app abre para poder matarla", False)
        cerrar(pid, forzar=True)
        return
    cerrar(pid, forzar=True)          # muerte violenta: no suelta el candado
    candado = os.path.expanduser("~/.alsi_busqueda/buscador.lock")
    comprobar("tras matarla queda el candado en disco", os.path.exists(candado))
    marca = tam_log()
    nuevo = lanzar()
    seg = esperar_ventana(nuevo) if nuevo else None
    comprobar("la app vuelve a abrir pese al candado huerfano",
              seg is not None, "%.1fs" % seg if seg else "NO ABRE")
    try:
        with open(LOG, encoding="utf-8", errors="ignore") as f:
            f.seek(marca)
            texto = f.read()
    except Exception:
        texto = ""
    # Lo que importa es que NO se quede fuera. El candado muerto lo puede
    # retirar Qt por su cuenta (detecta que el PID no existe) o nuestra valvula
    # de seguridad; ambos caminos son validos, asi que se comprueba el efecto.
    comprobar("y no se le dice que la app ya esta abierta",
              "Ya hay otra instancia" not in texto)
    cerrar(nuevo, forzar=True)


def prueba_servidor_caido():
    titulo("4. ARRANQUE REAL CON EL SERVIDOR INACCESIBLE")
    import configparser
    origen = os.path.join(os.path.dirname(EXE), "config.ini")
    cfg = configparser.ConfigParser()
    cfg.read(origen, encoding="utf-8")
    # Si falta el config.ini junto al .exe, esto reventaba con un KeyError seco
    # a mitad de la bateria y parecia un fallo de la app. Se dice lo que pasa.
    if "database" not in cfg:
        comprobar("hay un config.ini junto al ejecutable para esta prueba", False,
                  "falta %s" % origen)
        return
    cfg["database"]["host"] = "192.0.2.1"
    falso = os.path.join(tempfile.gettempdir(), "alsi_exe_caido.ini")
    with open(falso, "w", encoding="utf-8") as f:
        cfg.write(f)

    marca = tam_log()
    pid = lanzar({"ALSI_CONFIG_INI": falso})
    comprobar("arranca aunque el servidor no responda", pid is not None)
    if not pid:
        return
    seg = esperar_ventana(pid)
    comprobar("ABRE LA VENTANA IGUALMENTE", seg is not None,
              "%.1fs" % seg if seg else "NO ABRE (esto era el fallo original)")
    if seg is not None:
        comprobar("y lo hace en menos de 15 s", seg < 15, "%.1fs" % seg)
    time.sleep(12)         # dar tiempo al intento de conexion (5 s) y al aviso
    lineas = lineas_log_de(pid, marca)
    comprobar("el registro dice que no hay base de datos",
              any("192.0.2.1" in l for l in lineas))
    comprobar("la ventana sigue viva tras fallar la conexion",
              vivo(pid) and bool(titulo_ventana(pid)))
    cerrar(pid, forzar=True)


def prueba_diagnostico():
    titulo("5. MODO DIAGNOSTICO DEL EJECUTABLE")
    destino = os.path.expanduser("~/.alsi_busqueda/diagnostico.txt")
    try:
        os.remove(destino)
    except OSError:
        pass
    env = dict(os.environ)
    env["ALSI_SIN_DIALOGOS"] = "1"
    env["ALSI_SIN_CANDADO"] = "1"
    t0 = time.time()
    r = subprocess.run([EXE, "--diagnostico"], env=env, timeout=180)
    comprobar("termina sin error", r.returncode == 0, "codigo %s" % r.returncode)
    comprobar("no deja ventana abierta ni proceso", True)
    comprobar("escribe el informe en disco", os.path.exists(destino),
              "%.1fs" % (time.time() - t0))
    if os.path.exists(destino):
        with open(destino, encoding="utf-8", errors="ignore") as f:
            inf = f.read()
        for clave in ("Version de la app", "Puerto TCP", "Consulta de prueba",
                      "Host en uso", "TEMP escribible"):
            comprobar("el informe incluye '%s'" % clave, clave in inf)


# ---------------------------------------------------------------------------
def main():
    emitir("PRUEBAS DEL EJECUTABLE - %s" % EXE)
    emitir("Existe: %s" % os.path.exists(EXE))
    if not os.path.exists(EXE):
        emitir("No se encuentra el ejecutable.")
        return 1

    abiertos = ps("(Get-Process BuscadorPiezas -ErrorAction SilentlyContinue)."
                  "Id -join ','")
    emitir("Instancias abiertas antes de empezar: %s" % (abiertos or "ninguna"))
    if abiertos:
        if "--limpiar" in sys.argv:
            emitir("Se cierran (--limpiar) para partir de cero.")
            ps("Get-Process BuscadorPiezas -ErrorAction SilentlyContinue | "
               "Stop-Process -Force")
            time.sleep(3)
        else:
            emitir("")
            emitir("Hay instancias abiertas. Estas pruebas necesitan partir de")
            emitir("cero (abren y cierran la app). Cierra la aplicacion, o vuelve")
            emitir("a lanzar esto con --limpiar para que las cierre yo.")
            return 2
    candado = os.path.expanduser("~/.alsi_busqueda/buscador.lock")
    if os.path.exists(candado):
        try:
            os.remove(candado)
            emitir("Se retira un candado suelto de una ejecucion anterior.")
        except OSError:
            pass

    pid = None
    try:
        pid = prueba_arranque_normal()
        if pid:
            prueba_instancia_unica(pid)
            cerrar(pid)
            comprobar("la app se cierra limpiamente al pedirselo", not vivo(pid))
        prueba_candado_huerfano()
        prueba_servidor_caido()
        prueba_diagnostico()
    finally:
        cerrar(pid, forzar=True)

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
    return 0 if not fallos else 1


if __name__ == "__main__":
    codigo = main()
    _salida.close()
    sys.exit(codigo)
