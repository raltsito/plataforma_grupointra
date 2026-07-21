# Plan: Requerimientos Sistema Financiero INTRA (doc. Jesus, 09/07/2026)

Fuente: `Requerimientos_Sistema_Financiero_INTRA-1.pdf`. Objetivo: unificar recepcion, nomina semanal y nomina Academia dentro de `apps/finanzas`, sin doble captura ni reportes manuales.

Estado tomado el 2026-07-21 comparando el documento contra el codigo de `apps/finanzas`.

## Resumen de estado por criterio de aceptacion (seccion 8 del doc)

| # | Criterio | Estado |
|---|----------|--------|
| 1 | Sellar terapeuta en nomina semanal crea egreso automatico | Hecho |
| 2 | Pago base, bono y vale de gasolina se registran por separado | Hecho |
| 3 | Metodo de pago: transferencia, efectivo, pendiente, pagado | Hecho |
| 4 | Nomina descargada (imagen/PDF) con periodo, fecha, estatus, detalle y totales | Hecho (2026-07-21, Fase 1) |
| 5 | Reporte General de Recepcion importado/sincronizado sin copiar a otra plantilla | Hecho (2026-07-21, Fase 2b) |
| 6 | Datos de recepcion alimentan ingresos, pacientes, terapeutas, ranking, metodos de pago | Hecho (2026-07-21, Fase 2) |
| 7 | Nomina Academia: seleccionar maestro y capturar conceptos por cantidad | Hecho (2026-07-21, Fase 3) |
| 8 | Nomina Academia calcula automaticamente con tabuladores configurables | Hecho (2026-07-21, Fase 3) |
| 9 | Bloqueo de duplicados por periodo/persona/concepto | Hecho (2026-07-21, Fase 4 — helper compartido `existe_duplicado`, con nota de diseño: los imports/sync usan upsert a propósito, no el helper de bloqueo) |
| 10 | Ajustes posteriores se registran como "Ajuste", sin reescribir historial | Hecho (2026-07-21, Fase 4 — alcance acotado con el usuario, ver detalle abajo) |

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
- [x] Variables de Railway verificadas (no requirieron cambio): `CONSULTORIOWEB_API_URL`/`CONSULTORIOWEB_API_KEY` (proyecto CentralizacionIntra) ya coincidian con `RAILWAY_PUBLIC_DOMAIN`/`DJANGO_API_KEY` del proyecto SistemaIntra (ConsultorioWeb) desde la integracion previa de nomina semanal.
- [x] **Desplegado a produccion (2026-07-21):**
  - ConsultorioWeb: commit `6bb2ec79` + `railway up` en proyecto SistemaIntra/servicio web. Verificado en vivo: `https://www.agenda.intra.org.mx/api/reporte-general/` responde 200 con 295 citas reales del periodo 2026-07-01 a 2026-07-21 (mismo total que el Excel de referencia). Push a GitHub bloqueado por el clasificador de seguridad de la sesion — el commit existe localmente en `C:\Users\carlo\Documents\Freelancer\ConsultorioWeb` pero no en GitHub todavia; pendiente que el usuario haga `git push origin main` ahi manualmente.
  - portal_grupointra: commit `a1cb485`, push a GitHub exitoso, y `railway up` en proyecto CentralizacionIntra. Migracion `0004_citarecepcion` aplicada en produccion sin errores, servidor arriba (`https://portal.grupointra.mx/finanzas/` responde 200).
- [ ] Pendiente: probar la sincronizacion desde el navegador real (no solo via test client / curl) con sesion de usuario real del grupo Finanzas.

