import hashlib
import hmac
import logging

import requests
from django.conf import settings

from .errores import ErrorPasarela, PROVEEDOR_NO_DISPONIBLE

logger = logging.getLogger(__name__)


class MetaError(Exception):
    pass


def _base_url():
    version = settings.MENSAJERIA_WHATSAPP_API_VERSION
    phone_id = settings.MENSAJERIA_WHATSAPP_PHONE_NUMBER_ID
    return f'https://graph.facebook.com/{version}/{phone_id}'


def enviar_plantilla(destinatario, plantilla, idioma, variables, adjunto=None):
    """Llama a la API de Meta para mandar un mensaje de plantilla. No arma
    texto ni decide contenido (D5): solo empaqueta lo que ya llegó validado
    por `servicios.py`.

    Devuelve el `wa_message_id` de Meta. Lanza `ErrorPasarela` con código
    `proveedor_no_disponible` si Meta no respondió -- ese código es
    explícitamente reintentable con la misma Idempotency-Key (sección 7)."""

    parametros = [
        {'type': 'text', 'text': str(valor)}
        for _, valor in sorted(variables.items(), key=lambda item: int(item[0]))
    ]
    componentes = [{'type': 'body', 'parameters': parametros}] if parametros else []

    if adjunto:
        tipo = adjunto.get('tipo')
        campo_meta = {'documento': 'document', 'imagen': 'image', 'video': 'video'}.get(tipo, 'document')
        componentes.insert(0, {
            'type': 'header',
            'parameters': [{
                'type': campo_meta,
                campo_meta: {
                    'link': adjunto['url'],
                    **({'filename': adjunto['nombre']} if adjunto.get('nombre') else {}),
                },
            }],
        })

    cuerpo = {
        'messaging_product': 'whatsapp',
        'to': destinatario,
        'type': 'template',
        'template': {
            'name': plantilla,
            'language': {'code': idioma},
            'components': componentes,
        },
    }

    try:
        respuesta = requests.post(
            f'{_base_url()}/messages',
            json=cuerpo,
            headers={'Authorization': f'Bearer {settings.MENSAJERIA_WHATSAPP_TOKEN}'},
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.warning('Meta no respondió al enviar plantilla %s a %s: %s', plantilla, destinatario, exc)
        raise ErrorPasarela(
            PROVEEDOR_NO_DISPONIBLE,
            'Meta no respondió. Puedes reintentar con la misma Idempotency-Key.',
            status=502,
        ) from exc

    if respuesta.status_code >= 500:
        raise ErrorPasarela(
            PROVEEDOR_NO_DISPONIBLE,
            'Meta no respondió. Puedes reintentar con la misma Idempotency-Key.',
            status=502,
        )

    if respuesta.status_code >= 400:
        raise MetaError(f'Meta rechazó el envío ({respuesta.status_code}): {respuesta.text}')

    datos = respuesta.json()
    return datos['messages'][0]['id']


def verificar_firma_webhook(cuerpo_crudo, firma_recibida):
    """Valida `X-Hub-Signature-256`, la firma que Meta manda en cada webhook
    (HMAC-SHA256 con el App Secret). No es el mismo secreto que usamos para
    firmar los webhooks salientes hacia los sistemas suscritos -- ver
    `emisor_webhooks.py`."""

    if not firma_recibida or not firma_recibida.startswith('sha256='):
        return False
    esperada = hmac.new(
        settings.MENSAJERIA_WEBHOOK_APP_SECRET.encode('utf-8'),
        cuerpo_crudo,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f'sha256={esperada}', firma_recibida)
