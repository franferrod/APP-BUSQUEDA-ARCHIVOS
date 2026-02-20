@echo off
setlocal enabledelayedexpansion

:: ======================================================
:: SCRIPT DE DESPLIEGUE DE VERSIONES ALSI
:: Uso: DESPLEGAR_VERSION.bat v1.0.X
:: ======================================================

set VERSION=%1
set RED_PATH="\\192.168.1.229\Volume_1\ALSI INTERCAMBIO\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS"

if "%VERSION%"=="" (
    echo [ERROR] Debes especificar una version. Ejemplo: DESPLEGAR_VERSION.bat v1.0.1
    echo Versiones disponibles:
    dir /B releases
    pause
    exit /b
)

if not exist "releases\%VERSION%" (
    echo [ERROR] La version %VERSION% no existe en la carpeta releases.
    pause
    exit /b
)

echo === Desplegando Version %VERSION% a la red ===
echo Origen: releases\%VERSION%
echo Destino: %RED_PATH%

xcopy /Y /S /I "releases\%VERSION%\*" %RED_PATH%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Version %VERSION% desplegada correctamente en la red.
) else (
    echo.
    echo [ERROR] Hubo un problema al copiar los archivos. Verifica la conexion con el servidor.
)

pause
