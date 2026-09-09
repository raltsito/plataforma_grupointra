import json

from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from . import meta_client, servicios
from .autenticacion import requiere_sistema_autenticado
from .errores import (
    ENVIO_NO_ENCONTRADO,
    ErrorPasarela,
    JSON_INVALIDO,
    request_id_de,
    respuesta_de_error,
)
from .models import Envio
from django.conf import settings


def _cuerpo_json(request):
    try:
        return json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ErrorPasarela(JSON_INVALIDO.codigo, JSON_INVALIDO.mensaje, status=400)


@require_http_methods(['POST'])
@requiere_sistema_autenticado
def envios_view(request):
    request_id = request.request_id_mensajeria
    idempotency_key = request.headers.get('Idempotency-Key')
    if not idempotency_key:
        return respuesta_de_error(
            request_id,
            ErrorPasarela('idempotency_key_ausente', 'Falta la cabecera Idempotency-Key.', status=400),
        )

    try:
        cuerpo = _cuerpo_json(request)
        envio = servicios.crear_envio(
            {'cuerpo': cuerpo, 'idempotency_key_header': idempotency_key},
            request.sistema_mensajeria,
        )
    except ErrorPasarela as error:
        return respuesta_de_error(request_id, error)

    return JsonResponse({
        'envio_id': envio.envio_id,
        'estado': envio.estado,
        'wa_message_id': envio.wa_message_id or None,
        'creado_en': envio.creado_en.isoformat(),
    }, status=201)


@require_GET
@requiere_sistema_autenticado
def envio_detalle_view(request, envio_id):
    request_id = request.request_id_mensajeria
    envio = Envio.objects.filter(envio_id=envio_id).first()
    if envio is None:
        return respuesta_de_error(
            request_id,
            ErrorPasarela(ENVIO_NO_ENCONTRADO, 'No existe un envío con ese identificador.', status=404),
        )

    return JsonResponse({
        'envio_id': envio.envio_id,
        'estado': envio.estado,
        'motivo_bloqueo': envio.motivo_bloqueo or None,
        'wa_message_id': envio.wa_message_id or None,
        'creado_en': envio.creado_en.isoformat(),
        'enviado_en': envio.enviado_en.isoformat() if envio.enviado_en else None,
        'entregado_en': envio.entregado_en.isoformat() if envio.entregado_en else None,
        'leido_en': envio.leido_en.isoformat() if envio.leido_en else None,
    })


@require_http_methods(['POST'])
@requiere_sistema_autenticado
def bajas_view(request):
    request_id = request.request_id_mensajeria
    try:
        cuerpo = _cuerpo_json(request)
        baja = servicios.registrar_baja(
            cuerpo.get('destinatario'), request.sistema_mensajeria, cuerpo.get('motivo', ''),
        )
    except ErrorPasarela as error:
        return respuesta_de_error(request_id, error)

    return JsonResponse({'destinatario': baja.destinatario, 'creado_en': baja.creado_en.isoformat()}, status=201)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def webhook_meta_view(request):
    """Verificación de suscripción (GET) y eventos entrantes (POST) de Meta.
    No usa `requiere_sistema_autenticado`: quien llama es Meta, no un
    sistema suscrito -- se autentica con la firma HMAC del cuerpo, no con
    nuestro esquema de ApiKey."""

    if request.method == 'GET':
        if (
            request.GET.get('hub.mode') == 'subscribe'
            and request.GET.get('hub.verify_token') == settings.MENSAJERIA_WEBHOOK_VERIFY_TOKEN
        ):
            return HttpResponse(request.GET.get('hub.challenge', ''))
        return HttpResponseBadRequest('Token de verificación inválido.')

    firma = request.headers.get('X-Hub-Signature-256', '')
    if not meta_client.verificar_firma_webhook(request.body, firma):
        return HttpResponse(status=401)

    try:
        datos = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest('JSON inválido.')

    for entrada in datos.get('entry', []):
        for cambio in entrada.get('changes', []):
            valor = cambio.get('value', {})
            _procesar_valor_webhook(valor)

    return HttpResponse(status=200)


def _procesar_valor_webhook(valor):
    for estado in valor.get('statuses', []):
        timestamp = _epoch_a_datetime(estado.get('timestamp'))
        servicios.procesar_estado_entrante(estado.get('id'), estado.get('status'), timestamp)

    for mensaje in valor.get('messages', []):
        timestamp = _epoch_a_datetime(mensaje.get('timestamp'))
        remitente = mensaje.get('from')
        boton = mensaje.get('button')
        texto = mensaje.get('text', {}).get('body') if mensaje.get('type') == 'text' else None
        servicios.procesar_mensaje_entrante(
            remitente,
            timestamp,
            boton_id=boton.get('payload') if boton else None,
            texto=boton.get('text') if boton else texto,
        )


def _epoch_a_datetime(valor):
    if valor is None:
        return timezone.now()
    return timezone.datetime.fromtimestamp(int(valor), tz=timezone.get_current_timezone())
