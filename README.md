<div align="center">

<img src="ALSI_IMAGOTIPO_naranja.png" alt="ALSI Logo" width="280"/>

# 🔍 Buscador de Piezas ALSI

**Herramienta interna de búsqueda de archivos CAD para la Oficina Técnica de ALSI**

[![Versión](https://img.shields.io/badge/versión-1.0.5-orange?style=flat-square)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)](https://python.org)
[![PyQt5](https://img.shields.io/badge/UI-PyQt5-green?style=flat-square)](https://riverbankcomputing.com/software/pyqt)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?style=flat-square&logo=windows)](https://microsoft.com/windows)
[![Tests](https://img.shields.io/badge/tests-22%20passed-brightgreen?style=flat-square)](tests/)

</div>

---

## 🌟 ¿Qué hace esta aplicación?

El **Buscador de Piezas ALSI** permite encontrar en segundos cualquier archivo de diseño (SolidWorks, AutoCAD, PDF...) almacenado en los equipos de la oficina técnica, sin necesidad de recordar en qué carpeta está ni de quién es el proyecto.

Indexa de forma inteligente las carpetas de red de todos los compañeros y permite buscar por nombre de pieza, cliente, proyecto o año, con previsualización de miniaturas en tiempo real.

---

## ✨ Características principales

| Función | Descripción |
|---|---|
| 🔎 **Búsqueda inteligente** | Multi-palabra separada por comas, insensible a tildes y acentos |
| ⚡ **Búsqueda instantánea** | Indexación local en SQLite, resultados en < 1 segundo |
| 🖼️ **Miniaturas asíncronas** | Previsualización de piezas SW, PDFs y planos sin bloquear la UI |
| 📂 **Filtros en cascada** | Compañero → Año → Cliente → Proyecto → Orden |
| 🏗️ **Propiedades SolidWorks** | Extracción de Soldadura, Pintura, Láser, Material, etc. |
| 🖱️ **Drag & Drop** | Arrastra directamente a SolidWorks para abrir o insertar |
| 📚 **Bibliotecas comerciales** | Búsqueda en Siddex, ALSI Estándar y Dark Web J.A. |
| 💾 **Memoria de sesión** | Recuerda tus filtros y configuración entre sesiones |

---

## 🗂️ Estructura del proyecto

```
BÚSQUEDA PIEZAS/
├── buscar_piezas.py       # Vista principal (UI / PyQt5)
├── controllers.py         # Lógica de negocio e indexación
├── models.py              # Base de datos SQLite (IndexManager)
├── tests/
│   └── test_buscar.py     # Suite de tests (22 tests) ✅
├── docs/
│   └── GUIA_RAPIDA.md     # Manual de usuario
├── releases/              # Historial de versiones compiladas
│   ├── v1.0.1/
│   ├── v1.0.2/
│   ├── v1.0.3/
│   ├── v1.0.4/
│   └── v1.0.5/            # ← Versión actual
├── CHANGELOG.md           # Historial de cambios
├── compilar.bat           # Script de compilación con PyInstaller
└── DESPLEGAR_VERSION.bat  # Script de despliegue a la red
```

---

## 🚀 Historial de versiones

### [v1.0.5] — 2026-03-13 · Estabilidad Crítica
> Versión de corrección urgente. Soluciona múltiples causas de cierre inesperado reportadas en equipos de la oficina.

- 🔴 Fix: Hilo de miniaturas crasheaba silenciosamente en **cada búsqueda** (variables sin definir)
- 🔴 Fix: `on_sw_file_extracted` referenciaba atributo inexistente → crash al seleccionar piezas SW
- 🟡 Fix: Llamadas COM redundantes en el hilo de thumbnails → `AccessViolation` esporádico en red
- 🟡 Fix: Métodos duplicados en la clase principal → `closeEvent` incorrecto no guardaba preferencias
- 🟠 Fix: Guard inseguro en `iniciar_extraccion_sw` → `RuntimeError` ocasional
- 🔵 Fix: `import time` faltaba en cabecera

### [v1.0.4] — 2026-03-03 · Extracción SolidWorks
- Nueva funcionalidad: Extracción de propiedades personalizadas de piezas SW (Láser, Soldadura, Pintura, Material...)
- Filtros por procesos de fabricación en el panel lateral
- Extracción batch en segundo plano con barra de progreso

### [v1.0.3] — 2026-02-26 · Thumbnails y Sin Acentos
- Columna "Vista" con miniaturas asíncronas de piezas, PDFs y planos
- Búsqueda insensible a acentos/tildes
- Filtro independiente para Dark Web J.A. (Javier Alonso)
- Fix crítico de Drag & Drop a SolidWorks

### [v1.1.0] — 2026-02-20 · Compatibilidad Windows 7
- Versión especial para Rubén con Python 3.8.10 embebido
- Fix de DLLs del sistema para equipos antiguos

### [v1.0.0] — 2026-02-18 · Lanzamiento Oficial
- Primera versión de producción desplegada en la Oficina Técnica

---

## 🛠️ Desarrollo

### Requisitos

```bash
pip install -r requirements.txt
# PyQt5, pywin32, olefile, PyMuPDF, pyinstaller
```

### Ejecutar en desarrollo

```bash
python buscar_piezas.py
```

### Tests

```bash
python -m pytest tests/ -v
# 22 passed ✅
```

### Compilar ejecutable

```batch
compilar.bat
# Genera dist/BuscadorPiezas.exe
```

### Desplegar en red

```batch
DESPLEGAR_VERSION.bat
# Copia el ejecutable a Z:\ALSI INTERCAMBIO\...
```

---

## 🏗️ Arquitectura

El proyecto sigue el patrón **MVC** sobre PyQt5:

```
Vista (buscar_piezas.py)
    │  señales PyQt5
    ▼
Controlador (controllers.py)
    │  IndexadorThread / ThumbnailWorker / SWPropertyExtractorThread
    ▼
Modelo (models.py)
    │  SQLite (~/.alsi_busqueda/index.db)
    ▼
Rutas de red (\\OFITEC-X\alsi proyectos aprobados)
```

---

## 👤 Autor

**Francisco Fernández Rodríguez**  
Departamento de Oficina Técnica — ALSI

---

<div align="center">
<sub>Uso interno — ALSI © 2026</sub>
</div>
