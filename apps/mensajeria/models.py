import hashlib
import json
import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


def _generar_envio_id():
    return f'env_{uuid.uuid4().hex}'


class Envio(models.Model):
    """Bitácora canónica de mensajería (D1 del contrato v1). Cualquier
    sistema que pida un envío por la pasarela queda registrado aquí, sin
    importar si el destinatario es un prospecto del CRM, un paciente o un
    alumno.

    `content_type`/`object_id`/`destinatario_local` es un GenericForeignKey
    igual al de `apps.core.auditoria.models.RegistroAuditoria` (el precedente
    que cita D1), pero solo puede resolver a un modelo que exista en ESTE
    proyecto Django (hoy, crm_ventas.Prospecto cuando esa app exista). Para
    un origen de otro servicio -- ConsultorioWeb, Academia -- no hay
    ContentType posible: no son modelos de este proyecto. Por eso el origen
    real y siempre presente son `origen_sistema`/`origen_entidad`/
    `origen_id` (texto plano, tal cual llega en el payload); el
    GenericForeignKey es un enlace local de cortesía cuando aplica, nunca la
    fuente de verdad de "qué se le dijo a esta persona" -- para eso están los
    tres campos `origen_*`, consultables aunque el sistema de origen sea
    externo."""

    class Estado(models.TextChoices):
        ENCOLADO = 'encolado', 'Encolado'
        ENVIADO = 'enviado', 'Enviado'
        ENTREGADO = 'entregado', 'Entregado'
        LEIDO = 'leido', 'Leído'
        FALLIDO = 'fallido', 'Fallido'
        BLOQUEADO = 'bloqueado', 'Bloqueado'
        CANCELADO = 'cancelado', 'Cancelado'

    envio_id = models.CharField(
        max_length=40, unique=True, default=_generar_envio_id, editable=False,
    )

    destinatario = models.CharField(
        max_length=20,
        help_text='Número en formato E.164, ya normalizado.',
    )
    plantilla = models.CharField(max_length=100)
    idioma = models.CharField(max_length=10, default='es_MX')
    variables = models.JSONField(default=dict, blank=True)
    adjunto = models.JSONField(null=True, blank=True)
    enviar_despues_de = models.DateTimeField(null=True, blank=True)

    origen_sistema = models.CharField(max_length=60)
    origen_entidad = models.CharField(max_length=60)
    origen_id = models.CharField(max_length=60)

    # Enlace local opcional -- ver docstring de la clase.
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    destinatario_local = GenericForeignKey('content_type', 'object_id')

    estado = models.CharField(
        max_length=12, choices=Estado.choices, default=Estado.ENCOLADO,
    )
    motivo_bloqueo = models.CharField(max_length=30, blank=True)
    wa_message_id = models.CharField(max_length=100, blank=True)

    idempotency_key = models.CharField(max_length=100, unique=True)
    huella_payload = models.CharField(max_length=64)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    entregado_en = models.DateTimeField(null=True, blank=True)
    leido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Envío'
        verbose_name_plural = 'Envíos'
        indexes = [
            models.Index(fields=['destinatario']),
            models.Index(fields=['origen_sistema', 'origen_entidad', 'origen_id']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f'{self.envio_id} -> {self.destinatario} ({self.plantilla})'


def huella_de(payload):
    """Hash estable del payload lógico (sin ids de intento) para poder
    distinguir "mismo Idempotency-Key, mismo envío" de "mismo
    Idempotency-Key, contenido distinto" -- igual que exige la sección 8 del
    contrato v1 de Consultorio Web para `external_request_id`."""
    canonico = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonico.encode('utf-8')).hexdigest()


class Baja(models.Model):
    """Una sola lista de bajas para toda la operación (D4): si la persona
    pidió no recibir mensajes, ningún sistema puede pasarla por alto aunque
    no lo sepa."""

    destinatario = models.CharField(max_length=20, unique=True)
    origen_sistema = models.CharField(max_length=60)
    motivo = models.CharField(max_length=255, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Baja'
        verbose_name_plural = 'Bajas'

    def __str__(self):
        return self.destinatario


class UltimaInteraccion(models.Model):
    """Marca de tiempo del último mensaje ENTRANTE de cada destinatario.
    Alimenta la regla de la ventana de 24 horas (D4). Ver nota en
    `servicios.py::dentro_de_ventana` sobre por qué, con D5 en vigor (la
    pasarela nunca manda texto libre), esta tabla hoy no bloquea ningún envío
    de plantilla -- se deja construida para cuando exista un modo de
    mensajes de sesión."""

    destinatario = models.CharField(max_length=20, unique=True)
    ultimo_mensaje_entrante_en = models.DateTimeField()

    def __str__(self):
        return f'{self.destinatario} @ {self.ultimo_mensaje_entrante_en}'


class SistemaSuscrito(models.Model):
    """Sistema externo autorizado a llamar la pasarela y/o a recibir sus
    webhooks salientes. La API Key de entrada y el secreto HMAC de salida
    son cosas distintas a propósito: una autentica quién nos llama, la otra
    firma lo que nosotros les mandamos."""

    nombre = models.CharField(max_length=60, unique=True)
    api_key = models.CharField(max_length=100, unique=True)
    webhook_url = models.URLField(blank=True)
    webhook_hmac_secret = models.CharField(max_length=100, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Sistema suscrito'
        verbose_name_plural = 'Sistemas suscritos'

    def __str__(self):
        return self.nombre
