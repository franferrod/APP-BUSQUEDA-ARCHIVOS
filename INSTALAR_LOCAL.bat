@echo off
setlocal enabledelayedexpansion

set APP_NAME=BuscadorPiezas
set APP_EXE=BuscadorPiezas.exe
set TARGET_DIR=%LOCALAPPDATA%\ALSI_Buscador
set DESKTOP_PATH=%USERPROFILE%\Desktop

echo.
echo  ======================================================
echo     INSTALANDO BUSCADOR DE PIEZAS ALSI (V1.0.0)
echo  ======================================================
echo.

REM Soporte para rutas UNC (V1.0.1)
pushd "%~dp0"

REM Verificación de archivos fuente
if not exist "%~dp0%APP_EXE%" (
    echo [ERROR] No se encuentra %APP_EXE% en %~dp0
    echo Por favor, ejecuta este script desde la carpeta de red.
    popd
    pause
    exit /b
)

REM 1. Crear carpeta local si no existe
echo 1. Preparando directorio local...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

REM 2. Copiar ejecutable y recursos
echo 2. Copiando archivos a local...
copy /Y "%APP_EXE%" "%TARGET_DIR%\" >nul
if exist "ALSI_ISOTIPO_naranja.png" copy /Y "ALSI_ISOTIPO_naranja.png" "%TARGET_DIR%\" >nul
if exist "ALSI_IMAGOTIPO_naranja.png" copy /Y "ALSI_IMAGOTIPO_naranja.png" "%TARGET_DIR%\" >nul
if exist "ALSI_BUSCADOR.ico" copy /Y "ALSI_BUSCADOR.ico" "%TARGET_DIR%\" >nul

REM 3. Crear Acceso Directo mediante PowerShell
echo 3. Creando acceso directo en el Escritorio...
set SHORTCUT_NAME=Buscador Piezas ALSI
set PS_CMD="$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP_PATH%\%SHORTCUT_NAME%.lnk');$s.TargetPath='%TARGET_DIR%\%APP_EXE%';$s.WorkingDirectory='%TARGET_DIR%';$s.IconLocation='%TARGET_DIR%\ALSI_BUSCADOR.ico';$s.Description='Buscador de archivos ALSI';$s.Save()"
powershell -Command %PS_CMD%

echo.
echo  ======================================================
echo     INSTALACION COMPLETADA CON EXITO
echo  ======================================================
echo  Puedes cerrar esta ventana y usar el acceso directo.
echo.
popd
pause
