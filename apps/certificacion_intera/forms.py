from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.portafolio.models import Instrumento
from .instrumentos import excluir_instrumentos_de_flujo_interno

from .models import (
    Canalizacion,
    ConfiguracionInstrumento,
    Consejeria,
    EntrevistaSeguimiento,
    Escuela,
    Participante,
    ProcesoCertificacion,
)


class BaseInteraForm(forms.ModelForm):
    def clean(self):
        try:
            return super().clean()
        except ValidationError as error:
            self.add_error(None, error)
            return self.cleaned_data


class EscuelaForm(BaseInteraForm):
    class Meta:
        model = Escuela

        fields = (
            'nombre',
            'nivel_educativo',
            'director',
            'cantidad_total_alumnos',
            'contacto',
            'correo',
            'telefono',
            'estado',
            'municipio',
            'direccion',
            'observaciones',
        )

        widgets = {
            'direccion': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
            'observaciones': forms.Textarea(
                attrs={
                    'rows': 4,
                }
            ),
        }


class ProcesoCertificacionForm(BaseInteraForm):
    escuela = forms.ModelChoiceField(
        queryset=Escuela.objects.all(),
        required=True,
        empty_label='Selecciona una escuela',
    )

    instrumentos = forms.ModelMultipleChoiceField(
        queryset=Instrumento.objects.none(),
        required=True,
    )

    fecha_cierre = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
            }
        ),
    )

    def __init__(
        self,
        *args,
        instrumentos_disponibles=None,
        escuela_preseleccionada=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.fields['instrumentos'].queryset = (
            instrumentos_disponibles
            if instrumentos_disponibles is not None
            else Instrumento.objects.none()
        )

        if escuela_preseleccionada:
            self.fields['escuela'].initial = escuela_preseleccionada
            self.fields['escuela'].required = False

    def clean(self):
        cleaned_data = super().clean()
        fecha_cierre = cleaned_data.get('fecha_cierre')

        if cleaned_data.get('estado') == ProcesoCertificacion.Estado.CERRADO:
            if not fecha_cierre:
                self.add_error(
                    'fecha_cierre',
                    'Para cerrar el proceso registra una fecha de cierre.',
                )
            elif fecha_cierre > timezone.localdate():
                self.add_error(
                    'fecha_cierre',
                    (
                        'No se puede cerrar el proceso porque la fecha de '
                        'cierre aún no ha pasado.'
                    ),
                )

        return cleaned_data

    class Meta:
        model = ProcesoCertificacion

        fields = (
            'ciclo_escolar',
            'nombre',
            'fecha_inicio',
            'fecha_cierre',
            'observaciones',
        )

        widgets = {
            'fecha_inicio': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
            'fecha_cierre': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
            'observaciones': forms.Textarea(
                attrs={
                    'rows': 4,
                }
            ),
        }


class ParticipanteForm(BaseInteraForm):
    class Meta:
        model = Participante

        fields = (
            'nombre',
            'numero_alumno',
            'grupo',
            'sexo',
            'fecha_nacimiento',
            'correo',
            'telefono',
        )

        widgets = {
            'fecha_nacimiento': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
        }


class ParticipantePublicoForm(ParticipanteForm):
    """Misma estructura del participante, sin permitir escoger proceso o escuela."""

    fecha_nacimiento = forms.DateField(
        required=True,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
            }
        ),
    )

    class Meta:
        model = Participante

        fields = (
            'nombre',
            'numero_alumno',
            'grupo',
            'fecha_nacimiento',
            'correo',
            'telefono',
        )

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data['fecha_nacimiento']

        if fecha > timezone.localdate():
            raise ValidationError(
                'La fecha de nacimiento no puede ser futura.'
            )

        return fecha

    def clean(self):
        datos = super().clean()

        if not datos.get('nombre') or not datos.get('numero_alumno'):
            raise ValidationError(
                'Captura nombre completo y matrícula.'
            )

        return datos


class SexoBaremoPublicoForm(forms.Form):
    """Dato contextual capturado solo cuando una calculadora lo requiere."""

    sexo = forms.ChoiceField(
        label='Sexo (requerido para baremos del instrumento)',
        choices=(
            (
                'femenino',
                'Femenino',
            ),
            (
                'masculino',
                'Masculino',
            ),
        ),
        widget=forms.RadioSelect,
    )


class FechaNacimientoPublicoForm(forms.Form):
    fecha_nacimiento = forms.DateField(
        label='Fecha de nacimiento (requerida para seleccionar la variante)',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data['fecha_nacimiento']
        if fecha > timezone.localdate():
            raise ValidationError('La fecha de nacimiento no puede ser futura.')
        return fecha


class ConfiguracionInstrumentoForm(BaseInteraForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['instrumento'].queryset = excluir_instrumentos_de_flujo_interno(
            Instrumento.objects.filter(activo=True),
        )

    class Meta:
        model = ConfiguracionInstrumento

        fields = (
            'instrumento',
            'requerido',
            'estado',
            'fecha_inicio',
            'fecha_cierre',
            'observaciones',
        )

        widgets = {
            'fecha_inicio': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
            'fecha_cierre': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
            'observaciones': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }


class EntrevistaSeguimientoForm(BaseInteraForm):
    class Meta:
        model = EntrevistaSeguimiento

        fields = (
            'nombre_confirmado',
            'numero_alumno_confirmado',
            'fecha',
            'observaciones',
            'decision',
        )

        widgets = {
            'fecha': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
            'observaciones': forms.Textarea(
                attrs={
                    'rows': 4,
                }
            ),
        }


class ConsejeriaForm(BaseInteraForm):
    class Meta:
        model = Consejeria

        fields = (
            'fecha',
            'observaciones',
            'estado',
        )

        widgets = {
            'fecha': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
            'observaciones': forms.Textarea(
                attrs={
                    'rows': 4,
                }
            ),
        }


class CanalizacionForm(BaseInteraForm):
    class Meta:
        model = Canalizacion

        fields = (
            'tipo',
            'fecha',
            'prioridad',
            'destino',
            'motivo',
            'observaciones',
            'estado',
            'estado_clinico',
            'comentarios_recepcion',
        )

        widgets = {
            'fecha': forms.DateInput(
                attrs={
                    'type': 'date',
                }
            ),
            'observaciones': forms.Textarea(
                attrs={
                    'rows': 4,
                }
            ),
            'comentarios_recepcion': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }
