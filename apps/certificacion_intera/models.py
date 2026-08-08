import uuid
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.portafolio.models import Instrumento, PreguntaInstrumento, RevisionInstrumento
from .instrumentos import es_instrumento_de_flujo_interno


class Escuela(models.Model):
    nombre = models.CharField(max_length=200)
    nivel_educativo = models.CharField(max_length=100, blank=True)
    director = models.CharField(max_length=150)
    cantidad_total_alumnos = models.PositiveIntegerField()
    contacto = models.CharField(max_length=150, blank=True)
    correo = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    estado = models.CharField(max_length=100)
    municipio = models.CharField(max_length=100)
    direccion = models.TextField(blank=True)
    observaciones = models.TextField(blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Escuela'
        verbose_name_plural = 'Escuelas'

    def __str__(self):
        return self.nombre


class ProcesoCertificacion(models.Model):
    class Estado(models.TextChoices):
        CONFIGURACION = ('configuracion', 'Configuración')
        APLICACION = ('aplicacion', 'Aplicación de instrumentos')
        SEGUIMIENTO = ('seguimiento', 'Seguimiento')
        CONSEJERIA = ('consejeria', 'Consejerías')
        CERRADO = ('cerrado', 'Cerrado')

    escuela = models.ForeignKey(Escuela, on_delete=models.PROTECT, related_name='procesos')
    ciclo_escolar = models.CharField(max_length=30, blank=True)
    nombre = models.CharField(max_length=150, default='Proceso de certificación')
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.CONFIGURACION,
    )
    fecha_inicio = models.DateField()
    fecha_cierre = models.DateField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_inicio', '-id']
        verbose_name = 'Proceso de certificación'
        verbose_name_plural = 'Procesos de certificación'

    def __str__(self):
        return f'{self.escuela} · {self.nombre}'

    def clean(self):
        if self.fecha_cierre and self.fecha_cierre < self.fecha_inicio:
            raise ValidationError(
                'La fecha de cierre no puede ser anterior a la fecha de inicio.',
            )
        if self.estado == self.Estado.CERRADO:
            if not self.fecha_cierre:
                raise ValidationError('Para cerrar el proceso registra una fecha de cierre.')
            if self.fecha_cierre > timezone.localdate():
                raise ValidationError(
                    'No se puede cerrar el proceso porque la fecha de cierre aún no ha pasado.',
                )

    class Meta:
        ordering = ['-fecha_inicio', '-id']
        verbose_name = 'Proceso de certificación'
        verbose_name_plural = 'Procesos de certificación'
        constraints = [
            models.UniqueConstraint(
                fields=['escuela', 'ciclo_escolar'],
                name='proceso_unico_por_escuela_y_ciclo',
            ),
        ]


