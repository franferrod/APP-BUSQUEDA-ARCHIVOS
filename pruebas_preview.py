# -*- coding: utf-8 -*-
"""Pruebas del panel de vista previa (V2.1.3).

Fallo que arreglan: en la galeria se veia la miniatura del ensamblaje pero al
seleccionarlo el panel derecho mostraba el icono generico de SolidWorks (el
cubo amarillo y azul). Causa: el shell de Windows devuelve ese icono cuando no
sabe renderizar el archivo, y se aplicaba sin comprobar nada, machacando la
miniatura buena que ya estaba puesta.

    python pruebas_preview.py
"""
import os
import runpy
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ALSI_SIN_DIALOGOS"] = "1"
os.environ["ALSI_SIN_CANDADO"] = "1"
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

INFORME = os.path.join(RAIZ, "pruebas_preview_resultado.txt")
RESULTADOS = []
_f = open(INFORME, "w", encoding="utf-8")


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
    emitir("  %-56s %s%s" % (texto, "OK" if ok else "FALLO",
                             ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    emitir("")
    emitir("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


def main():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor
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

            from models import PG_CONFIG
            import psycopg2
            c = psycopg2.connect(**PG_CONFIG)
            cur = c.cursor()
            # Archivos donde ya se comprobo que el shell devuelve el icono
            # generico (la misma imagen para los dos), y otros de control.
            cur.execute("""SELECT a.ruta_completa, a.nombre_archivo
                           FROM buscador.archivos a
                           JOIN buscador.miniaturas m
                             ON m.ruta_completa = a.ruta_completa
                           WHERE a.extension = '.sldasm'
                             AND (a.nombre_archivo ILIKE '26067.E023%'
                                  OR a.nombre_archivo ILIKE '26067.E144%'
                                  OR a.nombre_archivo ILIKE '26067.E222%')
                           ORDER BY a.nombre_archivo""")
            filas = cur.fetchall()
            if len(filas) < 2:
                cur.execute("""SELECT a.ruta_completa, a.nombre_archivo
                               FROM buscador.archivos a
                               JOIN buscador.miniaturas m
                                 ON m.ruta_completa = a.ruta_completa
                               WHERE a.extension = '.sldasm' LIMIT 3""")
                filas = cur.fetchall()
            c.close()
            if not filas:
                comprobar("hay ensamblajes con miniatura para probar", False)
                return 0
            ruta, nombre = filas[0]

            def imagen_del_shell(r):
                """Lo que el shell de Windows devuelve para ese archivo."""
                try:
                    image, hbitmap = win.extraer_miniatura_raw(r, size=1024)
                    if hbitmap:
                        from PyQt5.QtWinExtras import QtWin
                        pm = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapPremultipliedAlpha)
                        if pm.isNull():
                            pm = QtWin.fromHBITMAP(hbitmap, QtWin.HBitmapNoAlpha)
                        import ctypes
                        from ctypes import c_void_p
                        ctypes.windll.gdi32.DeleteObject.argtypes = [c_void_p]
                        ctypes.windll.gdi32.DeleteObject(hbitmap)
                        return pm
                    if image is not None and not image.isNull():
                        return QPixmap.fromImage(image)
                except Exception:
                    pass
                return None

            titulo("1. LA MEDIDA DE PARECIDO SEPARA LOS DOS CASOS")
            datos = win.db.obtener_miniatura(ruta)
            pm_bd = QPixmap.fromImage(QImage.fromData(datos))
            comprobar("hay miniatura de archivo para usar de referencia",
                      not pm_bd.isNull(), "%dx%d" % (pm_bd.width(), pm_bd.height()))

            # misma imagen a otra resolucion = lo que hace el shell cuando SI
            # renderiza: debe parecerse mucho
            pm_grande = pm_bd.scaled(1024, 1024, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
            p_bueno = win._parecido_imagenes(pm_bd, pm_grande)
            comprobar("un render de verdad se reconoce como parecido",
                      p_bueno >= win.UMBRAL_PREVIEW_PARECIDO, "%.1f%%" % (p_bueno * 100))

            # El icono generico DE VERDAD, tal y como lo devuelve el shell en
            # este equipo (no uno dibujado a mano: eso no representa el caso).
            generico = None
            for r, n in filas:
                pm_sh = imagen_del_shell(r)
                if pm_sh is None:
                    continue
                pm_ref = QPixmap.fromImage(
                    QImage.fromData(win.db.obtener_miniatura(r) or b""))
                if pm_ref.isNull():
                    continue
                if win._parecido_imagenes(pm_ref, pm_sh) < 0.85:
                    generico = pm_sh
                    ruta, nombre = r, n
                    pm_bd = pm_ref
                    break
            if generico is None:
                comprobar("se ha podido capturar el icono generico real", False,
                          "el shell renderiza bien todos los de la muestra")
                emitir("      (sin el caso real no se puede probar el descarte)")
            else:
                p_malo = win._parecido_imagenes(pm_bd, generico)
                comprobar("el icono generico REAL se reconoce como distinto",
                          p_malo < win.UMBRAL_PREVIEW_PARECIDO,
                          "%.1f%% en %s" % (p_malo * 100, nombre[:30]))
                comprobar("los dos casos quedan lejos del umbral por ambos lados",
                          (p_bueno - win.UMBRAL_PREVIEW_PARECIDO) > 0.05
                          and (win.UMBRAL_PREVIEW_PARECIDO - p_malo) > 0.05,
                          "bueno %.0f%% / umbral %.0f%% / malo %.0f%%"
                          % (p_bueno * 100, win.UMBRAL_PREVIEW_PARECIDO * 100,
                             p_malo * 100))

            # el archivo de referencia puede haber cambiado arriba: el render
            # "bueno" tiene que salir del mismo archivo que se va a probar
            pm_grande = pm_bd.scaled(1024, 1024, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)

            titulo("2. EL ICONO GENERICO NO TAPA LA MINIATURA BUENA")
            if generico is None:
                emitir("  (se omite: no se ha capturado el icono generico)")
            else:
                win.cache_miniaturas.clear()
                win._preview_referencia = (ruta, pm_bd)
                win._gen_preview = getattr(win, "_gen_preview", 0) + 1
                win._set_preview_imagen(pm_bd)
                win._on_preview_pesado(win._gen_preview, ruta, "1 MB",
                                       generico.toImage(), 0)
                despues = win.lbl_preview_icon._pm
                comprobar("tras llegar el icono generico, el panel NO cambia",
                          despues is not None
                          and win._parecido_imagenes(despues, pm_bd) > 0.99)
                comprobar("y el generico no se guarda en la cache",
                          win.cache_miniaturas.get((ruta, 1024)) is None)

            titulo("2b. LA MISMA IMAGEN PARA DOS ARCHIVOS = ICONO GENERICO")
            win.cache_miniaturas.clear()
            win._huellas_shell = {}
            win._huellas_genericas = set()
            falso = QPixmap(512, 512)
            falso.fill(QColor("#DDDDDD"))
            r1, r2 = filas[0][0], filas[min(1, len(filas) - 1)][0]
            win._preview_referencia = (r1, None)      # sin referencia: pasa el 1er filtro
            win._gen_preview += 1
            win._on_preview_pesado(win._gen_preview, r1, "1 MB", falso.toImage(), 0)
            primero_aceptado = win.cache_miniaturas.get((r1, 1024)) is not None
            win._preview_referencia = (r2, None)
            win._gen_preview += 1
            win._on_preview_pesado(win._gen_preview, r2, "1 MB", falso.toImage(), 0)
            segundo_rechazado = win.cache_miniaturas.get((r2, 1024)) is None
            comprobar("la primera vez se acepta (aun no hay con que comparar)",
                      primero_aceptado)
            comprobar("al repetirse en OTRO archivo se descarta por generico",
                      segundo_rechazado if r1 != r2 else True,
                      "" if r1 != r2 else "(un solo archivo, no aplica)")

            titulo("3. UN RENDER DE VERDAD SI SE APLICA (mas resolucion)")
            win.cache_miniaturas.clear()
            win._huellas_shell = {}
            win._huellas_genericas = set()
            win._preview_referencia = (ruta, pm_bd)
            win._gen_preview += 1
            win._on_preview_pesado(win._gen_preview, ruta, "1 MB",
                                   pm_grande.toImage(), 0)
            aplicado = win.lbl_preview_icon._pm
            comprobar("el render bueno si reemplaza a la miniatura",
                      aplicado is not None and aplicado.width() > pm_bd.width(),
                      "%dx%d -> %dx%d" % (pm_bd.width(), pm_bd.height(),
                                          aplicado.width(), aplicado.height()))

            titulo("4. SIN MINIATURA DE REFERENCIA SE ACEPTA LO QUE HAYA")
            win.cache_miniaturas.clear()
            win._huellas_shell = {}
            win._huellas_genericas = set()
            win._preview_referencia = ("otra_ruta_distinta", None)
            win._gen_preview += 1
            cualquiera = generico if generico is not None else pm_grande
            win._on_preview_pesado(win._gen_preview, ruta, "1 MB",
                                   cualquiera.toImage(), 0)
            comprobar("si no hay con que comparar, no se descarta nada",
                      win.cache_miniaturas.get((ruta, 1024)) is not None)

            titulo("5. LA GALERIA Y EL PANEL USAN LA MISMA IMAGEN")
            iguales = 0
            for r, n in filas:
                d = win.db.obtener_miniatura(r)
                if not d:
                    continue
                pm = QPixmap.fromImage(QImage.fromData(d))
                lote = win.db.obtener_miniaturas_lote([r])
                if lote.get(r):
                    pm_gal = QPixmap.fromImage(QImage.fromData(lote[r]))
                    if win._parecido_imagenes(pm, pm_gal) > 0.999:
                        iguales += 1
            comprobar("panel y galeria leen la misma miniatura de la BD",
                      iguales == len([1 for r, _n in filas
                                      if win.db.obtener_miniatura(r)]),
                      "%d archivos" % iguales)
        except Exception:
            import traceback
            emitir("EXCEPCION:")
            emitir(traceback.format_exc())
            RESULTADOS.append(("la bateria termina sin excepciones", False, ""))

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
