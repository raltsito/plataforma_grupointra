# Pasarela de mensajería — bitácora de implementación

Documenta la construcción de `apps/mensajeria` a partir de
`Contrato pasarela de mensajería v1 - Grupo INTRA` (Carlos, 8 de septiembre
de 2026). Este archivo es la bitácora del proceso — decisiones tomadas,
discrepancias encontradas contra el contrato original y lo que falta — no
un manual de uso. Se va actualizando conforme avanza el trabajo.

## Estado actual (2026-09-08)

`apps/mensajeria` está construida, probada (9 pruebas propias + suite
completa del proyecto en verde, 124 tests) y montada en el proyecto. **No
está conectada a `crm_ventas`** porque esa app todavía está en construcción
(fuera de este repo) — es la única pieza que falta, y es intencionalmente
la última: el contrato la diseñó como servicio compartido con
`GenericForeignKey`, así que no necesita que `crm_ventas` exista para
funcionar ni para probarse.

## Discrepancia encontrada contra el contrato original

El contrato asume que `apps/crm_ventas` ya existe en este repo con el
modelo `MensajeWhatsApp` y la vista `whatsapp_prospecto` simulando el
envío ("Hallazgo 1 y 2" del contrato). Al revisar el checkout local de
`portal_grupointra` el 8 de septiembre de 2026, esa app **no existe** —
tampoco en el fork `RocioMedC/plataforma_grupointra` que `CLAUDE.md` señala
como fuente alterna de trabajo (no se encontró por búsqueda de texto en el
árbol de trabajo). Confirmado con el usuario: `crm_ventas` está en
construcción por separado. Conclusión: se construye la pasarela primero,
aislada, y la Fase 2 (conectar `crm_ventas`) queda pendiente hasta que esa
app esté lista.

## Qué se construyó

Todo dentro de `apps/mensajeria/`:

- **`models.py`** — `Envio`, `Baja`, `UltimaInteraccion`, `SistemaSuscrito`.
- **`meta_client.py`** — cliente de WhatsApp Cloud API (Meta): envío de
  plantillas y verificación de firma de webhooks entrantes
  (`X-Hub-Signature-256`).
- **`servicios.py`** — la lógica de negocio: normalización E.164,
  validación de plantilla/variables contra `settings.MENSAJERIA_PLANTILLAS`,
  idempotencia, bajas, despacho a Meta, procesamiento de webhooks de estado
  y de mensajes entrantes.
- **`emisor_webhooks.py`** — notifica por HMAC al sistema que solicitó cada
  envío (cambios de estado y respuestas de botón).
- **`autenticacion.py`** — decorador que exige
  `Authorization: ApiKey ...` + `X-Contract-Version: 1`, igual que el
  contrato v1 de Consultorio Web (D2).
- **`errores.py`** — formato de error estándar (`code`, `message`,
  `request_id`, `field_errors` opcional), mismo formato que
  `docs/CONTRATO_API_INTERA_CONSULTORIO_V1.md`.
- **`views.py` / `urls.py`** — los 3 endpoints del contrato más el webhook
  de Meta, montados en `config/urls.py` bajo `api/mensajeria/v1/`:
  - `POST /api/mensajeria/v1/envios/`
  - `GET /api/mensajeria/v1/envios/<envio_id>/`
  - `POST /api/mensajeria/v1/bajas/`
  - `GET|POST /api/mensajeria/v1/webhook-meta/` (no está en la tabla del
    contrato — la ruta del webhook de Meta no venía especificada; se eligió
    este nombre, cambiarlo es un `path()` si hace falta otro).
- **`admin.py`** — visibilidad de `Envio`/`Baja`/`SistemaSuscrito` en
  `/admin/`.
- **`tests.py`** — las 4 pruebas obligatorias de la sección 9 del contrato
  (plantilla con formato correcto, idempotencia, baja sin llamar a Meta,
  webhook de botón), más autenticación y los errores de validación. Todas
  mockean `meta_client.requests.post`: verifican la lógica de la pasarela,
  no la integración real con Meta.
- **`config/settings.py`** — variables nuevas (ver tabla abajo) y
  `INSTALLED_APPS`.

## Decisiones de diseño no obvias (para no repetir la discusión después)