class ConfiguracionInstrumento(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = ('pendiente', 'Pendiente')
        ACTIVA = ('activa', 'Activa')
        CERRADA = ('cerrada', 'Cerrada')

    proceso = models.ForeignKey(
        ProcesoCertificacion,
        on_delete=models.CASCADE,
        related_name='configuraciones_instrumento',
    )
    instrumento = models.ForeignKey(
        Instrumento,
        on_delete=models.PROTECT,
        related_name='configuraciones_intera',
    )
    requerido = models.BooleanField(default=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.ACTIVA)
    orden = models.PositiveIntegerField(default=0)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_cierre = models.DateField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('proceso', 'instrumento')
        ordering = ('orden', 'id')
        verbose_name = 'Configuración de instrumento'
        verbose_name_plural = 'Configuraciones de instrumentos'

    def clean(self):
        if self.instrumento_id and es_instrumento_de_flujo_interno(self.instrumento):
            raise ValidationError(
                'Este instrumento pertenece a un flujo interno y no puede formar parte de la batería.',
            )
        if not self.instrumento.activo:
            raise ValidationError('No es posible configurar un instrumento inactivo.')
        if self.fecha_cierre and self.fecha_inicio and (self.fecha_cierre < self.fecha_inicio):
            raise ValidationError(
                'La fecha de cierre no puede ser anterior a la fecha de inicio.',
            )


class Participante(models.Model):
    proceso = models.ForeignKey(
        ProcesoCertificacion,
        on_delete=models.CASCADE,
        related_name='participantes',
    )
    nombre = models.CharField(max_length=200)
    numero_alumno = models.CharField(max_length=50)
    grupo = models.CharField(max_length=100, blank=True)
    sexo = models.CharField(
        max_length=15,
        choices=[
            ('femenino', 'Femenino'),
            ('masculino', 'Masculino'),
            ('otro', 'Otro'),
            ('no_especificado', 'Prefiero no especificar'),
        ],
        blank=True,
    )
    fecha_nacimiento = models.DateField(null=True, blank=True)
    correo = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    privacidad_aceptada_en = models.DateTimeField(null=True, blank=True)
    privacidad_version = models.CharField(max_length=30, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        unique_together = ('proceso', 'numero_alumno')

    def __str__(self):
        return f'{self.nombre} · {self.numero_alumno}'

    @property
    def aplicaciones_pendientes(self):
        requeridos = (
            self.proceso.configuraciones_instrumento
            .filter(requerido=True)
            .values_list('instrumento_id', flat=True)
        )
        respondidos = (
            self.aplicaciones
            .filter(estado=AplicacionInstrumento.Estado.RESPONDIDA)
            .values_list('instrumento_id', flat=True)
        )
        return set(requeridos) - set(respondidos)


class AplicacionInstrumento(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = ('pendiente', 'Pendiente')
        RESPONDIDA = ('respondida', 'Respondida')
        CANCELADA = ('cancelada', 'Cancelada')

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    proceso = models.ForeignKey(
        ProcesoCertificacion,
        on_delete=models.CASCADE,
        related_name='aplicaciones',
    )
    participante = models.ForeignKey(
        Participante,
        on_delete=models.CASCADE,
        related_name='aplicaciones',
    )
    instrumento = models.ForeignKey(
        Instrumento,
        on_delete=models.PROTECT,
        related_name='aplicaciones_intera',
    )
    aplicacion_publica = models.ForeignKey(
        'AplicacionPublica',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='aplicaciones_individuales',
    )
    generado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PENDIENTE)
    creado_en = models.DateTimeField(auto_now_add=True)
    iniciada_en = models.DateTimeField(null=True, blank=True)
    respondido_en = models.DateTimeField(null=True, blank=True)
    puntaje_total = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    interpretacion = models.TextField(blank=True)
    resultado_detalle = models.JSONField(blank=True, null=True)
    revision_calculadora = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ['-creado_en']

    def clean(self):
        if (
            self.participante_id and
            self.proceso_id and
            self.participante.proceso_id != self.proceso_id
        ):
            raise ValidationError('El participante debe pertenecer al proceso seleccionado.')


class AplicacionPublica(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = ('activa', 'Activa')
        CERRADA = ('cerrada', 'Cerrada')

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    configuracion = models.OneToOneField(
        ConfiguracionInstrumento,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='aplicacion_publica',
    )
    proceso = models.OneToOneField(
        ProcesoCertificacion,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='aplicacion_publica_general',
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVA)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(configuracion__isnull=False)
                    | models.Q(proceso__isnull=False)
                ),
                name='aplicacion_publica_con_origen',
            ),
        ]

    @property
    def instrumento(self):
        return self.configuracion.instrumento if self.configuracion_id else None

    @property
    def fecha_apertura(self):
        return self.configuracion.fecha_inicio if self.configuracion_id else None

    @property
    def fecha_cierre(self):
        return self.configuracion.fecha_cierre if self.configuracion_id else None

    @property
    def url_publica(self):
        from django.urls import reverse
        return reverse('certificacion_intera:aplicacion_publica', args=[self.token])


