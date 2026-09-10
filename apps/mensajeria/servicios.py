import re

from django.conf import settings
from django.utils import timezone

from . import emisor_webhooks, meta_client
from .errores import (
    ADJUNTO_NO_SOPORTADO,
    DESTINATARIO_DADO_DE_BAJA,
    DESTINATARIO_INVALIDO,
    ErrorPasarela,
    IDEMPOTENCIA_EN_CONFLICTO,
    PLANTILLA_DESCONOCIDA,
    VARIABLES_INCOMPLETAS,
)
from .models import Baja, Envio, UltimaInteraccion, huella_de

E164 = re.compile(r'^\+[1-9]\d{7,14}$')


def normalizar_destinatario(valor):
    """La pasarela normaliza y rechaza lo que no puede normalizar; no
    adivina (sección 4). Hoy solo exige el formato E.164 ya explícito en el
    payload -- no intenta inferir lada de país de números sin `+`, porque
    adivinar mal manda el mensaje a la persona equivocada."""
    valor = (valor or '').strip()
    if not E164.match(valor):
        raise ErrorPasarela(
            DESTINATARIO_INVALIDO,
            'El destinatario debe venir en formato E.164, por ejemplo +528442896091.',
        )
    return valor


def validar_plantilla(nombre, idioma, variables, adjunto=None):
    catalogo = settings.MENSAJERIA_PLANTILLAS.get(nombre)
    if catalogo is None:
        raise ErrorPasarela(PLANTILLA_DESCONOCIDA, f'La plantilla "{nombre}" no existe o no está aprobada.')

    if idioma not in catalogo['idiomas']:
        raise ErrorPasarela(
            PLANTILLA_DESCONOCIDA,
            f'La plantilla "{nombre}" no está aprobada en el idioma "{idioma}".',
        )

    faltantes = [clave for clave in catalogo['variables'] if clave not in variables]
    if faltantes:
        raise ErrorPasarela(
            VARIABLES_INCOMPLETAS,
            f'Faltan variables requeridas por la plantilla: {", ".join(faltantes)}.',
        )

    if adjunto and not catalogo.get('admite_adjunto', False):
        # No es que Meta lo vaya a rechazar -- es que el header de esta
        # plantilla, tal como quedó aprobada, no tiene un parámetro de
        # documento/imagen/video que llenar (ver el comentario del
        # catálogo en settings.py). Mejor fallar aquí con un error claro
        # que armar un componente que Meta va a rechazar por desajuste.
        raise ErrorPasarela(
            ADJUNTO_NO_SOPORTADO,
            f'La plantilla "{nombre}" no tiene un header de adjunto aprobado en Meta.',
        )


def dentro_de_ventana(destinatario):
    """D4 dice que fuera de la ventana de 24h solo pasan plantillas
    aprobadas. Como D5 prohíbe que esta API mande otra cosa que no sea una
    plantilla aprobada, y Meta permite enviar plantillas aprobadas a
    cualquier hora (la ventana de 24h en la API de Meta solo limita mensajes
    de sesión/texto libre), esta función hoy siempre deja pasar el envío.
    Se deja implementada -- y `UltimaInteraccion` se sigue actualizando en
    cada webhook entrante -- para el día en que se agregue un modo de
    mensaje de sesión; ver MENSAJERIA_PASARELA.md (decisión cerrada
    2026-09-10, con la cita literal de D4/D5 del contrato)."""
    return True


MENSAJES_DE_BLOQUEO = {
    DESTINATARIO_DADO_DE_BAJA: 'La persona pidió no recibir mensajes.',
    'fuera_de_ventana': 'Sin plantilla válida y sin ventana de 24 horas abierta.',
}


def crear_envio(payload, sistema):
    idempotency_key = payload.get('idempotency_key_header')
    cuerpo = payload['cuerpo']

    existente = Envio.objects.filter(idempotency_key=idempotency_key).first()
    if existente is not None:
        if existente.huella_payload != huella_de(cuerpo):
            raise ErrorPasarela(
                IDEMPOTENCIA_EN_CONFLICTO,
                'Esa Idempotency-Key ya se usó con un contenido distinto.',
                status=409,
            )
        if existente.estado == Envio.Estado.BLOQUEADO:
            # Reintento con la misma Idempotency-Key de un envío que ya
            # estaba bloqueado (D3): se repite el mismo error, no se vuelve
            # a evaluar nada.
            raise ErrorPasarela(
                existente.motivo_bloqueo,
                MENSAJES_DE_BLOQUEO.get(existente.motivo_bloqueo, 'Envío bloqueado.'),
                status=422,
            )
        return existente

    destinatario = normalizar_destinatario(cuerpo.get('destinatario'))

    if Baja.objects.filter(destinatario=destinatario).exists():
        _registrar_bloqueado(destinatario, cuerpo, idempotency_key, DESTINATARIO_DADO_DE_BAJA)
        raise ErrorPasarela(DESTINATARIO_DADO_DE_BAJA, MENSAJES_DE_BLOQUEO[DESTINATARIO_DADO_DE_BAJA], status=422)

    plantilla = cuerpo.get('plantilla', '')
    idioma = cuerpo.get('idioma', 'es_MX')
    variables = cuerpo.get('variables', {})
    validar_plantilla(plantilla, idioma, variables, cuerpo.get('adjunto'))

    if not dentro_de_ventana(destinatario):
        _registrar_bloqueado(destinatario, cuerpo, idempotency_key, 'fuera_de_ventana')
        raise ErrorPasarela('fuera_de_ventana', MENSAJES_DE_BLOQUEO['fuera_de_ventana'], status=422)

    origen = cuerpo.get('origen', {})
    envio = Envio.objects.create(
        destinatario=destinatario,
        plantilla=plantilla,
        idioma=idioma,
        variables=variables,
        adjunto=cuerpo.get('adjunto'),
        enviar_despues_de=cuerpo.get('enviar_despues_de') or None,
        origen_sistema=origen.get('sistema', sistema.nombre),
        origen_entidad=origen.get('entidad', ''),
        origen_id=str(origen.get('id', '')),
        idempotency_key=idempotency_key,
        huella_payload=huella_de(cuerpo),
    )

    if envio.enviar_despues_de and envio.enviar_despues_de > timezone.now():
        return envio

    _despachar(envio)
    return envio


