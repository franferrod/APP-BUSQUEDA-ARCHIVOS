@echo off
setlocal enabledelayedexpansion

set APP_NAME=BuscadorPiezas
set APP_EXE=BuscadorPiezas.exe
set TARGET_DIR=%LOCALAPPDATA%\ALSI_Buscador
set DESKTOP_PATH=%USERPROFILE%\Desktop

set APP_VERSION=2.1.0

echo.
echo  ======================================================
echo     INSTALANDO BUSCADOR DE PIEZAS ALSI (%APP_VERSION%)
echo  ======================================================
echo.

REM Soporte para rutas UNC
pushd "%~dp0"

REM Verificación de archivos fuente
if not exist "%~dp0%APP_EXE%" (
    echo [ERROR] No se encuentra %APP_EXE% en %~dp0
    echo Por favor, ejecuta este script desde la carpeta de red.
    popd
    pause
    exit /b
)

REM 1. Eliminar base de datos SQLite antigua (V1.0.7)
echo 1. Eliminando rastros de base de datos local antigua...
if exist "%TARGET_DIR%\index.db" del /F /Q "%TARGET_DIR%\index.db"
if exist "%TARGET_DIR%\index.db-wal" del /F /Q "%TARGET_DIR%\index.db-wal"
if exist "%TARGET_DIR%\index.db-shm" del /F /Q "%TARGET_DIR%\index.db-shm"

REM 2. Crear carpeta local si no existe
echo 2. Preparando directorio local...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

REM 3. Copiar ejecutable y recursos
echo 3. Copiando archivos a local...
copy /Y "%APP_EXE%" "%TARGET_DIR%\" >nul
copy /Y "SwPropExtractor.exe" "%TARGET_DIR%\" >nul
copy /Y "SolidWorks.Interop.swdocumentmgr.dll" "%TARGET_DIR%\" >nul
if exist "ALSI_ISOTIPO_naranja.png" copy /Y "ALSI_ISOTIPO_naranja.png" "%TARGET_DIR%\" >nul
if exist "ALSI_IMAGOTIPO_naranja.png" copy /Y "ALSI_IMAGOTIPO_naranja.png" "%TARGET_DIR%\" >nul
if exist "ALSI_BUSCADOR.ico" copy /Y "ALSI_BUSCADOR.ico" "%TARGET_DIR%\" >nul
if exist "config.ini" copy /Y "config.ini" "%TARGET_DIR%\" >nul

REM Copiar scripts de reindexación
copy /Y "reindexar_diario.py" "%TARGET_DIR%\" >nul
copy /Y "reindexar_tarea.bat" "%TARGET_DIR%\" >nul

REM 4. Crear Acceso Directo mediante PowerShell
echo 4. Creando acceso directo en el Escritorio...
set SHORTCUT_NAME=Buscador Piezas ALSI
set PS_CMD="$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP_PATH%\%SHORTCUT_NAME%.lnk');$s.TargetPath='%TARGET_DIR%\%APP_EXE%';$s.WorkingDirectory='%TARGET_DIR%';$s.IconLocation='%TARGET_DIR%\ALSI_BUSCADOR.ico';$s.Description='Buscador de archivos ALSI';$s.Save()"
powershell -Command %PS_CMD%

echo.
echo  ======================================================
echo     INSTALACION COMPLETADA CON EXITO
echo  ======================================================
echo  La aplicacion ahora se conecta directamente al NAS.
echo  Puedes cerrar esta ventana y usar el acceso directo en tu Escritorio.
echo.
popd
pause