class ResultadoInstrumento(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = ('pendiente', 'Pendiente de evaluación')
        EVALUADO = ('evaluado', 'Evaluado')

    aplicacion = models.OneToOneField(
        AplicacionInstrumento,
        on_delete=models.CASCADE,
        related_name='resultado',
    )
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    creado_en = models.DateTimeField(auto_now_add=True)
    observaciones = models.TextField(blank=True)


class BitacoraProceso(models.Model):
    proceso = models.ForeignKey(
        ProcesoCertificacion,
        on_delete=models.CASCADE,
        related_name='bitacora',
    )
    evento = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']


class RespuestaInstrumento(models.Model):
    aplicacion = models.ForeignKey(
        AplicacionInstrumento,
        on_delete=models.CASCADE,
        related_name='respuestas',
    )
    pregunta = models.ForeignKey(
        PreguntaInstrumento,
        on_delete=models.CASCADE,
        related_name='respuestas_intera',
    )
    valor = models.TextField(blank=True)
    valor_numerico = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('aplicacion', 'pregunta')
        ordering = ['pregunta__orden']


class EntrevistaSeguimiento(models.Model):
    class Decision(models.TextChoices):
        FINALIZAR = ('finalizar', 'Finalizar caso')
        CONSEJERIA = ('consejeria', 'Enviar a consejería')

    participante = models.OneToOneField(
        Participante,
        on_delete=models.CASCADE,
        related_name='entrevista',
    )
    nombre_confirmado = models.CharField(max_length=200)
    numero_alumno_confirmado = models.CharField(max_length=50)
    fecha = models.DateField()
    observaciones = models.TextField(blank=True)
    decision = models.CharField(max_length=15, choices=Decision.choices)
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.participante_id and self.participante.aplicaciones_pendientes:
            raise ValidationError(
                'El participante aún no ha respondido todos los instrumentos requeridos.',
            )


class Consejeria(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = ('pendiente', 'Pendiente')
        REALIZADA = ('realizada', 'Realizada')
        CANCELADA = ('cancelada', 'Cancelada')

    participante = models.ForeignKey(
        Participante,
        on_delete=models.CASCADE,
        related_name='consejerias',
    )
    fecha = models.DateField()
    observaciones = models.TextField()
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PENDIENTE)
    creada_en = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if (
            self.participante_id and
            self.participante.consejerias.exclude(pk=self.pk).count() >= 3
        ):
            raise ValidationError(
                'Solo se permiten hasta tres sesiones de consejería por participante.',
            )


class Canalizacion(models.Model):
    class Tipo(models.TextChoices):
        ORDINARIA = ('ordinaria', 'Ordinaria')
        VOLUNTARIA = ('voluntaria', 'Voluntaria')
        EMERGENCIA = ('emergencia', 'Emergencia')

    class Estado(models.TextChoices):
        REGISTRADA = ('registrada', 'Registrada')
        PENDIENTE_ENVIO = ('pendiente_envio', 'Pendiente de envío')
        ENVIADA = ('enviada', 'Enviada a recepción')
        CONFIRMADA = ('confirmada', 'Recepción confirmada')
        CITA_PROGRAMADA = ('cita_programada', 'Cita programada')
        ATENDIDA = ('atendida', 'Paciente atendido')
        CERRADA = ('cerrada', 'Cerrada')
        CANCELADA = ('cancelada', 'Cancelada')

    class Prioridad(models.TextChoices):
        BAJA = ('baja', 'Baja')
        MEDIA = ('media', 'Media')
        ALTA = ('alta', 'Alta')
        URGENTE = ('urgente', 'Urgente')

    class EstadoEnvio(models.TextChoices):
        PENDIENTE = ('pendiente', 'Pendiente de envío')
        ENVIADA = ('enviada', 'Enviada')
        CONFIRMADA = ('confirmada', 'Confirmada')
        ERROR = ('error', 'Error de sincronización')

    class EstadoClinico(models.TextChoices):
        SIN_RESPUESTA = ('sin_respuesta', 'Sin respuesta')
        RECIBIDA = ('recibida', 'Recibida')
        CITA_PROGRAMADA = ('cita_programada', 'Cita programada')
        ATENDIDA = ('atendida', 'Paciente atendido')
        CERRADA = ('cerrada', 'Cerrada')

    participante = models.ForeignKey(
        Participante,
        on_delete=models.CASCADE,
        related_name='canalizaciones',
    )
    fecha = models.DateField(default=timezone.localdate, verbose_name='Fecha de solicitud')
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.ORDINARIA)
    destino = models.CharField(max_length=200, default='INTRA')
    motivo = models.CharField(max_length=250)
    observaciones = models.TextField(blank=True)
    prioridad = models.CharField(
        max_length=10,
        choices=Prioridad.choices,
        default=Prioridad.MEDIA,
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE_ENVIO,
    )
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='canalizaciones_registradas',
    )
    fecha_envio = models.DateTimeField(null=True, blank=True)
    estado_envio = models.CharField(
        max_length=12,
        choices=EstadoEnvio.choices,
        default=EstadoEnvio.PENDIENTE,
    )
    estado_clinico = models.CharField(
        max_length=20,
        choices=EstadoClinico.choices,
        default=EstadoClinico.SIN_RESPUESTA,
    )
    fecha_respuesta = models.DateTimeField(null=True, blank=True)
    comentarios_recepcion = models.TextField(blank=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    remoto_id = models.CharField(max_length=100, blank=True)
    sincronizado_en = models.DateTimeField(null=True, blank=True)
    error_sincronizacion = models.TextField(blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['participante'],
                condition=models.Q(
                    estado__in=[
                        'registrada',
                        'pendiente_envio',
                        'enviada',
                        'confirmada',
                        'cita_programada',
                        'atendida',
                    ],
                ),
                name='canalizacion_activa_unica_por_participante',
            ),
        ]

    def clean(self):
        realizadas = (
            self.participante.consejerias.filter(estado=Consejeria.Estado.REALIZADA).count()
            if self.participante_id
            else 0
        )
        entrevista = (
            getattr(self.participante, 'entrevista', None)
            if self.participante_id
            else None
        )
        if self.tipo == self.Tipo.ORDINARIA and (not entrevista or realizadas < 3):
            raise ValidationError(
                'La canalización ordinaria requiere entrevista y tres consejerías realizadas.',
            )
        if self.tipo == self.Tipo.VOLUNTARIA and (not self.motivo.strip()):
            raise ValidationError('La canalización voluntaria requiere motivo.')
        if (
            self.tipo == self.Tipo.EMERGENCIA and
            (not self.motivo.strip() or not self.observaciones.strip())
        ):
            raise ValidationError(
                'La canalización de emergencia requiere motivo y observaciones.',
            )
        if (
            self.estado in (self.Estado.CERRADA, self.Estado.CANCELADA) and
            not self.fecha_cierre
        ):
            self.fecha_cierre = timezone.now()

    def save(self, *args, **kwargs):
        anterior = (
            None
            if self._state.adding
            else type(self).objects.filter(pk=self.pk).values('estado').first()
        )
        self.full_clean()
        super().save(*args, **kwargs)
        evento = (
            'Canalización creada'
            if anterior is None
            else (
                'Canalización cambió de estado'
                if anterior['estado'] != self.estado
                else 'Canalización modificada'
            )
        )
        descripcion = (
            f'{self.get_tipo_display()} · {self.get_estado_display()} · {self.participante.nombre}'
        )
        BitacoraProceso.objects.create(
            proceso=self.participante.proceso,
            evento=evento,
            descripcion=descripcion,
            usuario=self.registrada_por,
        )


