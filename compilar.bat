@echo off
echo ======================================================
echo COMPILANDO BUSCADOR DE PIEZAS (ALSI) - V1.0.7
echo ======================================================
echo Instalando dependencias necesarias...
pip install -r requirements.txt

echo.
echo === Compilando extractor de propiedades SolidWorks ===
C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /reference:"C:\Program Files\Common Files\SOLIDWORKS Shared\SolidWorks.Interop.swdocumentmgr.dll" /reference:System.Web.Extensions.dll /out:"SwPropExtractor.exe" "SwPropExtractor.cs"

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
copy "config.ini" "dist\"

REM echo.
REM echo === Desplegando en Unidad Z: ===
REM set RED_PATH="\\192.168.1.10\Oficina Tecnica\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS"
REM if exist %RED_PATH% (
REM     echo Copiando a %RED_PATH%...
REM     xcopy /Y /S /I "dist\*" %RED_PATH%
REM     echo Despliegue completado en red.
REM ) else (
REM     echo [ERROR] No se pudo acceder a %RED_PATH%
REM )

echo.
echo Proceso finalizado. El ejecutable esta en 'dist/BuscadorPiezas.exe'
pause
echo.
echo ======================================================
echo PROCESO FINALIZADO
echo El ejecutable se encuentra en la carpeta 'dist'
echo ======================================================
