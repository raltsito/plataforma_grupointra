from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models


class CategoriaTerapeuta(models.TextChoices):
    A = 'A', 'Categoría A'
    B = 'B', 'Categoría B'
    C = 'C', 'Categoría C'


class Tabulador(models.Model):
    """Tabulador institucional de honorarios. Versionado: un cambio de
    tarifas se registra como una fila nueva, nunca editando una vigente,
    para que los honorarios ya calculados no se alteren retroactivamente."""

    categoria = models.CharField(max_length=1, choices=CategoriaTerapeuta.choices)
    pago_base = models.DecimalField(max_digits=10, decimal_places=2)
    umbral_pacientes_semana = models.PositiveIntegerField(
        help_text='Número de pacientes atendidos por semana a partir del cual aplica el bono de gasolina.'
    )
    monto_bono = models.DecimalField(max_digits=10, decimal_places=2)
    vigente_desde = models.DateField()

    class Meta:
        verbose_name = 'Tabulador'
        verbose_name_plural = 'Tabuladores'
        ordering = ['-vigente_desde']

    def __str__(self):
        return f'{self.get_categoria_display()} · vigente desde {self.vigente_desde}'


class Ingreso(models.Model):
    class Concepto(models.TextChoices):
        CONSULTA = 'consulta', 'Consulta'
        INSCRIPCION_DIPLOMADO = 'inscripcion_diplomado', 'Inscripción diplomado'
        MENSUALIDAD_DIPLOMADO = 'mensualidad_diplomado', 'Mensualidad diplomado'
        INSCRIPCION_TALLER = 'inscripcion_taller', 'Inscripción taller'
        MENSUALIDAD_TALLER = 'mensualidad_taller', 'Mensualidad taller'
        CURSO_CERTIFICACION = 'curso_certificacion', 'Curso / certificación'

    class Estatus(models.TextChoices):
        PAGADO = 'pagado', 'Pagado'
        PARCIAL = 'parcial', 'Parcial'
        PENDIENTE = 'pendiente', 'Pendiente'

    concepto = models.CharField(max_length=30, choices=Concepto.choices)
    terapeuta = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='ingresos',
    )
    persona = models.CharField('Alumno / Paciente', max_length=150, blank=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    estatus = models.CharField(max_length=10, choices=Estatus.choices, default=Estatus.PENDIENTE)
    fecha = models.DateField()

    class Meta:
        verbose_name = 'Ingreso'
        verbose_name_plural = 'Ingresos'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.get_concepto_display()} · {self.monto} · {self.fecha}'


class CitaRecepcion(models.Model):
    """Fila del Reporte General de Recepción (agenda.intra.org.mx),
    importada desde el Excel exportado por esa plataforma. Guarda la cita tal
    cual, y opcionalmente queda ligada al Ingreso que generó (solo las citas
    que cuentan como ingreso real lo tienen) — ver
    integraciones/importador_recepcion.py."""

    class Estatus(models.TextChoices):
        CONFIRMADA = 'confirmada', 'Confirmada'
        SIN_CONFIRMAR = 'sin_confirmar', 'Sin confirmar'
        REAGENDO = 'reagendo', 'Reagendó'
        CANCELO = 'cancelo', 'Canceló'
        SI_ASISTIO = 'si_asistio', 'Sí asistió'
        NO_ASISTIO = 'no_asistio', 'No asistió'
        INCIDENCIA = 'incidencia', 'Incidencia'

    class MetodoPago(models.TextChoices):
        TRANSFERENCIA = 'transferencia', 'Transferencia'
        EFECTIVO = 'efectivo', 'Efectivo'
        PASE = 'pase', 'Pase'
        DEBITO = 'debito', 'Débito'
        CREDITO = 'credito', 'Crédito'

    fecha = models.DateField()
    hora = models.TimeField()
    tipo_cita = models.CharField(max_length=50, blank=True)
    paciente = models.CharField(max_length=150)
    terapeuta = models.CharField(max_length=150)
    servicio = models.CharField(max_length=100, blank=True)
    division = models.CharField('División', max_length=100, blank=True)
    consultorio = models.CharField(max_length=100, blank=True)
    estatus = models.CharField(max_length=20, choices=Estatus.choices)
    metodo_pago = models.CharField(max_length=20, choices=MetodoPago.choices, blank=True)
    costo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ingreso = models.OneToOneField(
        Ingreso, null=True, blank=True, on_delete=models.SET_NULL,
        editable=False, related_name='cita_recepcion',
    )

    class Meta:
        verbose_name = 'Cita de Recepción'
        verbose_name_plural = 'Citas de Recepción'
        ordering = ['-fecha', '-hora']
        # Validación de duplicados pedida en la sección 5.1 del documento:
        # una misma cita (fecha, hora, paciente, terapeuta, servicio) nunca
        # se importa dos veces; una segunda importación actualiza la fila.
        unique_together = ('fecha', 'hora', 'paciente', 'terapeuta', 'servicio')

    def __str__(self):
        return f'{self.paciente} · {self.terapeuta} · {self.fecha} {self.hora}'


