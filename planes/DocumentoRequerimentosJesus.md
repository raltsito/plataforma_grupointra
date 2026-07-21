# Plan: Requerimientos Sistema Financiero INTRA (doc. Jesus, 09/07/2026)

Fuente: `Requerimientos_Sistema_Financiero_INTRA-1.pdf`. Objetivo: unificar recepcion, nomina semanal y nomina Academia dentro de `apps/finanzas`, sin doble captura ni reportes manuales.

Estado tomado el 2026-07-21 comparando el documento contra el codigo de `apps/finanzas`.

## Resumen de estado por criterio de aceptacion (seccion 8 del doc)

| # | Criterio | Estado |
|---|----------|--------|
| 1 | Sellar terapeuta en nomina semanal crea egreso automatico | Hecho |
| 2 | Pago base, bono y vale de gasolina se registran por separado | Hecho |
| 3 | Metodo de pago: transferencia, efectivo, pendiente, pagado | Hecho |
| 4 | Nomina descargada (imagen/PDF) con periodo, fecha, estatus, detalle y totales | Falta |
| 5 | Reporte General de Recepcion importado/sincronizado sin copiar a otra plantilla | Falta |
| 6 | Datos de recepcion alimentan ingresos, pacientes, terapeutas, ranking, metodos de pago | Falta |
| 7 | Nomina Academia: seleccionar maestro y capturar conceptos por cantidad | Falta |
| 8 | Nomina Academia calcula automaticamente con tabuladores configurables | Falta |
| 9 | Bloqueo de duplicados por periodo/persona/concepto | Parcial (solo ConsultorioWeb import + Honorario mensual) |
| 10 | Ajustes posteriores se registran como "Ajuste", sin reescribir historial | Falta |

Lo ya construido vive en `apps/finanzas/integraciones/consultorioweb.py` e `importador_nomina.py` (import de cortes semanales via API de ConsultorioWeb) y en el modelo `Egreso` (campos `metodo_pago`, `estatus`, `referencia_externa`).

## Fases (orden sugerido por el propio documento, seccion 8 "Prioridad recomendada")

### Fase 1 — Cerrar nomina semanal + descarga (criterios 3, 4, 9 parcial)
- [x] Libreria de PDF decidida y probada: `xhtml2pdf==0.2.17` (pura Python, sin dependencias de sistema tipo GTK — corre igual en Windows dev y Railway/Linux). Agregada a `requirements.txt`.
- [x] Decidido: solo PDF descargable (no version PNG/imagen aparte).
- [x] Vista de descarga implementada: `apps/finanzas/views.py::nomina_descargar_view`, URL `finanzas:nomina_descargar` (`nomina/descargar/`), boton "Descargar nomina (PDF)" agregado en `nomina.html` junto al filtro de fechas.
- [x] `apps/finanzas/reportes_nomina.py` — reconstruye una fila por persona (pago base / vale de gasolina / bono) a partir de los Egresos separados que ya crea `importador_nomina.py`, usando el sufijo de `referencia_externa` (`:base`/`:bono`/`:extra`); no requirio cambios de modelo ni migracion nueva.
- [x] `apps/finanzas/pdfs.py` — helper `render_pdf()` generico (reusable para la descarga de Nomina Academia en Fase 3) con `link_callback` para resolver el logo de INTRA (`core/images/intra-logo.png`) via staticfiles.
- [x] Template `apps/finanzas/templates/finanzas/nomina_pdf.html` — encabezado con logo, periodo, badge de estatus; tabla por persona (tipo, concepto, metodo, estatus, pago base, vale, bono, total); totales (pendiente por dispersar, transferencia, efectivo, vales/extras pendientes); detalle de vales de gasolina; fecha/hora de generacion.
- [x] Probado extremo a extremo: datos vacios, datos de ejemplo (calculo de totales verificado a mano) y via Django test client con el permiso real (`acceso_finanzas_requerido`) — status 200, PDF valido, filename correcto.
- [ ] Pendiente (movido a Fase 4): el estatus mostrado hoy es solo Pagado/Pendiente derivado de los Egresos; el badge "Sellado" real requiere el sistema de estados completo. Por ahora el PDF es funcional pero no distingue Borrador/Sellado.
- [ ] Pendiente: probar visualmente en el navegador (`python manage.py runserver` + click en "Descargar nomina (PDF)") con datos reales de ConsultorioWeb, no solo datos de prueba sinteticos.

