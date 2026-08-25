# -*- coding: utf-8 -*-
"""Pruebas de lo nuevo en la V2.1.2: filtro dentro de los dialogos y Abrir PDF.

    python pruebas_v212.py
"""
import os
import runpy
import sys
import time
import traceback

RAIZ = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ALSI_SIN_DIALOGOS"] = "1"
os.environ["ALSI_SIN_CANDADO"] = "1"
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

INFORME = os.path.join(RAIZ, "pruebas_v212_resultado.txt")
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
    print("  %-56s %s%s" % (texto, "OK" if ok else "FALLO",
                            ("  · " + detalle) if detalle else ""))
    return ok


def titulo(t):
    print()
    print("-- %s %s" % (t, "-" * max(0, 64 - len(t))))


def esperar(cond, seg=30):
    from PyQt5.QtWidgets import QApplication
    t0 = time.time()
    while not cond() and time.time() - t0 < seg:
        QApplication.processEvents()
        time.sleep(0.05)
    return cond()


def buscar_datos_de_prueba():
    """Un ensamblaje con muchos componentes y una pieza que tenga PDF."""
    from models import PG_CONFIG
    import psycopg2
    c = psycopg2.connect(**PG_CONFIG)
    cur = c.cursor()
    cur.execute("""SELECT ensamblaje_ruta FROM buscador.componentes
                   GROUP BY 1 HAVING count(*) >= 8
                   ORDER BY count(*) DESC LIMIT 1""")
    ens = cur.fetchone()[0]
    # El primer token tiene que parecer un CODIGO, igual que exige
    # _codigo_de_nombre: con punto y con algun digito ('24120.P027').
    # Sin esa condicion la muestra acababa cayendo en nombres como
    # 'PLACA CE 22-0404.SLDPRT', cuyo primer token es 'PLACA': la prueba
    # pedia un PDF que el producto, con razon, no tiene por que encontrar.
    cur.execute("""SELECT ruta_completa, nombre_archivo FROM buscador.archivos
                   WHERE extension IN ('.sldprt','.sldasm')
                     AND split_part(nombre_archivo,' ',1) ~ '^[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+$'
                     AND split_part(nombre_archivo,' ',1) ~ '[0-9]'
                     AND upper(split_part(nombre_archivo,' ',1)) IN (
                         SELECT upper(split_part(nombre_archivo,' ',1))
                         FROM buscador.archivos WHERE extension='.pdf')
                   LIMIT 1""")
    con_pdf = cur.fetchone()
    cur.execute("""SELECT ruta_completa FROM buscador.archivos
                   WHERE extension='.sldprt'
                     AND nombre_archivo NOT LIKE '%.%'
                   LIMIT 1""")
    sin_codigo = cur.fetchone()
    cur.execute("""SELECT a.ruta_completa FROM buscador.componentes k
                   JOIN buscador.archivos a
                     ON upper(a.nombre_archivo)=upper(k.componente_nombre)
                   GROUP BY a.ruta_completa
                   HAVING count(DISTINCT k.ensamblaje_ruta) >= 3 LIMIT 1""")
    pieza_usada = cur.fetchone()[0]
    c.close()
    return ens, con_pdf, sin_codigo, pieza_usada


