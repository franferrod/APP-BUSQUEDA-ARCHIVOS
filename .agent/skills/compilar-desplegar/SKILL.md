---
description: Workflow para compilar y desplegar la aplicación Buscador de Piezas
---

# Compilación y Despliegue

Sigue estos pasos para generar una nueva versión del ejecutable y desplegarla en la unidad de red.

## 1. Preparación

Asegúrate de haber guardado todos los cambios en los archivos `.py`.
Si has modificado recursos gráficos, asegúrate de que existen en la carpeta raíz.

## 2. Generar Icono (Opcional)

Si has cambiado `ALSI_ISOTIPO_naranja.png`, regenera el icono `.ico`:

```powershell
python generar_icono.py
```

## 3. Compilar

Ejecuta el script de compilación que usa PyInstaller.

```powershell
./compilar.bat
```
// turbo
Esto generará la carpeta `dist/` con el ejecutable y las dependencias.

## 4. Verificar Compilación

Antes de desplegar, prueba el ejecutable localmente:

```powershell
./dist/BuscadorPiezas.exe
```

Verifica:
- Que abre correctamente.
- Que muestra la versión correcta en la ventana.
- Que busca e indexa.

## 5. Desplegar a Red

Copia el contenido de `dist/` a la unidad de red `Z:`.

```powershell
xcopy /Y /S /I "dist\*" "Z:\ALSI INTERCAMBIO\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS"
```
// turbo

## 6. Notificar

Avisa a los usuarios de que hay una nueva versión disponible.
