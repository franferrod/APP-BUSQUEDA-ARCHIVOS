@echo off
REM Tarea de reindexación automática diaria - ALSI Buscador de Piezas
REM Se ejecuta via Programador de Tareas de Windows a las 15:45h

cd /d "c:\Users\OFITEC 4\Desktop\ANTIGRAVITY\BÚSQUEDA PIEZAS"
"C:\Users\OFITEC 4\AppData\Local\Programs\Python\Python311\python.exe" reindexar_diario.py
