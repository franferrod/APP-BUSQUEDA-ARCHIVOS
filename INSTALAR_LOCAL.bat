@echo off
setlocal enabledelayedexpansion

set APP_NAME=BuscadorPiezas
set APP_EXE=BuscadorPiezas.exe
set TARGET_DIR=%LOCALAPPDATA%\ALSI_Buscador
set DESKTOP_PATH=%USERPROFILE%\Desktop

set APP_VERSION=2.3.1

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

REM 1. Cerrar la app si esta abierta (evita el error "archivo en uso" al copiar,
REM    que dejaba el exe SIN actualizar aunque el instalador dijera "EXITO")
echo 1. Cerrando la aplicacion si estaba abierta...
taskkill /F /IM "%APP_EXE%" >nul 2>&1
taskkill /F /IM SwPropExtractor.exe >nul 2>&1
REM Esperar unos segundos a que Windows libere los archivos
ping -n 4 127.0.0.1 >nul

REM 2. Eliminar base de datos SQLite antigua (V1.0.7)
echo 2. Eliminando rastros de base de datos local antigua...
if exist "%TARGET_DIR%\index.db" del /F /Q "%TARGET_DIR%\index.db"
if exist "%TARGET_DIR%\index.db-wal" del /F /Q "%TARGET_DIR%\index.db-wal"
if exist "%TARGET_DIR%\index.db-shm" del /F /Q "%TARGET_DIR%\index.db-shm"

REM 3. Crear carpeta local si no existe
echo 3. Preparando directorio local...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

REM 4. Copiar ejecutable y recursos (con verificacion real del exe principal)
echo 4. Copiando archivos a local...
copy /Y "%APP_EXE%" "%TARGET_DIR%\" >nul
if errorlevel 1 (
    echo.
    echo  [ERROR] No se pudo copiar %APP_EXE% ^(archivo en uso^).
    echo  Cierra por completo el Buscador de Piezas y vuelve a ejecutar este instalador.
    echo.
    popd
    pause
    exit /b 1
)
copy /Y "SwPropExtractor.exe" "%TARGET_DIR%\" >nul
copy /Y "SolidWorks.Interop.swdocumentmgr.dll" "%TARGET_DIR%\" >nul
if exist "ALSI_ISOTIPO_naranja.png" copy /Y "ALSI_ISOTIPO_naranja.png" "%TARGET_DIR%\" >nul
if exist "ALSI_IMAGOTIPO_naranja.png" copy /Y "ALSI_IMAGOTIPO_naranja.png" "%TARGET_DIR%\" >nul
if exist "ALSI_BUSCADOR.ico" copy /Y "ALSI_BUSCADOR.ico" "%TARGET_DIR%\" >nul
if exist "config.ini" copy /Y "config.ini" "%TARGET_DIR%\" >nul

REM Copiar scripts de reindexación
copy /Y "reindexar_diario.py" "%TARGET_DIR%\" >nul
copy /Y "reindexar_tarea.bat" "%TARGET_DIR%\" >nul

REM 5. Crear Acceso Directo mediante PowerShell
echo 5. Creando acceso directo en el Escritorio...
set SHORTCUT_NAME=Buscador Piezas ALSI
set PS_CMD="$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP_PATH%\%SHORTCUT_NAME%.lnk');$s.TargetPath='%TARGET_DIR%\%APP_EXE%';$s.WorkingDirectory='%TARGET_DIR%';$s.IconLocation='%TARGET_DIR%\ALSI_BUSCADOR.ico';$s.Description='Buscador de archivos ALSI';$s.Save()"
powershell -Command %PS_CMD%

echo.
echo  ======================================================
echo     INSTALACION COMPLETADA CON EXITO
echo  ======================================================
echo  Version instalada: %APP_VERSION%
echo  La aplicacion se abrira ahora. La primera apertura puede tardar
echo  unos segundos ^(el antivirus revisa el ejecutable nuevo^).
echo.

REM 6. Abrir la aplicacion ya actualizada
start "" "%TARGET_DIR%\%APP_EXE%"

popd
timeout /t 6 >nul
