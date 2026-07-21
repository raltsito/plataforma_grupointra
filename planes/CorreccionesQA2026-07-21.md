---
name: correcciones-qa-2026-07-21
---

# Correcciones de QA (feedback sobre checklist previa, 2026-07-21)

Contexto: el usuario probó el checklist anterior (capturas de WhatsApp, con ✓ = confirmado funcionando) y reportó 4 problemas reales sobre las pantallas base de Finanzas (Tablero, Ingresos, Donativos, Reportes) — no relacionados con el documento de requerimientos de Nómina/Recepción/Academia (esos ya quedaron 10/10, ver `DocumentoRequerimentosJesus.md`).

## Feedback recibido y corrección aplicada

1. **"Modificar pendiente, parcial y pagado — si está pendiente que no lo sume al tablero hasta que esté pagado."**
   - Corregido: nuevos helpers `_ingresos_efectivos`, `_egresos_efectivos`, `_honorarios_efectivos`, `_donativos_efectivos` en `views.py`. Un Ingreso/Egreso/Honorario Pendiente ya no suma en Tablero ni en Reportes hasta que se marca Pagado.

2. **"Ingresos: el monto parcial ponerlo aparte del monto total, que se diferencie el total de lo que se debe y lo que se pagó."**
   - Corregido: nuevo campo `Ingreso.monto_pagado`. La pantalla de Ingresos ahora muestra 3 cifras claramente distintas: **Total capturado** (todo lo registrado), **Cobrado** (Pagado completo + lo ya cobrado de un Parcial), **Pendiente por cobrar** (la diferencia). La tabla de ingresos tiene una columna "Cobrado" nueva.

3. **"Agregar opción Configuración: agregar opciones de concepto, etc."**
   - Corregido: nueva pantalla "Configuración" (`finanzas/configuracion/`) con catálogos `ConceptoIngreso` y `CategoriaEgreso` — se pueden agregar conceptos/categorías nuevas sin tocar código ni redeploy. Los conceptos/categorías base (Consulta, Nómina, Insumos, etc.) siguen fijos porque el Tablero/Reportes los usan por nombre para agrupar; un Egreso con categoría nueva se reporta en un renglón "Otros egresos" en Reportes, para que el total siempre cuadre.

4. **"Donativos y CFDI: modificar vigente, en trámite y cancelado — si está cancelado que no lo agregue a la suma."**
   - Corregido: `_donativos_efectivos()` excluye Cancelado de todas las sumas (Tablero, Reportes, y las propias tarjetas de la pantalla de Donativos).

## Alcance NO tocado (para no arriesgar lo que ya funcionaba)
- El feed de "Movimientos recientes" del Tablero sigue mostrando todo lo capturado (incluye Pendientes), porque es una bitácora de actividad, no una suma — se le quitaron los Donativos Cancelados por consistencia, pero no los Ingresos/Egresos Pendientes (mostrar que algo se capturó, aunque no cuente todavía, es información útil ahí).
- Egreso no tiene estatus "Parcial" (solo Pagado/Pendiente) — no se agregó, no fue parte del feedback.

## Pruebas realizadas
Probado extremo a extremo con datos sintéticos vía Django test client (ver conversación): Ingreso Pagado/Parcial/Pendiente sumando correctamente, Egreso Pendiente excluido, Honorario Pendiente excluido, Donativo Cancelado excluido, validación de `monto_pagado > monto` rechazada, catálogo de Configuración agregando opciones nuevas y apareciendo en los formularios, categoría custom cayendo en "Otros egresos" de Reportes.

## Pendiente
- Probar manualmente en el navegador (checklist entregada al usuario como Artifact).
- Commit + deploy a producción, pendiente de confirmación del usuario tras revisar el checklist.