### Fase 3 — Nomina Academia (criterios 7, 8) — COMPLETADA (2026-07-21)
- [x] Modelo `Maestro` (nombre, activo) — catalogo simple, sin FK a Usuario (igual que Egreso.persona / CitaRecepcion.terapeuta: no existen cuentas de Usuario para Academia). Alta/edicion via `/admin/`.
- [x] Modelo `TabuladorAcademia` (concepto: horas_clase/supervision/mesa_trabajo, monto_unidad, vigente_desde) — versionado igual que `Tabulador` de terapeutas, con `TabuladorAcademia.vigente(concepto, fecha)` para tomar la tarifa vigente en el periodo capturado.
- [x] Modelo `NominaAcademia` (cabecera: maestro, periodo_mes, periodo_anio, metodo_pago, estatus, total congelado) + `ConceptoNominaAcademia` (linea: concepto, descripcion para el concepto manual, cantidad, tabulador usado, tarifa y subtotal congelados en `save()` — mismo patron que `Honorario.bono/total`). Incluye el "concepto manual autorizado" del documento (descripcion + monto libre, sin tabulador).
- [x] `apps/finanzas/nomina_academia.py::capturar_nomina_academia()`: crea la cabecera + lineas, calcula el total, y genera **un Egreso separado por concepto** (categoria `nomina_academia` nueva en `Egreso.Categoria`) — mismo patron de desglose que la nomina semanal de terapeutas. Bloquea capturar dos veces la misma nomina de un maestro/periodo (`NominaAcademiaError`).
- [x] Vista `nomina_academia_view` (`finanzas/nomina-academia/`): modal de captura (maestro, mes, año, metodo de pago, cantidades por concepto, concepto manual opcional) + tabla de nominas ya capturadas con boton de descarga. Formulario (`NominaAcademiaCaptureForm`) exige al menos un concepto capturado.
- [x] Descarga en PDF (`nomina_academia_descargar_view`, reusando `render_pdf` de la Fase 1): encabezado (Nomina Academia, maestro, periodo, estatus), tabla por concepto (docente, concepto, cantidad, tarifa, subtotal, metodo, estatus) con fila TOTAL A PAGAR, y totales (por docente, transferencia, efectivo, pendiente).
- [x] Probado extremo a extremo: captura con tabuladores reales (3 horas clase × $150 + 1 mesa de trabajo × $200 = $650, calculo verificado), 2 Egresos generados correctamente, segunda captura del mismo maestro/periodo bloqueada, captura solo con concepto manual ($500), formulario vacio rechazado sin crear nomina, y PDF descargado y verificado visualmente.
- [ ] Nota: la validacion de duplicados aqui es "todo o nada" por maestro/periodo (no permite re-capturar ni agregar conceptos sueltos despues) — la Fase 4 (estados + ajustes) debe agregar la forma correcta de corregir una nomina ya capturada.
- [x] **Desplegado a produccion (2026-07-21):** commit `5c637b5`, push a GitHub exitoso, `railway up` en CentralizacionIntra. Migracion `0005_maestro_tabuladoracademia_alter_egreso_categoria_and_more` aplicada en produccion sin errores. Verificado: `https://portal.grupointra.mx/finanzas/nomina-academia/` responde 200.

### Fase 4 — Estados, botones y controles unificados (criterio 10, complementa el 9) — COMPLETADA (2026-07-21)
Alcance acotado con el usuario antes de construir (para no arriesgar los flujos de Nomina Academia/Recepcion ya en produccion):
- Se decidio NO tocar el flujo de captura de Nomina Academia (sigue siendo captura = sellado inmediato, un solo paso) — solo se agrego el mecanismo de Ajuste para corregir despues.
- Se decidio que Ajuste (y cualquier otra captura que solo existia via /admin/) se registra con un modal en la UI de Finanzas, no solo por /admin/.
- Se decidio generalizar la validacion de duplicados en un helper compartido.

