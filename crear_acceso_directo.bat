@echo off
set SCRIPT_NAME="Buscador de Piezas ALSI"
set TARGET_PATH="%~dp0dist\Buscador de Piezas ALSI.exe"
set WORKING_DIR="%~dp0dist"
set SHORTCUT_PATH="%USERPROFILE%\Desktop\%SCRIPT_NAME%.lnk"

echo Creando acceso directo en el escritorio...

powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT_PATH%');$s.TargetPath='%TARGET_PATH%';$s.WorkingDirectory='%WORKING_DIR%';$s.Save()"

echo.
echo ======================================================
echo ACCESO DIRECTO CREADO EN EL ESCRITORIO
echo ======================================================
pause