class EntrevistaUnoAUno(models.Model):
    class Estado(models.TextChoices):
        EN_CURSO = ('en_curso', 'En curso')
        FINALIZADA = ('finalizada', 'Finalizada')
        REABIERTA = ('reabierta', 'Reabierta')

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    participante = models.ForeignKey(
        Participante,
        on_delete=models.CASCADE,
        related_name='entrevistas_1a1',
    )
    proceso = models.ForeignKey(
        ProcesoCertificacion,
        on_delete=models.CASCADE,
        related_name='entrevistas_1a1',
    )
    instrumento = models.ForeignKey(Instrumento, on_delete=models.PROTECT)
    revision_plantilla = models.ForeignKey(RevisionInstrumento, on_delete=models.PROTECT)
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name='entrevistas_1a1_responsable',
    )
    iniciada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name='entrevistas_1a1_iniciadas',
    )
    finalizada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='entrevistas_1a1_finalizadas',
    )
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.EN_CURSO)
    revision_actual = models.PositiveIntegerField(default=1)
    iniciada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    finalizada_en = models.DateTimeField(null=True, blank=True)
    reabierta_en = models.DateTimeField(null=True, blank=True)
    justificacion_reapertura = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['participante', 'proceso'],
                name='entrevista_1a1_unica_por_participante_y_proceso',
            ),
        ]
        permissions = [
            ('view_entrevista_1a1', 'Puede ver Entrevista 1:1'),
            ('request_entrevista_1a1', 'Puede solicitar acceso Entrevista 1:1'),
            ('manage_entrevista_1a1', 'Puede gestionar Entrevista 1:1'),
            ('finish_entrevista_1a1', 'Puede finalizar Entrevista 1:1'),
            ('reopen_entrevista_1a1', 'Puede reabrir Entrevista 1:1'),
            ('view_historial_entrevista_1a1', 'Puede consultar historial Entrevista 1:1'),
        ]

    def clean(self):
        if (
            self.participante_id and
            self.proceso_id and
            self.participante.proceso_id != self.proceso_id
        ):
            raise ValidationError('El participante no pertenece al proceso.')