### Fase 2 — Reporte General de Recepcion (criterios 5, 6) — COMPLETADA (2026-07-21)
- [x] Mecanismo de entrada decidido: **importacion de Excel** (`.xlsx` exportado de agenda.intra.org.mx/reporte-general/). Confirmado con el solicitante que hoy no existe API del lado de Recepcion; el codigo queda separado en capas (`integraciones/reporte_recepcion.py` = fuente de datos, `integraciones/importador_recepcion.py` = logica de negocio) para poder cambiar a un cliente API despues sin tocar la logica de negocio, igual que el patron ya usado en ConsultorioWeb.
- [x] Modelo nuevo `CitaRecepcion` (`apps/finanzas/models.py`) con los campos de la tabla 5.1: fecha, hora, tipo_cita, paciente, terapeuta (CharField, no FK — no existen todavia cuentas de Usuario para terapeutas en el sistema), servicio, division, consultorio, estatus, metodo_pago, costo, mas un `OneToOneField` opcional a `Ingreso` para trazabilidad. Migracion `0004_citarecepcion.py` aplicada.
- [x] Catalogo real de Estatus confirmado con captura de pantalla de Recepcion: Confirmada, Sin confirmar, Reagendo, Cancelo, Si asistio, No asistio, Incidencia.
- [x] Regla de negocio confirmada con el solicitante (2026-07-21): **solo "Si asistio" cuenta como ingreso real** (ni "Confirmada" ni "Incidencia" cuentan). Ademas, sin importar el estatus, metodo de pago "Pase" o costo $0 tampoco cuentan (regla explicita del documento) — logica en `importador_recepcion.py::cuenta_como_ingreso`.
- [x] Validacion de duplicados: `unique_together` en `CitaRecepcion` por (fecha, hora, paciente, terapeuta, servicio), tal cual pide la seccion 5.1.
- [x] Recalculo al corregir estatus: `importar_cita()` usa `update_or_create` + sincroniza el `Ingreso` ligado (lo crea, actualiza monto/estatus, o lo borra si la cita deja de calificar). Probado explicitamente: cambiar una cita de "Si asistio" a "Cancelo" borro su Ingreso automaticamente.
- [x] Vista `reporte_recepcion_view` (`finanzas/reporte-recepcion/`): formulario de subida de Excel + KPIs (citas importadas, citas con asistencia, ingresos generados) + ranking de terapeutas (citas atendidas y total generado) + comparativo por metodo de pago + tabla de ultimas citas importadas. Liga en el sidebar (`_base.html`).
- [x] Probado extremo a extremo con el archivo real `reporte_intra_2026-07-01_2026-07-21.xlsx` (295 citas, 173 con "Si asistio", 156 generaron Ingreso tras excluir Pase/costo $0): import inicial, reimport idempotente (no duplica), y correccion de estatus con recalculo — los tres casos verificados via Django test client con el permiso real de Finanzas.
- [ ] Pendiente: probar la subida del Excel real en el navegador (no solo via test client) y revisar visualmente el ranking/comparativo con datos reales.
- [x] Correccion (2026-07-21): el repo de ConsultorioWeb/agenda.intra.org.mx si esta en poder del usuario — `C:\Users\carlo\Documents\Freelancer\ConsultorioWeb`. Se puede construir ahi un endpoint `/api/reporte-general/` igual que `/api/nomina-semanal/`, y luego cambiar `reporte_recepcion.py` de leer Excel a llamar esa API (mismo patron que `consultorioweb.py`). Ver Fase 2b abajo.

### Fase 2b — API de Reporte General en ConsultorioWeb — COMPLETADA (2026-07-21)
- [x] `/api/nomina-semanal/` investigado: vistas planas (sin DRF) en `clinica/views.py`, decorador `@api_key_required` (`clinica/api_auth.py`) que valida header `X-API-Key` contra `settings.DJANGO_API_KEY`. Convención replicada tal cual.
- [x] Repo de ConsultorioWeb (`C:\Users\carlo\Documents\Freelancer\ConsultorioWeb`, **repo separado, propiedad del usuario**): agregado `api_reporte_general(request)` en `clinica/views.py` (junto a `api_nomina_semanal`) y registrada la ruta `path('api/reporte-general/', ...)` en `core/urls.py`. Devuelve `Cita.objects.filter(fecha__range=...)` en crudo (fecha/hora ISO, estatus como código interno `si_asistio`/etc., metodo_pago como en `PAGO_CHOICES`, costo float) — mismo criterio que nomina-semanal: sin aplicar reglas de negocio, eso lo decide quien consume.
- [x] `apps/finanzas/integraciones/consultorioweb.py` (portal_grupointra): agregada `obtener_citas_recepcion(fecha_inicio, fecha_fin)`, mismo patron que `obtener_cortes_semanales`.
- [x] `apps/finanzas/integraciones/reporte_recepcion.py`: nueva `leer_reporte_api()` que llama esa funcion y normaliza al mismo formato que `leer_reporte_excel()` (ajustado `_fecha()` para aceptar tanto `DD/MM/YYYY` del Excel como ISO de la API; ajustado `_estatus()` para aceptar tanto "Si asistio" (Excel) como `si_asistio` (código de la API)).
- [x] Vista `reporte_recepcion_view` actualizada: la API es la via principal (formulario "Sincronizar con ConsultorioWeb" con rango de fechas, deshabilitado si `CONSULTORIOWEB_API_URL` no esta configurado), el Excel queda como respaldo manual colapsado en un `<details>`.
- [x] Probado extremo a extremo levantando el servidor de ConsultorioWeb en local (puerto 8811, base de datos demo con datos de abril 2026): sincronizacion inicial (44 citas nuevas + 2 actualizadas por llaves duplicadas en los datos demo, 7 generaron ingreso), re-sincronizacion idempotente (0 nuevas, sin duplicar), y pantalla con ranking funcionando con datos reales de esa base.
- [ ] Pendiente: definir y configurar `CONSULTORIOWEB_API_URL` / `CONSULTORIOWEB_API_KEY` en el entorno real (Railway) para produccion — hoy son env vars vacias en `config/settings.py`.
- [ ] Pendiente: probar la sincronizacion desde el navegador real (no solo via test client) contra el servidor de ConsultorioWeb en el entorno que corresponda.