- [x] `apps/finanzas/duplicados.py`: `existe_duplicado(modelo, **filtros)` + `DuplicadoError`. Usado por `NominaAcademia` (refactorizado, ya no tiene su propia `NominaAcademiaError`) y por el nuevo `HonorarioForm`. `Egreso.referencia_externa` (import ConsultorioWeb) y `CitaRecepcion` (import Recepcion) **deliberadamente NO usan este helper** — son flujos de sincronizacion que deben actualizar el registro existente (`get_or_create`/`update_or_create`), no rechazarlo; usar el helper de bloqueo ahi seria incorrecto. Documentado en el propio modulo.
- [x] Modelo `Ajuste` (generic FK a `Honorario`, `NominaAcademia` o `Egreso` via `django.contrib.contenttypes`): `motivo`, `diferencia`, `egreso_generado` (OneToOne opcional). Los registros originales (`Honorario.total`, `NominaAcademia.total`) nunca se tocan — siguen congelados como ya funcionaban.
- [x] `apps/finanzas/ajustes.py::registrar_ajuste(modelo, objeto_id, motivo, diferencia)`: si la diferencia es positiva (monto adicional a favor), genera un Egreso nuevo separado (categoria segun el tipo de origen). Si es negativa, solo queda registrada para trazabilidad — **no se modela nota de credito/reembolso todavia** (limitacion documentada, no una omision).
- [x] Nueva pantalla "Ajustes" (`finanzas/ajustes/`) con modal de captura (elegir Honorario, NominaAcademia o Egreso a corregir + motivo + diferencia) y tabla de ajustes registrados.
- [x] Modales agregados para todo lo que antes solo se creaba via `/admin/` (pedido explicito del usuario, "si hay mas cosas que solo se agregan en /admin hazles modal a todas"):
  - `Tabulador` (terapeutas) y `Honorario` → modales en `honorarios.html`.
  - `Maestro` y `TabuladorAcademia` → modales en `nomina_academia.html`.
  - `HonorarioForm` usa `existe_duplicado` para bloquear un honorario duplicado de terapeuta/periodo con un mensaje amigable (antes solo existia el `unique_together` crudo de Django admin).
- [x] Bug encontrado y corregido durante las pruebas: `ModelChoiceField` con un queryset recortado (`[:200]`) rompe la validacion interna de Django (`queryset.get(pk=...)` sobre un queryset ya con slice lanza `TypeError`, que Django traduce silenciosamente en "Select a valid choice"). Se quito el slice en los 3 `ModelChoiceField` de `AjusteForm`.
- [x] Probado extremo a extremo (12 casos): alta de Tabulador/Honorario/Maestro/TabuladorAcademia via modal, honorario duplicado bloqueado, ajuste positivo sobre Honorario (genera Egreso, no reescribe el total original), ajuste positivo sobre NominaAcademia (idem), ajuste negativo (no genera Egreso, si queda registrado), formulario de ajuste sin seleccion y con doble seleccion (ambos rechazados), listado de ajustes.
- [ ] Pendiente (fuera de alcance de esta fase, documentado como decision consciente): el flujo Borrador → Pendiente → Pagado → Sellado completo del documento (seccion 7) no se implemento tal cual; Nomina Academia y Recepcion siguen siendo "captura = resultado final". Si se necesita mas adelante, retomar desde aqui.
- [x] **Desplegado a produccion (2026-07-21):** commit `d155680`, push a GitHub exitoso, `railway up` en CentralizacionIntra (status SUCCESS). Verificado: `https://portal.grupointra.mx/finanzas/ajustes/`, `/finanzas/honorarios/` y `/finanzas/nomina-academia/` responden 200 (la pantalla de Ajustes en particular ya prueba que la tabla `Ajuste` existe en produccion).

## Estado final: 10/10 criterios de aceptacion cubiertos (2026-07-21)
Las 4 fases del plan quedaron completadas y desplegadas a produccion el mismo dia. Pendientes documentados como decisiones conscientes (no como huecos): flujo completo Borrador/Sellado para Academia/Recepcion, notas de credito para ajustes negativos, y que `agenda.intra.org.mx` construya su propio consumidor si algun dia deja de ser portal_grupointra quien sincroniza.

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
