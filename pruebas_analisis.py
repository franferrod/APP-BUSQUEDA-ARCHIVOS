# -*- coding: utf-8 -*-
"""Pruebas del analisis "Conjuntos con mas piezas sin vista previa" (V2.2.0).

Que resuelve: la investigacion de las vistas previas perdidas dejo claro que
reparar desde el indexado es imposible (Document Manager solo tiene metodos
Get* para la vista previa). Lo unico que las regenera es abrir el conjunto en
SolidWorks, reconstruir y volver a guardar. Asi que la app senala QUE conjuntos
arreglan mas piezas de una sola pasada.

Se comprueba contra el servidor de verdad, no contra datos inventados.

    python pruebas_analisis.py
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

INFORME = os.path.join(RAIZ, "pruebas_analisis_resultado.txt")
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
    from PyQt5.QtWidgets import QApplication, QDialog
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

            emitir("=" * 70)
            emitir("  ANALISIS: conjuntos con piezas sin vista previa")
            emitir("=" * 70)

            # ── 1. La consulta ────────────────────────────────────────────
            titulo("1. La consulta responde y en un tiempo razonable")
            t0 = time.time()
            filas = win.db.ensamblajes_sin_vista_previa(50)
            tardanza = time.time() - t0
            comprobar("devuelve resultados", len(filas) > 0, "%d filas" % len(filas))
            comprobar("tarda menos de 30 s", tardanza < 30, "%.1f s" % tardanza)
            comprobar("respeta el limite pedido", len(filas) <= 50)
            if not filas:
                salida["codigo"] = 1
                return 0

            # ── 2. Coherencia de cada fila ────────────────────────────────
            titulo("2. Cada fila es coherente")
            comprobar("cada fila trae los 7 campos",
                      all(len(f) == 7 for f in filas))
            comprobar("sin_vista siempre es mayor que cero",
                      all(f[4] > 0 for f in filas))
            comprobar("sin_vista nunca supera al total",
                      all(f[4] <= f[5] for f in filas),
                      str([(f[0][:20], f[4], f[5]) for f in filas if f[4] > f[5]][:2]))
            comprobar("viene ordenado de mas a menos",
                      all(filas[i][4] >= filas[i + 1][4] for i in range(len(filas) - 1)))
            comprobar("toda ruta es una ruta del NAS",
                      all(str(f[6]).startswith("\\\\") for f in filas))

            import psycopg2
            from models import PG_CONFIG
            cn = psycopg2.connect(**PG_CONFIG)
            cur = cn.cursor()

            # ── 3. El conteo cuadra con SQL a pelo ────────────────────────
            titulo("3. El conteo cuadra recalculandolo aparte")
            nombre, _cli, _pro, _anio, sin_vista, total, ruta = filas[0]
            cur.execute("""SELECT COUNT(DISTINCT componente_nombre)
                           FROM buscador.componentes WHERE ensamblaje_ruta = %s""",
                        (ruta,))
            total_real = cur.fetchone()[0]
            comprobar("el total de componentes coincide", total == total_real,
                      "informe %d · sql %d" % (total, total_real))

            cur.execute("""SELECT COUNT(*) FROM (
                             SELECT DISTINCT UPPER(c.componente_nombre) AS nom
                             FROM buscador.componentes c
                             WHERE c.ensamblaje_ruta = %s) x
                           WHERE NOT EXISTS (
                             SELECT 1 FROM buscador.archivos a
                             JOIN buscador.miniaturas m
                               ON m.ruta_completa = a.ruta_completa
                             WHERE UPPER(a.nombre_archivo) = x.nom
                               AND LOWER(a.extension) IN ('.sldprt','.sldasm'))""",
                        (ruta,))
            sin_real = cur.fetchone()[0]
            comprobar("las piezas sin vista coinciden", sin_vista == sin_real,
                      "informe %d · sql %d" % (sin_vista, sin_real))

            # ── 4. La semantica es la conservadora ────────────────────────
            titulo("4. Solo cuenta lo que esta roto seguro")
            # Las piezas que el informe da por rotas, una a una: ninguna puede
            # tener copia con miniatura. Si alguna la tuviera, el informe
            # mandaria a un compañero a reabrir un conjunto por nada.
            cur.execute("""SELECT DISTINCT UPPER(c.componente_nombre) AS nom
                           FROM buscador.componentes c
                           WHERE c.ensamblaje_ruta = %s
                             AND NOT EXISTS (
                                 SELECT 1 FROM buscador.archivos a
                                 JOIN buscador.miniaturas m
                                   ON m.ruta_completa = a.ruta_completa
                                 WHERE UPPER(a.nombre_archivo) = UPPER(c.componente_nombre)
                                   AND LOWER(a.extension) IN ('.sldprt','.sldasm'))
                           LIMIT 300""", (ruta,))
            rotas = [r[0] for r in cur.fetchall()]
            comprobar("se pueden listar las piezas dadas por rotas", len(rotas) > 0,
                      "%d nombres" % len(rotas))
            falsos = []
            for nom in rotas:
                cur.execute("""SELECT COUNT(*) FROM buscador.archivos a
                               JOIN buscador.miniaturas m
                                 ON m.ruta_completa = a.ruta_completa
                               WHERE UPPER(a.nombre_archivo) = %s
                                 AND LOWER(a.extension) IN ('.sldprt','.sldasm')""",
                            (nom,))
                if cur.fetchone()[0] > 0:
                    falsos.append(nom)
            comprobar("ninguna pieza con copia buena se cuenta como rota",
                      not falsos, "%d falsos: %s" % (len(falsos), falsos[:2]))

            # Y al reves: una pieza con miniatura NO puede estar en la lista.
            cur.execute("""SELECT UPPER(a.nombre_archivo)
                           FROM buscador.archivos a
                           JOIN buscador.miniaturas m ON m.ruta_completa = a.ruta_completa
                           JOIN buscador.componentes c
                             ON UPPER(c.componente_nombre) = UPPER(a.nombre_archivo)
                           WHERE c.ensamblaje_ruta = %s
                             AND LOWER(a.extension) IN ('.sldprt','.sldasm')
                           LIMIT 50""", (ruta,))
            sanas = {r[0] for r in cur.fetchall()}
            comprobar("las piezas sanas quedan fuera de la lista de rotas",
                      not (sanas & set(rotas)), str(list(sanas & set(rotas))[:2]))

            cur.execute("""SELECT COUNT(*) FROM buscador.archivos
                           WHERE ruta_completa = %s""", (ruta,))
            comprobar("el conjunto senalado existe en el indice",
                      cur.fetchone()[0] == 1)

            # ── 5. El filtro por ano ──────────────────────────────────────
            titulo("5. El filtro por ano")
            # Guarda de regresion: con el filtro escrito como
            # "(%s IS NULL OR anio >= %s)" el planificador no usaba el indice y
            # esto pasaba de 7 s a mas de DOS MINUTOS. Si alguien vuelve a
            # meter el OR, esta comprobacion lo caza.
            t0 = time.time()
            recientes = win.db.ensamblajes_sin_vista_previa(20, desde_anio=2024)
            tardanza_filtro = time.time() - t0
            comprobar("filtrar por ano no dispara el tiempo",
                      tardanza_filtro < 30, "%.1f s" % tardanza_filtro)
            comprobar("filtrar no es mas lento que no filtrar",
                      tardanza_filtro <= tardanza * 2 + 5,
                      "filtrado %.1f s vs completo %.1f s" % (tardanza_filtro, tardanza))
            comprobar("con desde_anio solo salen de ese ano en adelante",
                      all((f[3] or 0) >= 2024 for f in recientes),
                      str(sorted({f[3] for f in recientes})[:5]))
            comprobar("sin desde_anio salen tambien anteriores",
                      any((f[3] or 9999) < 2024 for f in filas))

            # ── 6. Estabilidad ────────────────────────────────────────────
            titulo("6. Dos ejecuciones dan lo mismo")
            otra = win.db.ensamblajes_sin_vista_previa(50)
            comprobar("el resultado es determinista",
                      [f[6] for f in otra] == [f[6] for f in filas])

            # ── 7. La interfaz ────────────────────────────────────────────
            titulo("7. La interfaz lo ofrece y lo pinta")
            acciones = [a.text() for a in win.menu_analisis.actions()]
            comprobar("la accion esta en el menu Analisis",
                      any("sin vista previa" in a for a in acciones), str(acciones))
            comprobar("sigue estando la de piezas reutilizadas",
                      any("reutilizadas" in a for a in acciones))

            capturado = {}
            original = QDialog.exec_

            def sin_bloquear(self):
                capturado["dlg"] = self
                return 0

            QDialog.exec_ = sin_bloquear
            try:
                win.mostrar_sin_vista_previa()
            finally:
                QDialog.exec_ = original

            dlg = capturado.get("dlg")
            comprobar("se abre el dialogo", dlg is not None)
            if dlg is not None:
                comprobar("el titulo es el correcto",
                          "sin vista previa" in dlg.windowTitle(), dlg.windowTitle())
                from PyQt5.QtWidgets import QTableWidget
                tablas = dlg.findChildren(QTableWidget)
                comprobar("lleva una tabla", len(tablas) >= 1)
                if tablas:
                    t = tablas[0]
                    cabeceras = [t.horizontalHeaderItem(i).text()
                                 for i in range(t.columnCount())]
                    comprobar("la primera columna es la miniatura",
                              cabeceras[0] == "Vista", str(cabeceras))
                    comprobar("estan las columnas prometidas",
                              all(c in cabeceras for c in
                                  ("Conjunto", "Piezas sin vista", "Año",
                                   "Cliente", "Proyecto")), str(cabeceras))
                    comprobar("hay tantas filas como resultados",
                              t.rowCount() == len(filas),
                              "%d vs %d" % (t.rowCount(), len(filas)))
                    comprobar("la columna de conteo se lee '<n> de <total>'",
                              " de " in t.item(0, 2).text(), t.item(0, 2).text())
                    # La ruta viaja en el UserRole de la columna 0 ("Vista"),
                    # que es de donde la leen el doble clic y el menu del boton
                    # derecho en todos los dialogos.
                    from PyQt5.QtCore import Qt as _Qt
                    rutas_celda = [t.item(r, 0).data(_Qt.UserRole)
                                   for r in range(min(5, t.rowCount()))]
                    comprobar("cada fila guarda su ruta para poder abrirla",
                              all(str(x or "").startswith("\\\\") for x in rutas_celda),
                              str(rutas_celda[:1]))
                    comprobar("la ruta guardada es la del conjunto listado",
                              t.item(0, 0).data(_Qt.UserRole) == filas[0][6])
            comprobar("la barra de estado informa del resultado",
                      "conjuntos" in win.lbl_status.text().lower(),
                      win.lbl_status.text())

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
