@echo off
title Guardar Punto de Restauración - Buscador ALSI
echo ========================================================
echo        CREANDO COPIA DE SEGURIDAD (SNAPSHOT)
echo ========================================================
echo.
python "%~dp0hacer_backup.py"
pause
