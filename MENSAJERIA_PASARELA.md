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
- **`fuera_de_ventana` está implementado pero hoy nunca dispara.** D4 dice
  que fuera de la ventana de 24h "solo dejan pasar plantillas aprobadas".
  D5 dice que la pasarela *solo* manda plantillas aprobadas, nunca texto
  libre. En la API real de Meta, una plantilla aprobada se puede enviar a
  cualquier hora — la ventana de 24h solo limita mensajes de
  sesión/texto libre. Con D5 vigente, ese código de error queda sin caso
  de uso real. Se dejó la tabla `UltimaInteraccion` construida y
  actualizándose en cada webhook entrante, y `servicios.dentro_de_ventana`
  siempre devuelve `True` con un comentario explicando por qué. **Pendiente
  de confirmar con quien escribió el contrato**: si la intención era otra
  regla (por ejemplo, limitar la categoría de plantilla fuera de ventana),
  hay que ajustar esa función — hoy no bloquea nada por este motivo.
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
3. **Resolver con el equipo la duda de `fuera_de_ventana`** — sigue
   pendiente, es una decisión de negocio que no se puede tomar por código
   (ver decisión arriba: hoy el código está listo para cualquiera de las
   dos respuestas, pero no se activó ninguna regla real).
4. **Probar las 4 pruebas de la sección 9 contra la API real de Meta**, con
   un número propio y credenciales de sandbox, antes de conectar cualquier
   proceso real — las pruebas automatizadas (`apps/mensajeria/tests.py`)
   cubren la lógica interna, no la integración real. Sigue pendiente de
   que Carlos tenga a la mano las credenciales de sandbox.
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