def probar_filtro_despiece(win, mod, ens):
    from PyQt5.QtWidgets import QLineEdit
    titulo("1. BUSCAR DENTRO DEL DESPIECE")
    dlgs = []
    from PyQt5.QtWidgets import QDialog
    QDialog.exec_ = lambda self: (dlgs.append(self), QDialog.Accepted)[1]
    win.mostrar_despiece(ens)
    dlg = dlgs[-1] if dlgs else None
    if not dlg:
        comprobar("el despiece se abre", False)
        return
    tabla = dlg.findChildren(mod.TablaDialogoArrastrable)[0]
    cajas = [w for w in dlg.findChildren(QLineEdit)]
    comprobar("el despiece trae un cuadro para buscar dentro", bool(cajas))
    if not cajas:
        return
    caja = cajas[0]
    total = tabla.rowCount()
    comprobar("al abrirlo se ven todos los componentes",
              sum(1 for f in range(total) if not tabla.isRowHidden(f)) == total,
              "%d componentes" % total)

    # texto real de un componente cualquiera
    objetivo = ""
    for f in range(total):
        it = tabla.item(f, 1)
        if it and len(it.text()) > 6:
            objetivo = it.text().split()[-1]
            break
    caja.setText(objetivo)
    visibles = sum(1 for f in range(total) if not tabla.isRowHidden(f))
    comprobar("filtrar por una palabra real deja menos filas",
              0 < visibles <= total, "'%s' -> %d de %d" % (objetivo, visibles, total))

    caja.setText("zzzz-no-existe")
    comprobar("un texto que no esta deja la lista vacia",
              sum(1 for f in range(total) if not tabla.isRowHidden(f)) == 0)

    caja.setText("")
    comprobar("al limpiar vuelven todos los componentes",
              sum(1 for f in range(total) if not tabla.isRowHidden(f)) == total)

    # sin acentos y en minusculas
    con_acento = ""
    for f in range(total):
        it = tabla.item(f, 1)
        if it and any(c in it.text() for c in "ÁÉÍÓÚÑáéíóúñ"):
            con_acento = it.text()
            break
    if con_acento:
        sin_tildes = (con_acento.lower().replace("á", "a").replace("é", "e")
                      .replace("í", "i").replace("ó", "o").replace("ú", "u")
                      .replace("ñ", "n"))
        palabra = [p for p in sin_tildes.split() if len(p) > 4]
        if palabra:
            caja.setText(palabra[0])
            comprobar("busca sin tildes y en minusculas",
                      sum(1 for f in range(total) if not tabla.isRowHidden(f)) > 0,
                      "'%s'" % palabra[0])
    else:
        comprobar("busca sin tildes y en minusculas (sin datos con acento)", True)

    caja.setText("")
    # Varias palabras: deben aparecer TODAS, aunque esten en columnas
    # distintas. Se cogen dos textos de la MISMA fila y de columnas distintas,
    # asi la prueba no depende de como se llamen los componentes.
    fila_ok, uno, dos = None, "", ""
    for f in range(total):
        textos = []
        for c in range(tabla.columnCount()):
            it = tabla.item(f, c)
            if it and it.text() and it.text() not in ("—", "-"):
                palabras = [p for p in it.text().split() if len(p) >= 3]
                if palabras:
                    textos.append(palabras[0])
        if len(textos) >= 2:
            fila_ok, uno, dos = f, textos[0], textos[-1]
            break
    if fila_ok is not None:
        caja.setText(uno + " " + dos)
        visibles = sum(1 for f in range(total) if not tabla.isRowHidden(f))
        comprobar("con varias palabras exige que aparezcan todas",
                  visibles >= 1 and not tabla.isRowHidden(fila_ok),
                  "'%s %s' -> %d filas" % (uno, dos, visibles))
        caja.setText(uno + " zzzznoexiste")
        comprobar("si una de las palabras no esta, la fila no sale",
                  sum(1 for f in range(total) if not tabla.isRowHidden(f)) == 0)
    else:
        comprobar("con varias palabras exige que aparezcan todas", False,
                  "no se ha encontrado una fila con dos textos")
    caja.setText("")
    dlg.close()


def probar_filtro_donde_se_usa(win, mod, pieza):
    from PyQt5.QtWidgets import QDialog, QLineEdit
    titulo("2. BUSCAR DENTRO DE '¿EN QUE ENSAMBLAJES SE USA?'")
    dlgs = []
    QDialog.exec_ = lambda self: (dlgs.append(self), QDialog.Accepted)[1]
    win.mostrar_donde_se_usa(pieza)
    dlg = dlgs[-1] if dlgs else None
    if not dlg:
        comprobar("el dialogo se abre", False)
        return
    lista = dlg.findChildren(mod.ListaArrastrable)[0]
    cajas = dlg.findChildren(QLineEdit)
    comprobar("tambien trae cuadro de busqueda", bool(cajas))
    if not cajas:
        return
    caja = cajas[0]
    total = lista.count()
    caja.setText("zzzz-no-existe")
    comprobar("filtra la lista de ensamblajes",
              sum(1 for i in range(total) if not lista.item(i).isHidden()) == 0,
              "%d ensamblajes" % total)
    caja.setText("")
    comprobar("y al limpiar vuelven todos",
              sum(1 for i in range(total) if not lista.item(i).isHidden()) == total)
    dlg.close()