### Fase 3 — Nomina Academia (criterios 7, 8)
- [ ] Modelo `Maestro`/`Docente` (activo, filtrable por nombre) — catalogo simple, alta/seleccion.
- [ ] Modelo `TabuladorAcademia` (monto por concepto: horas clase, supervision, mesa de trabajo, otros; versionado por fecha de vigencia, igual patron que `Tabulador` de terapeutas — nunca editar uno vigente).
- [ ] Modelo `NominaAcademia` (o conceptos dentro de un solo modelo con FK a maestro + periodo + concepto + cantidad + tarifa congelada + subtotal), calculo automatico cantidad x tarifa, metodo de pago (transferencia/efectivo/pendiente/pagado).
- [ ] Vista con flujo: entrar al modulo, elegir periodo, elegir maestro, submenu de conceptos, capturar cantidades, calcular total automatico, guardar como egreso de Academia (categoria nueva en `Egreso`, ej. `nomina_academia`), boton sellar.
- [ ] Descarga en imagen/PDF (reusar la solucion de la Fase 1): encabezado (nomina Academia, periodo, fecha de pago, estatus, usuario que genera), tabla (docente, concepto, cantidad, tarifa, subtotal, metodo, estatus), totales (por docente, transferencia, efectivo, pendiente, general).
- [ ] Validacion: evitar duplicar nomina por docente/periodo/concepto salvo que se registre como ajuste (depende de Fase 4).

### Fase 4 — Estados, botones y controles unificados (criterio 10, complementa el 9)
- [ ] Introducir estado `Sellado` y `Ajuste` (hoy solo existe Pagado/Pendiente/Parcial) en los modelos relevantes: `Egreso`, `Honorario`, y los nuevos de Academia/Recepcion.
  - Reglas de transicion (tabla seccion 7 del doc): Borrador → editable/eliminable; Pendiente → cambiar metodo, marcar pagado, descargar; Pagado → bloquear cambios sensibles, permitir observaciones; Sellado → genera egreso automatico y bloquea duplicados; Ajuste → requiere motivo y diferencia, no reescribe historial original.
- [ ] Unificar botones segun tabla de la seccion 7: Ver detalle, Guardar borrador, Sellar terapeuta/docente, Sellar periodo, Descargar imagen, Exportar PDF, Registrar ajuste.
- [ ] Generalizar la validacion de duplicados (hoy solo cubre `Egreso.referencia_externa` y `Honorario` mensual) a un helper reusable por periodo+persona+concepto, aplicable a Academia y Recepcion tambien.
- [ ] Modelo/flujo de "Ajuste": nueva entrada que referencia el registro original, guarda motivo + diferencia, sin tocar el monto/estado ya sellado.

## Decisiones pendientes de confirmar con el solicitante (Administracion INTRA / Jesus)
1. Reporte General de Recepcion: ¿existe API como ConsultorioWeb, o solo exportacion Excel? Define si Fase 2 es un importador de archivo o un cliente API.
2. Libreria de generacion de PDF/imagen (weasyprint vs reportlab vs otra) — impacta requirements.txt y el Procfile/Railway.
3. Confirmar catalogo exacto de "conceptos" para Nomina Academia (horas clase, supervision, mesa de trabajo, "otros si aplica" — que otros conceptos existen).
4. Confirmar que estatus de Recepcion cuentan como ingreso real (asistio/confirmado/pagado) y cuales no.

## Notas de arquitectura (para mantener consistencia con CLAUDE.md)
- Todo lo nuevo va dentro de `apps/finanzas` (modelos, migraciones, templates bajo `apps/finanzas/templates/finanzas/`, namespace `finanzas:`).
- Seguir el patron ya usado en `integraciones/` para cualquier import externo (Recepcion), con su propio archivo tipo `importador_recepcion.py` si aplica.
- Igual que `Honorario`, cualquier monto ya sellado/congelado no debe recalcularse si el tabulador cambia despues — extender ese mismo criterio a Academia.
- Vistas protegidas por `acceso_finanzas_requerido`, igual que las 7 vistas actuales.
