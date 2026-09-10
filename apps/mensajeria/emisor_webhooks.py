import hashlib
import hmac
import json
import logging
import time

import requests

from .models import SistemaSuscrito

logger = logging.getLogger(__name__)


def _firmar(secreto, timestamp, cuerpo_bytes):
    mensaje = b'v0:' + str(timestamp).encode('ascii') + b':' + cuerpo_bytes
    return 'v0=' + hmac.new(secreto.encode('utf-8'), mensaje, hashlib.sha256).hexdigest()


def notificar(sistema_nombre, evento, payload):
    """Avisa al sistema que solicitó un envío -- la pasarela avisa, no al
    revés (sección 6). Firma con HMAC en la cabecera, mismo patrón que
    orbita-saas usa de verdad para verificar los webhooks de Zoom
    (`lib/zoom-webhook.ts` de ese repo: `X-<Nombre>-Signature: v0=` + hex
    HMAC-SHA256 de `v0:{timestamp}:{cuerpo}`, más un timestamp aparte para
    que el mensaje firmado no sea replayable). Confirmado contra ese código
    el 2026-09-10 -- ya no es una suposición. Un consumidor debe: tomar
    `X-Mensajeria-Timestamp`, recalcular `v0:{timestamp}:{cuerpo_crudo}` con
    su `webhook_hmac_secret`, y comparar en tiempo constante contra
    `X-Mensajeria-Signature`."""

    sistema = SistemaSuscrito.objects.filter(
        nombre=sistema_nombre, activo=True,
    ).exclude(webhook_url='').first()
    if sistema is None:
        logger.info('No hay webhook configurado para %s; no se notifica %s.', sistema_nombre, evento)
        return

    cuerpo = json.dumps({'evento': evento, 'data': payload}, sort_keys=True).encode('utf-8')
    timestamp = int(time.time())
    firma = _firmar(sistema.webhook_hmac_secret, timestamp, cuerpo)

    try:
        requests.post(
            sistema.webhook_url,
            data=cuerpo,
            headers={
                'Content-Type': 'application/json',
                'X-Mensajeria-Signature': firma,
                'X-Mensajeria-Timestamp': str(timestamp),
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        # Un webhook saliente que falla no debe tumbar el procesamiento del
        # webhook entrante de Meta que lo disparó -- se registra y ya. Si
        # hace falta garantizar entrega, la siguiente iteración debe agregar
        # cola con reintentos, no bloquear aquí.
        logger.warning('No se pudo notificar a %s (%s): %s', sistema_nombre, evento, exc)
