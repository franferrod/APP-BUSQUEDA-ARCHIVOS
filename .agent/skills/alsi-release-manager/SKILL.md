---
description: Gestión de versiones, etiquetado Git y despliegue en red para ALSI Buscador
---

# ALSI Release Manager - Skill de Gestión

Esta Skill define el proceso estándar para publicar nuevas versiones, documentar cambios y permitir rollbacks (re-despliegues de versiones anteriores).

## Proceso de Lanzamiento (Release)

Al finalizar una mejora o corrección:

1.  **Actualizar Versión**:
    - Cambiar `lbl_ver` en `buscar_piezas.py` (método `mostrar_info`).
    - Añadir los cambios al historial en el `QTextBrowser` de la ventana "Acerca de".
2.  **Compilar**:
    - Ejecutar `compilar.bat` para generar el nuevo `.exe` en `dist/`.
3.  **Etiquetar en Git**:
    - Confirmar cambios: `git add .` + `git commit -m "V1.X.X: Descripción"`.
    - Crear etiqueta: `git tag v1.X.X`.
    - (Opcional) Subir a GitHub: `git push origin master --tags`.
4.  **Archivar**:
    - Crear carpeta `releases/v1.X.X/`.
    - Copiar el contenido de `dist/*` a `releases/v1.X.X/`.
5.  **Desplegar**:
    - Copiar el contenido de `dist/*` a la carpeta de red (Ruta IP: `\\192.168.1.229\Volume_1\ALSI INTERCAMBIO\ALSI DOCUMENTOS OT\APP BÚSQUEDA ARCHIVOS`).

## Gestión de Rollbacks (Re-despliegue)

Si una versión nueva falla y se necesita volver a una anterior:

1.  Localizar la versión deseada en la carpeta `releases/`.
2.  Ejecutar el script `DESPLEGAR_VERSION.bat` pasando la versión como argumento.
    - Ejemplo: `DESPLEGAR_VERSION.bat v1.0.1`.
3.  Confirmar que los archivos en la red han sido sobrescritos.

## Estructura de releases

```text
releases/
├── v1.0.0/ (Lanzamiento inicial)
├── v1.0.1/ (Auto-update + UNC Fix)
└── v1.0.2/ (Búsqueda sin acentos)
```

## Recomendaciones Proactivas

- **Documentación Git**: Cada commit debe empezar con la versión (ej: `V1.0.2: ...`).
- **Verificación de Red**: Antes de cada despliegue, verificar que la ruta IP sea accesible.
- **Backups de DB**: Aunque la DB es local, es recomendable guardar una copia de `index.db` en la carpeta `releases/vX.X.X` si hay cambios en el esquema.