- **`GenericForeignKey` es de cortesía, no la fuente de verdad.** El
  contrato (D1) dice que `Envio` referencia al destinatario con
  `GenericForeignKey`, calcado de
  `apps/core/auditoria/models.py::RegistroAuditoria`. Pero un
  `GenericForeignKey` de Django solo puede apuntar a un modelo *de este
  mismo proyecto* — funciona para `crm_ventas.Prospecto` (cuando exista,
  porque va a vivir en este mismo repo), pero **no puede funcionar** para
  un `Paciente` de ConsultorioWeb o un alumno de Academia: son modelos de
  otro servicio, sin `ContentType` posible aquí. Por eso `origen_sistema` /
  `origen_entidad` / `origen_id` (texto plano, tal cual llega en el
  payload) son los campos que siempre están presentes y consultables —
  `content_type`/`object_id` quedan nulos salvo que el origen sea local.
- **`fuera_de_ventana` está implementado pero hoy nunca dispara — y así
  debe quedarse (cerrado 2026-09-10).** Cita literal del contrato (antes
  solo se tenía parafraseado):
  > D4: "...fuera de la ventana solo deja pasar plantillas aprobadas..."
  > D5: "...no se admite texto libre por la API."
  Leídas juntas, D4 no es una regla de negocio adicional por implementar:
  es la justificación de D5. En la plataforma de Meta, la ventana de 24h
  solo restringe mensajes de sesión/texto libre — una plantilla aprobada
  se manda a cualquier hora. D4 describe ese comportamiento de la
  plataforma como el motivo de que la pasarela nunca admita texto libre
  (D5); no describe una restricción distinta que falte. Como D5 ya
  garantiza "solo plantillas aprobadas" de forma incondicional (no solo
  fuera de ventana), no hay nada adicional que `dentro_de_ventana` deba
  bloquear. Se deja la tabla `UltimaInteraccion` construida y
  actualizándose en cada webhook entrante (sirve para trazabilidad y para
  una eventual función futura), y `servicios.dentro_de_ventana` sigue
  devolviendo `True` siempre, con un comentario que documenta esta
  lectura de D4+D5 en vez de dejarlo como pregunta abierta.
- **El HMAC del webhook saliente ahora sí copia el patrón real de
  orbita-saas (resuelto 2026-09-10).** El repo `orbita-saas`
  (`raltsito/orbita-saas`, checkout local en
  `Downloads/ORBITA/ORBITAACADEMY/PlataformaSAAS`) sí estaba disponible —
  no en este repo, pero sí en la máquina. Su verificación de webhooks de
  Zoom (`lib/zoom-webhook.ts`) firma `v0:{timestamp}:{cuerpo}` con
  HMAC-SHA256 y manda el resultado como `v0=<hex>` en la cabecera de firma,
  más el timestamp en una cabecera aparte (`x-zm-request-timestamp`), y
  compara en tiempo constante. `emisor_webhooks.py::notificar` ahora sigue
  el mismo patrón: `X-Mensajeria-Signature: v0=<hex hmac-sha256 de
  "v0:{timestamp}:{cuerpo}">` y `X-Mensajeria-Timestamp: <timestamp>`. Un
  consumidor debe recalcular la firma con esas dos cabeceras más su
  `webhook_hmac_secret` y comparar con `hmac.compare_digest` (o
  equivalente). Las 10 pruebas de `apps/mensajeria/tests.py` siguen en
  verde — ninguna verificaba el formato exacto de la cabecera.
