# -*- coding: utf-8 -*-
"""Cierre determinista de las baterias que abren la aplicacion (V2.3.2).

EL PROBLEMA
Las baterias arrancan la app de verdad con runpy y sustituyen
`QApplication.exec_`, asi que el bucle de eventos real nunca corre: ni salta
`aboutToQuit` ni pasa por `closeEvent`. Cuando el proceso termina, Python
destruye los objetos en el orden que le da la gana, y ahi quedan vivos hilos de
fondo (la cascada de propiedades y el refresco de Clientes/Proyectos), QSettings
y mapas de bits del shell de Windows. Qt destruyendo un QThread en marcha tumba
el proceso: la bateria imprime sus comprobaciones en verde y despues sale con
139 (segmentation fault) o 127, sin un solo mensaje de error.

Eso hacia el banco de pruebas inservible como semaforo: no se podia distinguir
"ha fallado algo" de "ha terminado bien y se ha caido al salir".

LA SOLUCION
Volcar el informe, parar los hilos y salir con `os._exit`, que termina el
proceso sin pasar por la destruccion de objetos ni por atexit. El codigo de
salida vuelve a significar exactamente lo que dicen las comprobaciones.

Es seguro porque los informes se escriben con flush en cada linea y aqui se
cierran antes de salir. No sustituye al cierre de la app real: esa si pasa por
closeEvent y aboutToQuit, y eso lo cubre `pruebas_ejecutable.py` sobre el .exe
empaquetado.
"""
import os
import sys


def salir(codigo, informe=None):
    """Termina el proceso con `codigo`, sin destruir Qt por el camino.

    OJO: aqui NO se toca Qt. Cuando `main()` ya ha devuelto, el bucle de
    eventos falso ha terminado y cualquier llamada a la ventana o a la
    aplicacion puede caer sobre un objeto medio destruido: el proceso se mataba
    solo con STATUS_STACK_BUFFER_OVERRUN (0xC0000409) DESPUES de imprimir todas
    las comprobaciones en verde. Los hilos se paran DENTRO de cada bateria,
    mientras Qt esta sano, con `win._detener_workers_de_fondo()`."""
    for f in (informe, sys.stdout, sys.stderr):
        try:
            f.flush()
        except Exception:
            pass
    try:
        if informe is not None:
            informe.close()
    except Exception:
        pass
    os._exit(int(codigo) if codigo is not None else 1)