class Egreso(models.Model):
    class Categoria(models.TextChoices):
        RENTA = 'renta', 'Renta'
        SERVICIOS = 'servicios', 'Servicios'
        INSUMOS = 'insumos', 'Insumos'
        NOMINA_ADMIN = 'nomina_admin', 'Nómina administrativa'
        NOMINA_TERAPEUTAS = 'nomina_terapeutas', 'Nómina terapeutas (ConsultorioWeb)'
        NOMINA_ACADEMIA = 'nomina_academia', 'Nómina Academia'

    class MetodoPago(models.TextChoices):
        TRANSFERENCIA = 'transferencia', 'Transferencia'
        EFECTIVO = 'efectivo', 'Efectivo'
        CHEQUE = 'cheque', 'Cheque'
        OTRO = 'otro', 'Otro'

    class Estatus(models.TextChoices):
        PAGADO = 'pagado', 'Pagado'
        PENDIENTE = 'pendiente', 'Pendiente'

    concepto = models.CharField(max_length=150)
    categoria = models.CharField(max_length=20, choices=Categoria.choices)
    persona = models.CharField('Terapeuta / Proveedor', max_length=150, blank=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, choices=MetodoPago.choices, blank=True)
    estatus = models.CharField(max_length=10, choices=Estatus.choices, default=Estatus.PAGADO)
    fecha = models.DateField()
    # Identificador del movimiento de origen en un sistema externo (ej.
    # 'consultorioweb:corte:123:base'), usado para no duplicar un egreso si
    # la importación se vuelve a correr. null=True (no blank/'') porque un
    # índice único permite múltiples NULL pero no múltiples cadenas vacías,
    # y los egresos capturados a mano no tienen referencia externa.
    referencia_externa = models.CharField(max_length=80, unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = 'Egreso'
        verbose_name_plural = 'Egresos'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.concepto} · {self.monto} · {self.fecha}'


class Honorario(models.Model):
    class Estatus(models.TextChoices):
        PAGADO = 'pagado', 'Pagado'
        PENDIENTE = 'pendiente', 'Pendiente'

    terapeuta = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='honorarios',
    )
    tabulador = models.ForeignKey(Tabulador, on_delete=models.PROTECT, related_name='honorarios')
    periodo_mes = models.PositiveSmallIntegerField()
    periodo_anio = models.PositiveSmallIntegerField()
    num_pacientes = models.PositiveIntegerField()
    bono = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    total = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    estatus = models.CharField(max_length=10, choices=Estatus.choices, default=Estatus.PENDIENTE)

    class Meta:
        verbose_name = 'Honorario'
        verbose_name_plural = 'Honorarios'
        ordering = ['-periodo_anio', '-periodo_mes']
        unique_together = ('terapeuta', 'periodo_mes', 'periodo_anio')

    def __str__(self):
        return f'{self.terapeuta} · {self.periodo_mes}/{self.periodo_anio}'

    def save(self, *args, **kwargs):
        # El bono y el total se calculan una sola vez, al crear el registro,
        # para que un honorario ya cerrado no cambie si el tabulador se
        # actualiza después (regla de negocio: pagos cerrados no se alteran).
        if self._state.adding:
            self.bono = (
                self.tabulador.monto_bono
                if self.num_pacientes > self.tabulador.umbral_pacientes_semana
                else 0
            )
            self.total = self.tabulador.pago_base + self.bono
        super().save(*args, **kwargs)


class Donativo(models.Model):
    class Tipo(models.TextChoices):
        MONETARIO = 'monetario', 'Monetario'
        ESPECIE = 'especie', 'En especie'

    class EstatusCFDI(models.TextChoices):
        VIGENTE = 'vigente', 'Vigente'
        CANCELADO = 'cancelado', 'Cancelado'
        TRAMITE = 'tramite', 'En trámite'

    donante_nombre = models.CharField(max_length=200)
    donante_rfc = models.CharField('RFC', max_length=13, blank=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    folio_cfdi = models.CharField('Folio CFDI', max_length=50, blank=True, null=True)
    estatus_cfdi = models.CharField(
        'Estatus CFDI', max_length=10, choices=EstatusCFDI.choices, default=EstatusCFDI.TRAMITE,
    )
    archivo_xml = models.FileField(upload_to='finanzas/donativos/xml/', blank=True, null=True)
    archivo_pdf = models.FileField(upload_to='finanzas/donativos/pdf/', blank=True, null=True)
    fecha = models.DateField()

    class Meta:
        verbose_name = 'Donativo'
        verbose_name_plural = 'Donativos'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.donante_nombre} · {self.monto} · {self.fecha}'