- **Catálogo de plantillas en `settings.MENSAJERIA_PLANTILLAS`, no en base
  de datos.** Es un diccionario en `config/settings.py` (nombre → variables
  requeridas + idiomas). Coherente con D5 ("si hace falta un mensaje nuevo,
  se da de alta una plantilla nueva"): dar de alta una plantilla hoy es un
  cambio de código + deploy, no una pantalla de administración. Si el
  volumen de plantillas crece, vale la pena moverlo a un modelo con
  Django admin — no se hizo ahora para no adelantarse a una necesidad que
  no existe todavía.
- **Sin DRF.** El proyecto no tiene Django REST Framework instalado
  (`config/settings.py`) y todas las integraciones existentes
  (`certificacion_intera/consultorio_web.py`,
  `finanzas/integraciones/consultorioweb.py`) son vistas JSON a mano sobre
  `urllib`/`requests`. `apps/mensajeria` sigue el mismo patrón por
  consistencia con el resto del repo.
- **`envio_id` es `env_<uuid4 hex>`**, no un ULID como sugiere el ejemplo
  del contrato (`env_01J9…`). Un ULID ordenable por tiempo es una mejora
  cosmética, no funcional — se puede migrar después sin romper el
  contrato (el campo sigue siendo un string opaco para quien lo consume).

## Variables de entorno nuevas

| Variable | Local | Producción (Railway) |
|---|---|---|
| `MENSAJERIA_WHATSAPP_TOKEN` | Token de un número de prueba de Meta (WhatsApp Business Platform, sandbox) | Token del número real del negocio |
| `MENSAJERIA_WHATSAPP_PHONE_NUMBER_ID` | ID del número de prueba | ID del número real |
| `MENSAJERIA_WHATSAPP_API_VERSION` | `v21.0` (default, no hace falta fijarla) | igual |
| `MENSAJERIA_WEBHOOK_VERIFY_TOKEN` | cualquier cadena, usada en el handshake local | valor fijado en Meta Business Manager |
| `MENSAJERIA_WEBHOOK_APP_SECRET` | App Secret de la app de prueba en Meta | App Secret de la app real |

Ninguna tiene default "funcional" a propósito (mismo criterio que
`CONSULTORIOWEB_*`: si falta en Railway, debe fallar ruidoso, no enviar
mensajes con credenciales vacías). En local, sin configurarlas, los tests
igual pasan porque mockean `meta_client`; solo hace falta configurarlas de
verdad para probar contra la API real de Meta.

Las credenciales de los sistemas que consumen la pasarela (`Authorization:
ApiKey`) y sus webhooks de salida no son variables de entorno — son filas
de `SistemaSuscrito` en la base de datos (usar `/admin/` o una migración de
datos, igual que los grupos de `apps/core/permisos/grupos.py`).

## Conflicto de webhook con ConsultorioWeb (2026-09-09)

Al preparar el guion de pruebas de humo salió un punto de arquitectura no
anticipado: **el webhook de WhatsApp de Meta solo puede apuntar a una URL
por App**, y ConsultorioWeb ya tiene registrado el suyo
(`clinica/views.py::whatsapp_webhook`) para el mismo número/App que se
iba a reutilizar en las pruebas. Registrar también el de
`apps/mensajeria` habría cortado los webhooks de ConsultorioWeb en
producción (estados de entrega y mensajes entrantes de la clínica).

Decisión (con el usuario, confirmada 2026-09-10): **el webhook de Meta
sigue apuntando siempre a ConsultorioWeb; se comparte por relay, no se
mueve.** ConsultorioWeb sigue siendo la única URL registrada en Meta
Business Manager. Implementado:

- **`ConsultorioWeb/core/settings.py`** — nueva variable
  `MENSAJERIA_WEBHOOK_RELAY_URL` (vacía por default; sin configurar, este
  servicio se comporta exactamente igual que antes).
- **`ConsultorioWeb/clinica/views.py::whatsapp_webhook`** — al final del
  procesamiento normal del POST, si `MENSAJERIA_WEBHOOK_RELAY_URL` está
  configurada, reenvía una copia del cuerpo crudo tal cual (misma
  `X-Hub-Signature-256` que mandó Meta, sin volver a firmar nada) a esa
  URL vía `_relay_webhook_a_mensajeria`. Best-effort: un fallo del relay
  (timeout, 500 del otro lado) se registra en log y no afecta el 200 que
  ConsultorioWeb le devuelve a Meta ni su propio procesamiento.
- **`apps/mensajeria/views.py::webhook_meta_view`** no cambió — ya
  validaba `X-Hub-Signature-256` contra `MENSAJERIA_WEBHOOK_APP_SECRET`,
  así que un POST relayado se procesa exactamente igual que uno directo de
  Meta, siempre que `MENSAJERIA_WEBHOOK_APP_SECRET` en portal_grupointra
  esté configurado con **el mismo App Secret de Meta que usa
  ConsultorioWeb** para ese número (es el mismo App/número compartido, no
  una app nueva) — pendiente de setear esa variable en Railway antes de
  activar el relay en producción.
- El handshake GET de Meta (`hub.mode=subscribe`) no se relaya —  sigue
  pasando solo por ConsultorioWeb, como ya pasa hoy; `apps/mensajeria`
  nunca necesita responderlo porque no es la URL registrada.

Consecuencia para el guion de pruebas de humo: en cuanto
`MENSAJERIA_WEBHOOK_RELAY_URL` esté configurada en producción, P1 (estado
que avanza a `enviado`/`entregado`) y P4 (webhook de vuelta / botones) ya
no dependen de un segundo número — se prueban completas contra el mismo
webhook que ya usa ConsultorioWeb.

## Ajustes por el guion de pruebas de humo (paso 08, 2026-09-09)

El equipo entregó un guion de 4 pruebas contra la pasarela ya desplegada
(`docs`/raíz: guion de pruebas, no versionado aquí por traer números de
teléfono y nombres de plantillas de negocio). Corriéndolo contra el código
tal como quedó el 2026-09-08 aparecieron dos huecos, ya corregidos:

- **`MENSAJERIA_PLANTILLAS` solo tenía `intra_recordatorio_cita_v1`.** El
  guion prueba tres plantillas reales del negocio
  (`intra_recordatorio_cita_v1`, `intra_cotizacion_enviada_v1` con adjunto,
  `intra_seguimiento_cotizacion_v1`). Se agregaron las otras dos al
  catálogo en `config/settings.py` con las variables que usa el guion.
  Falta que alguien confirme contra Meta Business Manager que el número y
  nombre de variables coincide exactamente con lo aprobado — el catálogo
  de este archivo es la fuente de verdad del lado del código, pero no
  valida contra Meta.
- **Un envío bloqueado (baja o fuera de ventana) devolvía un 200 de éxito
  con `"estado": "bloqueado"`, sin `code`.** La prueba P3 exige que la
  respuesta traiga el código `destinatario_dado_de_baja` en el formato de
  error estándar de la sección 7 — el mismo criterio que ya se sigue para
  `plantilla_desconocida` o `variables_incompletas`. Se corrigió: ahora un
  envío bloqueado sigue quedando registrado en `Envio` con
  `estado=bloqueado` y su `motivo_bloqueo` (auditoría), pero la respuesta
  HTTP es un error 422 con `{"code": "destinatario_dado_de_baja", ...}`
  igual que cualquier otro error de negocio. Un reintento con la misma
  `Idempotency-Key` de un envío ya bloqueado repite el mismo error sin
  volver a evaluar nada (coherente con D3).

## Pendiente

1. **Conectar `crm_ventas`** (Fase 2 del plan) — pospuesto a propósito
   hasta que esa app exista (decisión confirmada 2026-09-10): modificar
   `crm_ventas/views/mensajeria.py` para llamar a
   `apps.mensajeria.servicios.crear_envio(...)` en vez de simular, y
   `crm_ventas/models.py::MensajeWhatsApp` para apuntar al `Envio` de la
   pasarela en lugar de guardar su propio estado de entrega. Dar de alta el
   `SistemaSuscrito` de `crm_ventas` (API key + webhook) antes de conectar.
2. ~~**Verificar la firma HMAC de salida contra orbita-saas**~~ —
   **Resuelto el 2026-09-10.** Ver la decisión de diseño arriba: se
   encontró el checkout local de `orbita-saas` y se copió su patrón real
   (`v0=` + HMAC-SHA256 de `v0:{timestamp}:{cuerpo}`, timestamp en cabecera
   aparte). `emisor_webhooks.py` actualizado, 10 pruebas en verde.
3. ~~**Resolver la duda de `fuera_de_ventana`**~~ — **Cerrado el
   2026-09-10** (ver decisión arriba, con la cita literal de D4/D5): no
   hacía falta al equipo, hacía falta el texto exacto del contrato. Sin
   contradicción real entre D4 y D5, no hay regla adicional que activar;
   el comportamiento actual (nunca bloquea por este motivo) es correcto.
4. **Probar las 4 pruebas de la sección 9 contra la API real de Meta**
   — en curso el 2026-09-10, dos hallazgos ya resueltos/documentados:
   - **No hacía falta una sandbox separada.** `apps/mensajeria` ya está
     configurada con las credenciales reales de producción (mismo
     WABA/número que ConsultorioWeb, ver punto 5). Se creó un
     `SistemaSuscrito` de prueba en producción (`nombre='prueba_humo'`,
     vía `railway ssh` + `manage.py shell`, con el consentimiento
     explícito de Carlos) para autenticar las llamadas de prueba.
   - **Bug real encontrado y corregido: un rechazo de Meta al mandar la
     plantilla (4xx, ej. plantilla desconocida) tumbaba la vista con un
     500 en vez de responder con el formato de error del contrato.**
     `meta_client.enviar_plantilla` solo envolvía en `ErrorPasarela` el
     caso de "Meta no respondió" (timeout/5xx, código
     `proveedor_no_disponible`, 502, marcado como reintentable); el caso
     de "Meta respondió pero rechazó la solicitud" (4xx) lanzaba
     `MetaError`, una excepción plana que nada atrapaba. Corregido: ahora
     también es `ErrorPasarela` con código nuevo `rechazado_por_meta`
     (502) — mismo status que `proveedor_no_disponible` porque sigue
     siendo un problema del proveedor, pero **no es seguro reintentar con
     la misma Idempotency-Key** (Meta va a rechazar la misma solicitud
     otra vez; hace falta corregir la plantilla/variables, no reintentar).
     10 pruebas en verde después del cambio (ninguna cubría este camino
     antes).
   - **Gap encontrado pero NO corregido a propósito (fuera de alcance de
     hoy):** cuando `_despachar` falla (cualquiera de los dos códigos de
     arriba), el `Envio` ya creado se queda en `estado=encolado` para
     siempre — nada en `crear_envio` lo actualiza tras el error. Peor
     aún: un reintento con la misma Idempotency-Key **no vuelve a llamar
     a Meta**, `crear_envio` solo revisa si el envío existente está
     `BLOQUEADO`; si sigue en `encolado`, lo regresa tal cual sin
     reintentar el despacho. Esto contradice el mensaje de
     `proveedor_no_disponible` ("puedes reintentar con la misma
     Idempotency-Key"). Arreglarlo bien implica decidir cómo reintentar
     el despacho de forma segura (reentrada, condición de carrera si dos
     reintentos llegan a la vez) — no es un cambio de dos líneas, queda
     como punto nuevo, no como parte de esta sesión.
   - **Hallazgo de negocio, ya verificado contra la API real de Meta (no
     contra memoria de nadie): de las 3 plantillas del catálogo, 2 están
     aprobadas y 1 nunca se creó.** Primer intento real con
     `intra_recordatorio_cita_v1` rechazado (`132001, la plantilla no
     existe en es_MX`). Se confirmó contra
     `GET /{waba_id}/message_templates` (con el `MENSAJERIA_WHATSAPP_TOKEN`
     ya configurado):
     | Plantilla | Estado real en Meta |
     |---|---|
     | `intra_cotizacion_enviada_v1` | **APROBADA** (UTILITY, es_MX) |
     | `intra_seguimiento_cotizacion_v1` | **APROBADA** (MARKETING, es_MX) |
     | `intra_recordatorio_cita_v1` | **no existe** -- nunca se dio de alta |
     Lo que sí existe para recordatorios es la plantilla vieja que ya usa
     ConsultorioWeb (`recordatorio_cita_3_dias` / `_5_dias`,
     `confirmacion_cita_1_dia`, `encuesta_conformidad`,
     `reactivacion_paciente`, `clinica/services_whatsapp.py`), con una
     estructura de variables distinta (6, no 4) a la que asume el
     contrato para `intra_recordatorio_cita_v1`. El contenido exacto de
     `intra_cotizacion_enviada_v1`/`intra_seguimiento_cotizacion_v1` venía
     de un mensaje del hermano de Carlos (parte de un "mapa de
     articulación" externo a este repo, paso 06 = capturar y mandar a
     revisión en Meta) -- confirmado que sí se completó ese paso para
     esas dos, no para la de recordatorio.
   - **Dos incompatibilidades nuevas entre el código y la forma real en
     que quedaron aprobadas estas plantillas (encontradas probando
     `intra_seguimiento_cotizacion_v1` en vivo, P1 parcial):**
     1. El header de `intra_cotizacion_enviada_v1` quedó aprobado como
        **texto estático** ("Documento (el PDF de la cotización)"), no
        como header de tipo documento con variable. `meta_client.py`
        arma siempre un header de adjunto (documento/imagen/video) con
        `link` cuando llega `adjunto` en el payload -- con esta
        plantilla real eso manda un componente que la plantilla no
        espera (rechazo por desajuste de componentes). No probado en
        vivo todavía a propósito, para no gastar otro envío real que ya
        se sabe que va a fallar.
     2. `intra_seguimiento_cotizacion_v1` trae un componente
        `CALL_PERMISSION_REQUEST` (probablemente el botón "Agendar
        llamada" del diseño original). Probado en vivo: Meta lo rechazó
        con `(#138000) Calling API not enabled` -- el número no tiene la
        función de llamadas de WhatsApp habilitada en WhatsApp Manager.
        Es configuración de la cuenta de Meta, no un bug de código; el
        fix del 500 de arriba sí funcionó correctamente aquí (502 con
        formato de error del contrato, sin crash).
   - **Bloquea terminar P1 y correr P4 de la sección 9 hasta que Carlos
     decida, con su hermano si hace falta:**
     1. `intra_recordatorio_cita_v1`: ¿se da de alta y se manda a
        aprobación en Meta (falta esa plantilla, sección 1 del mensaje
        del hermano nunca se compartió completa), o `MENSAJERIA_PLANTILLAS`
        debe apuntar a la plantilla vieja ya aprobada (con su propia
        estructura de 6 variables, no 4)?
     2. `intra_cotizacion_enviada_v1`: ¿se re-sube la plantilla con un
        header de tipo documento de verdad, o el código deja de mandar
        un adjunto para esta plantilla en particular y el PDF se
        comparte de otra forma (link en el cuerpo, por ejemplo)?
     3. `intra_seguimiento_cotizacion_v1`: ¿se habilita la función de
        llamadas de WhatsApp para este número en WhatsApp Manager, o se
        vuelve a subir la plantilla sin el componente
        `CALL_PERMISSION_REQUEST`?
     P2 (idempotencia) y P3 (bajas) no llaman a Meta y sí se pueden
     correr sin resolver nada de esto primero.
5. ~~**Webhook único compartido con ConsultorioWeb**~~ — **Resuelto y
   verificado en producción el 2026-09-10.** Relay implementado, ambas
   variables configuradas en Railway (`MENSAJERIA_WEBHOOK_RELAY_URL` en
   `SistemaIntra`/`web`; `MENSAJERIA_WEBHOOK_APP_SECRET`,
   `MENSAJERIA_WHATSAPP_TOKEN` y `MENSAJERIA_WHATSAPP_PHONE_NUMBER_ID` en
   `CentralizacionIntra`, estas dos últimas espejo de las de ConsultorioWeb
   porque es el mismo WABA/número) y ambos servicios redesplegados con el
   código correspondiente. Probado con un POST firmado (payload vacío,
   `entry: [{changes: [{value: {}}]}]`) contra
   `https://www.agenda.intra.org.mx/api/whatsapp/webhook/`: el log HTTP de
   `apps/mensajeria` en Railway confirma `POST
   /api/mensajeria/v1/webhook-meta/ 200` en el mismo instante — el relay
   funciona de punta a punta. Sigue pendiente la prueba con un webhook real
   de Meta (esta solo confirma el mecanismo, no un evento real de la API).
6. ~~**Arranque en frío de ConsultorioWeb / INTRA v0.8 en Railway**~~ —
   **Resuelto el 2026-09-08.** Se desactivó el sueño del servicio (`web`,
   proyecto Railway `SistemaIntra`, ambiente `production`):
   `sleep_application: false`. El contenedor ya no se duerme a los 10 min
   de inactividad, así que deja de haber arranque en frío para el primer
   envío del día. Cambio de configuración de plataforma, sin tocar código
   ni redeploy. Costo: el servicio ahora mantiene el recurso mínimo
   asignado 24/7 en vez de liberarlo cuando no hay tráfico — vale la pena
   vigilar el consumo de Railway del proyecto `SistemaIntra` los próximos
   días para confirmar el impacto real en la factura.

## Cómo probar en local

```bash
python manage.py migrate
python manage.py test apps.mensajeria

# Crear un sistema suscrito de prueba:
python manage.py shell -c "
from apps.mensajeria.models import SistemaSuscrito
SistemaSuscrito.objects.get_or_create(nombre='crm_ventas', defaults={'api_key': 'clave-local-de-prueba'})
"
```

Para probar el webhook entrante de Meta contra `runserver` hace falta una
URL pública (`ngrok`/`cloudflared`) apuntando a
`/api/mensajeria/v1/webhook-meta/`, registrada en Meta Business Manager
con `MENSAJERIA_WEBHOOK_VERIFY_TOKEN`.