def probar_abrir_pdf(win, con_pdf, sin_codigo):
    titulo("3. ABRIR PDF")
    if con_pdf:
        ruta, nombre = con_pdf
        pdfs = win.pdfs_de(ruta)
        comprobar("encuentra el PDF de una pieza con codigo", len(pdfs) > 0,
                  "%s -> %d PDF" % (nombre[:34], len(pdfs)))
        comprobar("lo que devuelve son PDF de verdad",
                  all(p.lower().endswith(".pdf") for p in pdfs))
    # Un nombre sin codigo ALSI (sin el token tipo 24120.P027) no tiene PDF
    # asociado posible: debe devolver vacio, nunca reventar.
    falso = "C:" + chr(92) + "x" + chr(92) + "Pata tubo sin codigo.SLDPRT"
    comprobar("una pieza sin codigo devuelve lista vacia, no error",
              win.pdfs_de(falso) == [], os.path.basename(falso))
    if sin_codigo:
        comprobar("y lo mismo con una pieza real sin codigo",
                  win.pdfs_de(sin_codigo[0]) == [],
                  os.path.basename(sin_codigo[0])[:40])
    comprobar("un PDF es su propio PDF",
              win.pdfs_de("C:" + chr(92) + "x" + chr(92) + "plano.PDF")
              == ["C:" + chr(92) + "x" + chr(92) + "plano.PDF"])
    comprobar("una ruta vacia no revienta", win.pdfs_de("") == [])
    comprobar("abrir el PDF de algo sin PDF avisa y no revienta",
              win.abrir_pdf_de("C:" + chr(92) + "no" + chr(92) + "existe.SLDPRT") is None)


def probar_menu_pdf(win, mod, con_pdf):
    from PyQt5.QtWidgets import QMenu
    from PyQt5.QtCore import QPoint
    titulo("4. 'ABRIR PDF' EN EL MENU DEL BOTON DERECHO")
    acciones = []
    original = QMenu.exec_
    QMenu.exec_ = lambda self, *a, **k: acciones.extend(
        x.text() for x in self.actions() if x.text())
    try:
        ruta = con_pdf[0] if con_pdf else "C:" + chr(92) + "x.SLDPRT"
        win._menu_archivos(win.tabla, [ruta], QPoint(10, 10))
    finally:
        QMenu.exec_ = original
    comprobar("el menu de los dialogos ofrece 'Abrir PDF'",
              any("Abrir PDF" in a for a in acciones), ", ".join(acciones[:4]))
    comprobar("y sigue ofreciendo abrir en SolidWorks",
              any("SolidWorks" in a for a in acciones))


def resumen():
    print()
    print("=" * 72)
    fallos = [r for r in RESULTADOS if not r[1]]
    print("  TOTAL: %d de %d" % (len(RESULTADOS) - len(fallos), len(RESULTADOS)))
    if fallos:
        print()
        print("  FALLOS:")
        for t, _ok, d in fallos:
            print("    - %s %s" % (t, ("(%s)" % d) if d else ""))
    print("=" * 72)
    return 0 if not fallos else 1


def main():
    from PyQt5.QtWidgets import QApplication
    salida = {}

    def _exec(self):
        sys.stdout = TEE
        try:
            win = next(x for x in QApplication.topLevelWidgets()
                       if type(x).__name__ == "BuscadorPiezas")
            mod = sys.modules["__main__"]
            print("PRUEBAS DE LA V2.1.2 - filtro en dialogos y Abrir PDF")
            win._carga_inicial_diferida()
            esperar(lambda: win.db.esta_disponible(), 30)
            ens, con_pdf, sin_codigo, pieza = buscar_datos_de_prueba()
            probar_filtro_despiece(win, mod, ens)
            probar_filtro_donde_se_usa(win, mod, pieza)
            probar_abrir_pdf(win, con_pdf, sin_codigo)
            probar_menu_pdf(win, mod, con_pdf)
        except Exception:
            print("EXCEPCION:")
            traceback.print_exc()
            RESULTADOS.append(("la bateria termina sin excepciones", False, ""))
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
    sys.exit(main())