class RespuestaEntrevistaUnoAUno(models.Model):
    entrevista = models.ForeignKey(
        EntrevistaUnoAUno,
        on_delete=models.CASCADE,
        related_name='respuestas',
    )
    pregunta = models.ForeignKey(PreguntaInstrumento, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    valor = models.TextField(blank=True)
    valor_numerico = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    valor_fecha = models.DateField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['entrevista', 'pregunta', 'revision'],
                name='respuesta_1a1_unica_por_revision',
            ),
        ]


class HistorialEntrevistaUnoAUno(models.Model):
    entrevista = models.ForeignKey(
        EntrevistaUnoAUno,
        on_delete=models.CASCADE,
        related_name='historial',
    )
    evento = models.CharField(max_length=80)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    revision = models.PositiveIntegerField()
    descripcion = models.CharField(max_length=250, blank=True)
    justificacion = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']


class VerificacionAccesoEntrevista(models.Model):
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE)
    proceso = models.ForeignKey(ProcesoCertificacion, on_delete=models.CASCADE)
    usuaria = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    exitosa = models.BooleanField()
    autorizada_hasta = models.DateTimeField(null=True, blank=True)
    usada_en = models.DateTimeField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['participante', 'usuaria', 'creada_en'])]


class SolicitudAtencion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE_ENVIO = ('pendiente_envio', 'Pendiente de envío')
        ENVIADA = ('enviada', 'Enviada')
        RECIBIDA = ('recibida', 'Recibida')
        ACEPTADA = ('aceptada', 'Aceptada')
        PACIENTE_REGISTRADO = ('paciente_registrado', 'Paciente registrado')
        CITA_PROGRAMADA = ('cita_programada', 'Cita programada')
        FINALIZADA = ('finalizada', 'Finalizada')
        CANCELADA = ('cancelada', 'Cancelada')
        ERROR = ('error', 'Error de sincronización')

    class Sincronizacion(models.TextChoices):
        PENDIENTE = ('pendiente', 'Sincronización pendiente')
        SINCRONIZADA = ('sincronizada', 'Sincronizada')
        ERROR = ('error', 'Error')

    class EstadoIntegracion(models.TextChoices):
        PENDIENTE = ('pendiente_envio', 'Pendiente de envío')
        ENVIANDO = ('enviando', 'Enviando')
        ENVIADA = ('enviada', 'Enviada')
        ERROR = ('error_comunicacion', 'Error de comunicación')

    canalizacion = models.OneToOneField(
        Canalizacion,
        on_delete=models.PROTECT,
        related_name='solicitud_atencion',
    )
    estado = models.CharField(
        max_length=22,
        choices=Estado.choices,
        default=Estado.PENDIENTE_ENVIO,
    )
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='solicitudes_atencion',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    fecha_respuesta = models.DateTimeField(null=True, blank=True)
    fecha_programacion = models.DateTimeField(null=True, blank=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    comentarios_recepcion = models.TextField(blank=True)
    remoto_id = models.CharField(max_length=100, blank=True)
    estado_sincronizacion = models.CharField(
        max_length=15,
        choices=Sincronizacion.choices,
        default=Sincronizacion.PENDIENTE,
    )
    sincronizado_en = models.DateTimeField(null=True, blank=True)
    ultimo_error = models.TextField(blank=True)
    external_request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    integration_status = models.CharField(
        max_length=22,
        choices=EstadoIntegracion.choices,
        default=EstadoIntegracion.PENDIENTE,
    )
    remote_status = models.CharField(max_length=30, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_send_attempt_at = models.DateTimeField(null=True, blank=True)
    last_status_check_at = models.DateTimeField(null=True, blank=True)
    last_response_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=30, blank=True)
    last_error_message = models.CharField(max_length=250, blank=True)
    send_attempts = models.PositiveIntegerField(default=0)
    remote_internal_request_id = models.CharField(max_length=100, blank=True)
    remote_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Solicitud de Atención'
        verbose_name_plural = 'Solicitudes de Atención'

    def save(self, *args, **kwargs):
        anterior = (
            None
            if self._state.adding
            else type(self).objects.filter(pk=self.pk).values('estado').first()
        )
        super().save(*args, **kwargs)
        evento = (
            'Solicitud de Atención creada'
            if anterior is None
            else (
                'Solicitud de Atención cambió de estado'
                if anterior['estado'] != self.estado
                else 'Solicitud de Atención modificada'
            )
        )
        BitacoraProceso.objects.create(
            proceso=self.canalizacion.participante.proceso,
            evento=evento,
            descripcion=f'{self.get_estado_display()} · {self.canalizacion.participante.nombre}',
            usuario=self.creada_por,
        )