def _registrar_bloqueado(destinatario, cuerpo, idempotency_key, motivo):
    origen = cuerpo.get('origen', {})
    return Envio.objects.create(
        destinatario=destinatario,
        plantilla=cuerpo.get('plantilla', ''),
        idioma=cuerpo.get('idioma', 'es_MX'),
        variables=cuerpo.get('variables', {}),
        origen_sistema=origen.get('sistema', ''),
        origen_entidad=origen.get('entidad', ''),
        origen_id=str(origen.get('id', '')),
        idempotency_key=idempotency_key,
        huella_payload=huella_de(cuerpo),
        estado=Envio.Estado.BLOQUEADO,
        motivo_bloqueo=motivo,
    )


def _despachar(envio):
    wa_message_id = meta_client.enviar_plantilla(
        envio.destinatario, envio.plantilla, envio.idioma, envio.variables, envio.adjunto,
    )
    envio.wa_message_id = wa_message_id
    envio.estado = Envio.Estado.ENVIADO
    envio.enviado_en = timezone.now()
    envio.save(update_fields=['wa_message_id', 'estado', 'enviado_en', 'actualizado_en'])


def registrar_baja(destinatario, sistema, motivo=''):
    destinatario = normalizar_destinatario(destinatario)
    baja, _creada = Baja.objects.get_or_create(
        destinatario=destinatario,
        defaults={'origen_sistema': sistema.nombre, 'motivo': motivo},
    )
    return baja


ESTADOS_META = {
    'sent': Envio.Estado.ENVIADO,
    'delivered': Envio.Estado.ENTREGADO,
    'read': Envio.Estado.LEIDO,
    'failed': Envio.Estado.FALLIDO,
}


def procesar_estado_entrante(wa_message_id, estado_meta, timestamp):
    """Actualiza un Envío a partir de un webhook de estado de Meta y avisa
    al sistema que lo solicitó (sección 6, caso 1)."""
    envio = Envio.objects.filter(wa_message_id=wa_message_id).first()
    if envio is None:
        return

    nuevo_estado = ESTADOS_META.get(estado_meta)
    if nuevo_estado is None:
        return

    envio.estado = nuevo_estado
    campo_fecha = {
        Envio.Estado.ENTREGADO: 'entregado_en',
        Envio.Estado.LEIDO: 'leido_en',
    }.get(nuevo_estado)
    if campo_fecha:
        setattr(envio, campo_fecha, timestamp)
    envio.save()

    emisor_webhooks.notificar(envio.origen_sistema, 'cambio_estado', {
        'envio_id': envio.envio_id,
        'estado': envio.estado,
        'origen': {
            'sistema': envio.origen_sistema,
            'entidad': envio.origen_entidad,
            'id': envio.origen_id,
        },
    })


def procesar_mensaje_entrante(numero_remitente, timestamp, boton_id=None, texto=None):
    """Registra la última interacción (para la ventana de 24h) y, si es una
    respuesta a un botón de plantilla, avisa a quien solicitó el envío
    original (sección 6, caso 2) -- el caso que vuelve útiles los botones."""
    UltimaInteraccion.objects.update_or_create(
        destinatario=numero_remitente,
        defaults={'ultimo_mensaje_entrante_en': timestamp},
    )

    if boton_id is None:
        return

    ultimo_envio = Envio.objects.filter(
        destinatario=numero_remitente,
    ).exclude(origen_sistema='').order_by('-creado_en').first()
    if ultimo_envio is None:
        return

    emisor_webhooks.notificar(ultimo_envio.origen_sistema, 'respuesta_boton', {
        'envio_id': ultimo_envio.envio_id,
        'destinatario': numero_remitente,
        'boton_id': boton_id,
        'texto': texto,
        'origen': {
            'sistema': ultimo_envio.origen_sistema,
            'entidad': ultimo_envio.origen_entidad,
            'id': ultimo_envio.origen_id,
        },
    })
