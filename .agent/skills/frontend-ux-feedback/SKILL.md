# Skill: frontend-ux-feedback
Descripción: Mejora de la experiencia de usuario mediante micro-interacciones y feedback visual.

## Principios
1. **Feedback Inmediato**: Cada clic debe tener una reacción visual (cambio de cursor, estado de botón).
2. **Estados de Carga**: Usar barras de progreso o mensajes de "Buscando..." claros.
3. **Transiciones Suaves**: Aplicar QPropertyAnimation en PyQt5 para que los paneles no "salten" al abrirse/cerrarse.

## Ejemplo de Animación en Filtros
Para que el panel lateral de filtros se sienta premium:
```python
self.anim = QPropertyAnimation(self.filtros_panel, b"maximumWidth")
self.anim.setDuration(300)
self.anim.setStartValue(0)
self.anim.setEndValue(300)
self.anim.start()
```
