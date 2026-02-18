@echo off
echo ======================================================
echo COMPILANDO BUSCADOR DE PIEZAS SOLIDWORKS (ALSI)
echo ======================================================
echo Instalando dependencias necesarias...
pip install -r requirements.txt

echo.
echo === Generando recursos de imagen y Marca ===
python generar_icono.py

echo.
echo === Generando ejecutable FINAL (Limpio y con Icono) ===
python -m PyInstaller --noconfirm "BuscadorPiezas.spec"

echo.
echo === Copiando recursos a dist/ ===
copy "ALSI_ISOTIPO_naranja.png" "dist\"
copy "ALSI_IMAGOTIPO_naranja.png" "dist\"
copy "ALSI_BUSCADOR.ico" "dist\"
copy "INSTALAR_LOCAL.bat" "dist\"

echo.
echo === Desplegando en Unidad Z: ===
set RED_PATH="Z:\ALSI INTERCAMBIO\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS"
if exist %RED_PATH% (
    echo Copiando a %RED_PATH%...
    xcopy /Y /S /I "dist\*" %RED_PATH%
    echo Despliegue completado en red.
) else (
    echo [ERROR] No se pudo acceder a %RED_PATH%
)

echo.
echo Proceso finalizado. El ejecutable esta en 'dist/BuscadorPiezas.exe'
pause
echo.
echo ======================================================
echo PROCESO FINALIZADO
echo El ejecutable se encuentra en la carpeta 'dist'
echo ======================================================