class Maestro(models.Model):
    """Docente de Academia. No es un FK a Usuario del portal (igual que
    Egreso.persona / CitaRecepcion.terapeuta): hoy no existen cuentas de
    Usuario para el personal de Academia."""

    nombre = models.CharField(max_length=150)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Maestro (Academia)'
        verbose_name_plural = 'Maestros (Academia)'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class TabuladorAcademia(models.Model):
    """Tabulador de Academia por concepto (horas clase, supervisión, mesa de
    trabajo). Versionado igual que Tabulador: un cambio de tarifa es una fila
    nueva, nunca se edita una vigente, para no alterar nóminas ya calculadas."""

    class Concepto(models.TextChoices):
        HORAS_CLASE = 'horas_clase', 'Horas clase'
        SUPERVISION = 'supervision', 'Supervisión'
        MESA_TRABAJO = 'mesa_trabajo', 'Mesa de trabajo'

    concepto = models.CharField(max_length=20, choices=Concepto.choices)
    monto_unidad = models.DecimalField(max_digits=10, decimal_places=2)
    vigente_desde = models.DateField()

    class Meta:
        verbose_name = 'Tabulador de Academia'
        verbose_name_plural = 'Tabuladores de Academia'
        ordering = ['-vigente_desde']

    def __str__(self):
        return f'{self.get_concepto_display()} · ${self.monto_unidad} · vigente desde {self.vigente_desde}'

    @classmethod
    def vigente(cls, concepto, fecha):
        return cls.objects.filter(concepto=concepto, vigente_desde__lte=fecha).order_by('-vigente_desde').first()


class NominaAcademia(models.Model):
    """Cabecera de la nómina de un maestro en un periodo (mes/año). El total
    se congela al capturar los conceptos (ver nomina_academia.py) y no
    cambia si el tabulador se actualiza después — misma regla que Honorario."""

    class MetodoPago(models.TextChoices):
        TRANSFERENCIA = 'transferencia', 'Transferencia'
        EFECTIVO = 'efectivo', 'Efectivo'

    class Estatus(models.TextChoices):
        PAGADO = 'pagado', 'Pagado'
        PENDIENTE = 'pendiente', 'Pendiente'

    maestro = models.ForeignKey(Maestro, on_delete=models.PROTECT, related_name='nominas')
    periodo_mes = models.PositiveSmallIntegerField()
    periodo_anio = models.PositiveSmallIntegerField()
    metodo_pago = models.CharField(max_length=20, choices=MetodoPago.choices, blank=True)
    estatus = models.CharField(max_length=10, choices=Estatus.choices, default=Estatus.PENDIENTE)
    total = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=Decimal('0'))

    class Meta:
        verbose_name = 'Nómina Academia'
        verbose_name_plural = 'Nóminas Academia'
        ordering = ['-periodo_anio', '-periodo_mes']
        # Evita duplicar nómina por docente y periodo (sección 6.1 del
        # documento); una corrección posterior es un ajuste (Fase 4), no una
        # segunda captura.
        unique_together = ('maestro', 'periodo_mes', 'periodo_anio')

    def __str__(self):
        return f'{self.maestro} · {self.periodo_mes}/{self.periodo_anio}'


class ConceptoNominaAcademia(models.Model):
    """Línea de una NominaAcademia. La tarifa y el subtotal se calculan una
    sola vez al crearse (igual que Honorario.bono/total): la tarifa se toma
    del TabuladorAcademia vigente en el periodo, salvo para el concepto
    'manual', donde la captura la persona que autoriza."""

    class Concepto(models.TextChoices):
        HORAS_CLASE = 'horas_clase', 'Horas clase'
        SUPERVISION = 'supervision', 'Supervisión'
        MESA_TRABAJO = 'mesa_trabajo', 'Mesa de trabajo'
        MANUAL = 'manual', 'Concepto manual autorizado'

    nomina = models.ForeignKey(NominaAcademia, on_delete=models.CASCADE, related_name='conceptos')
    concepto = models.CharField(max_length=20, choices=Concepto.choices)
    descripcion = models.CharField(max_length=150, blank=True, help_text='Solo para el concepto manual autorizado.')
    cantidad = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('1'))
    tabulador = models.ForeignKey(
        TabuladorAcademia, null=True, blank=True, on_delete=models.PROTECT,
        editable=False, related_name='conceptos_generados',
    )
    tarifa = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, editable=False)

    class Meta:
        verbose_name = 'Concepto de Nómina Academia'
        verbose_name_plural = 'Conceptos de Nómina Academia'

    def __str__(self):
        return f'{self.get_concepto_display()} · {self.nomina}'

    def save(self, *args, **kwargs):
        if self._state.adding and self.concepto != self.Concepto.MANUAL:
            fecha_ref = date(self.nomina.periodo_anio, self.nomina.periodo_mes, 1)
            self.tabulador = TabuladorAcademia.vigente(self.concepto, fecha_ref)
            self.tarifa = self.tabulador.monto_unidad if self.tabulador else Decimal('0')
        if self._state.adding:
            self.subtotal = self.cantidad * self.tarifa
        super().save(*args, **kwargs)
