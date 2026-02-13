# Skill: pyinstaller-asset-bundling
Descripción: Mejores prácticas para asegurar que iconos y logos se vean siempre en ejecutables de un solo archivo.

## Concepto Clave: `_MEIPASS`
Cuando PyInstaller crea un "OneFile", desempaqueta los recursos en una carpeta temporal llamada `_MEIPASS` mientras el programa está en ejecución.

## Implementación Técnica
Para que el icono se vea siempre, el código debe buscarlo en esa carpeta temporal si está disponible:

```python
def resource_path(relative_path):
    import sys, os
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
```

## Configuración de Compilación
Se deben incluir los archivos explícitamente en el comando de compilación:
`--add-data "mi_icono.ico;."`
