# 🔍 Manual de Usuario: Buscador de Piezas ALSI (V1.3.4.5)

Este manual está diseñado para ayudarte a encontrar archivos de diseño (SolidWorks, PDF, DWG, etc.) de manera rápida y sencilla, sin necesidad de ser un experto en informática.

---

## 🛠 1. ¿Para qué sirve esta aplicación?
El **Buscador de Piezas** es una herramienta que centraliza todos los archivos de diseño guardados en las carpetas de los compañeros (**JUAN, SERGIO, MANU, PABLO, DANI**). En lugar de buscar carpeta por carpeta en Windows, puedes filtrar por cliente, año o código de proyecto desde un solo lugar.

---

## 🚀 2. Guía de Inicio Rápido

### A. Realizar una búsqueda
1.  **Escribe en los filtros**: En la parte superior verás cuadros para **Cliente**, **Proyecto** y **Órden**.
2.  **Espera un instante**: La aplicación espera **0.3 segundos** después de que dejas de escribir para mostrar los resultados. Esto evita que la pantalla se congele.
3.  **Mira los resultados**: Verás una lista con el nombre del archivo, quién lo tiene, el año y la ruta completa.

### B. Uso de los Filtros Inteligentes (Cascada)
La aplicación es inteligente: si seleccionas un **Año** específico, los filtros de **Cliente** y **Proyecto** solo mostrarán lo que existe en ese año.
*   **Compañeros**: Puedes marcar o desmarcar a quién quieres buscar.
*   **Tipo de Archivo**: En la esquina superior derecha puedes elegir ver solo PDFs, solo Planos (SLDDRW), solo Piezas (SLDPRT), etc.

---

## 📁 3. Acciones con los archivos
Una vez que encuentres lo que buscas:
*   **Abrir el archivo**: Haz **Doble Clic** sobre el archivo. Se abrirá automáticamente con el programa que corresponda (SolidWorks, Acrobat, etc.).
*   **Ir a la carpeta**: Pulsa el **Botón Derecho** sobre el archivo y elige "Abrir carpeta contenedora". Se abrirá una ventana de Windows justo donde está el archivo.

---

## 🔄 4. Actualizar la base de datos (Indexación)
Si alguien ha guardado archivos nuevos y no aparecen en la búsqueda, debes "Indexar".

1.  Pulsa el botón **"Indexar Piezas"** (abajo a la izquierda).
2.  **Selecciona lo que necesites**: 
    *   Puedes elegir actualizar solo a un compañero (ej. "SERGIO").
    *   Puedes elegir actualizar solo un **Año** (ej. "2024").
    *   *Tip: Si solo actualizas lo que ha cambiado, el proceso tardará apenas unos segundos.*
3.  Pulsa **"Iniciar Indexación"**. Verás una barra de progreso. No cierres el programa hasta que termine.

---

## ❓ 5. Preguntas Frecuentes y Solución de Problemas

**¿Por qué no aparece un archivo que acabo de guardar?**
> Debes ejecutar la **Indexación** para que el programa "sepa" que ese archivo existe.

**¿Por qué la búsqueda tarda un poco en actualizarse mientras escribo?**
> El programa usa una técnica llamada "Debouncing" para ser más fluido. Espera un breve momento (300ms) para asegurarse de que has terminado de escribir antes de consultar la base de datos.

**¿Qué pasa si una unidad de red (Z:) no está conectada?**
> El programa te avisará con un mensaje de advertencia. Asegúrate de tener acceso a las carpetas compartidas en tu equipo.

---

> [!TIP]
> **Consejo Pro**: Si buscas un código de proyecto específico (ej: 24001), escríbelo directamente en el filtro de "Proyecto" para filtrar instantáneamente miles de archivos.

---
*ALSI - Departamento de Diseño*
