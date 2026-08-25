# -*- coding: utf-8 -*-
"""
V2.2.0 - Comprueba de dónde saca la app las credenciales de PostgreSQL.

Motivo: config.ini lleva la contraseña en claro y el repositorio es público.
Se ha añadido una vía por variables de entorno, y estas comprobaciones
garantizan las dos cosas a la vez: que la vía nueva funciona y que NINGÚN
equipo ya instalado (que solo tiene su config.ini) se queda sin arrancar.

No toca la base de datos: solo mira qué dict de conexión se compone.

    python pruebas_credenciales.py
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

VARS = ["ALSI_CONFIG_INI", "ALSI_PG_HOST", "ALSI_PG_PORT", "ALSI_PG_DBNAME",
        "ALSI_PG_USER", "ALSI_PG_PASSWORD", "ALSI_PG_CONNECT_TIMEOUT"]

_ok = 0
_fallos = []


def check(nombre, condicion, detalle=""):
    global _ok
    if condicion:
        _ok += 1
        print(f"  OK    {nombre}")
    else:
        _fallos.append(nombre)
        print(f"  FALLO {nombre}   {detalle}")


def limpiar_entorno():
    for v in VARS:
        os.environ.pop(v, None)


def cargar():
    """Reimporta models para que vuelva a resolver PG_CONFIG."""
    sys.modules.pop("models", None)
    import models
    return models.PG_CONFIG


def main():
    carpeta = tempfile.mkdtemp(prefix="alsi_cred_")
    completo = os.path.join(carpeta, "completo.ini")
    sin_pass = os.path.join(carpeta, "sin_password.ini")
    with io.open(completo, "w", encoding="utf-8") as f:
        f.write("[database]\nhost = h1\nport = 5433\ndbname = d1\n"
                "user = u1\npassword = SECRETO_ARCHIVO\n")
    with io.open(sin_pass, "w", encoding="utf-8") as f:
        f.write("[database]\nhost = h2\nport = 5555\ndbname = d2\nuser = u2\n")

    print("1) config.ini completo — lo que tienen hoy todos los equipos")
    limpiar_entorno()
    os.environ["ALSI_CONFIG_INI"] = completo
    c = cargar()
    check("host, puerto, base y usuario salen del archivo",
          (c['host'], c['port'], c['dbname'], c['user']) == ('h1', 5433, 'd1', 'u1'), c)
    check("la contraseña sale del archivo", c['password'] == 'SECRETO_ARCHIVO')
    check("connect_timeout por defecto es 5", c['connect_timeout'] == 5)
    check("los keepalives siguen puestos",
          c['keepalives'] == 1 and c['keepalives_idle'] == 30)

    print("2) solo variables de entorno — sin ningún archivo de por medio")
    limpiar_entorno()
    os.environ.update({"ALSI_PG_HOST": "envhost", "ALSI_PG_PORT": "6000",
                       "ALSI_PG_DBNAME": "envdb", "ALSI_PG_USER": "envuser",
                       "ALSI_PG_PASSWORD": "SECRETO_ENTORNO"})
    c = cargar()
    check("la conexión entera sale del entorno",
          (c['host'], c['port'], c['dbname'], c['user']) == ('envhost', 6000, 'envdb', 'envuser'), c)
    check("la contraseña sale del entorno", c['password'] == 'SECRETO_ENTORNO')
    check("el puerto llega convertido a entero", isinstance(c['port'], int))

    print("3) config.ini SIN contraseña + ALSI_PG_PASSWORD — el modo recomendado")
    limpiar_entorno()
    os.environ["ALSI_CONFIG_INI"] = sin_pass
    os.environ["ALSI_PG_PASSWORD"] = "SOLO_EN_ENTORNO"
    c = cargar()
    check("servidor y puerto salen del archivo",
          (c['host'], c['port']) == ('h2', 5555), c)
    check("la contraseña sale del entorno", c['password'] == 'SOLO_EN_ENTORNO')

    print("4) si están las dos, manda el entorno")
    limpiar_entorno()
    os.environ["ALSI_CONFIG_INI"] = completo
    os.environ["ALSI_PG_PASSWORD"] = "LA_QUE_MANDA"
    c = cargar()
    check("la contraseña del entorno pisa a la del archivo",
          c['password'] == 'LA_QUE_MANDA')
    check("el resto se sigue leyendo del archivo", c['host'] == 'h1')

    print("5) un config.ini sin contraseña y sin entorno no se usa")
    limpiar_entorno()
    os.environ["ALSI_CONFIG_INI"] = sin_pass
    try:
        c = cargar()
        # No revienta: descarta el incompleto y sigue con el siguiente
        # candidato (el config.ini real de la carpeta). Lo que NO puede
        # pasar es que dé por bueno el que no tiene contraseña.
        check("no da por bueno el archivo incompleto", c['host'] != 'h2', c)
        check("acaba con una conexión que sí tiene contraseña",
              bool(str(c.get('password', '')).strip()))
    except SystemExit as e:
        check("o termina limpiamente con código 2", e.code == 2, f"código {e.code}")

    print("6) connect_timeout configurable por entorno")
    limpiar_entorno()
    os.environ.update({"ALSI_PG_HOST": "h", "ALSI_PG_PORT": "1",
                       "ALSI_PG_DBNAME": "d", "ALSI_PG_USER": "u",
                       "ALSI_PG_PASSWORD": "p", "ALSI_PG_CONNECT_TIMEOUT": "12"})
    c = cargar()
    check("se respeta ALSI_PG_CONNECT_TIMEOUT", c['connect_timeout'] == 12, c)

    print("7) el repositorio no lleva credenciales")
    limpiar_entorno()
    ignorados = io.open(os.path.join(RAIZ, ".gitignore"), encoding="utf-8").read()
    check("config.ini está en .gitignore", "config.ini" in ignorados)
    check("config.ini no está en el árbol de git",
          os.system('git -C "%s" ls-files --error-unmatch config.ini '
                    '>nul 2>&1' % RAIZ) != 0)

    limpiar_entorno()
    total = _ok + len(_fallos)
    print(f"\n{_ok} de {total} comprobaciones")
    if _fallos:
        print("Han fallado:")
        for f in _fallos:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
