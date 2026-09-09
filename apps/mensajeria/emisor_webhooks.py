import hashlib
import hmac
import json
import logging

import requests

from .models import SistemaSuscrito

logger = logging.getLogger(__name__)


def _firmar(secreto, cuerpo_bytes):
    return hmac.new(secreto.encode('utf-8'), cuerpo_bytes, hashlib.sha256).hexdigest()


def notificar(sistema_nombre, evento, payload):
    """Avisa al sistema que solicitó un envío -- la pasarela avisa, no al
    revés (sección 6). Firma con HMAC en la cabecera, mismo patrón que
    orbita-saas ya usa para los webhooks de Zoom (ver README de esta app:
    no se tuvo acceso al código de orbita-saas para copiar el formato
    exacto, así que esta firma sigue la convención más común de la industria
    -- `X-Mensajeria-Signature: sha256=<hmac>` -- y debe revisarse contra la
    implementación real antes de conectar un consumidor de producción)."""

    sistema = SistemaSuscrito.objects.filter(
        nombre=sistema_nombre, activo=True,
    ).exclude(webhook_url='').first()
    if sistema is None:
        logger.info('No hay webhook configurado para %s; no se notifica %s.', sistema_nombre, evento)
        return

    cuerpo = json.dumps({'evento': evento, 'data': payload}, sort_keys=True).encode('utf-8')
    firma = _firmar(sistema.webhook_hmac_secret, cuerpo)

    try:
        requests.post(
            sistema.webhook_url,
            data=cuerpo,
            headers={
                'Content-Type': 'application/json',
                'X-Mensajeria-Signature': f'sha256={firma}',
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        # Un webhook saliente que falla no debe tumbar el procesamiento del
        # webhook entrante de Meta que lo disparó -- se registra y ya. Si
        # hace falta garantizar entrega, la siguiente iteración debe agregar
        # cola con reintentos, no bloquear aquí.
        logger.warning('No se pudo notificar a %s (%s): %s', sistema_nombre, evento, exc)
