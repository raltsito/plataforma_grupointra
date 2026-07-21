from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model

from .models import ConceptoNominaAcademia, Donativo, Egreso, Ingreso, Maestro, NominaAcademia

User = get_user_model()

_ATTRS = {'class': 'fin-input'}


class IngresoForm(forms.ModelForm):
    class Meta:
        model = Ingreso
        fields = ['concepto', 'terapeuta', 'persona', 'monto', 'estatus', 'fecha']
        widgets = {
            'concepto': forms.Select(attrs=_ATTRS),
            'terapeuta': forms.Select(attrs=_ATTRS),
            'persona': forms.TextInput(attrs={**_ATTRS, 'placeholder': 'Nombre del alumno o paciente'}),
            'monto': forms.NumberInput(attrs={**_ATTRS, 'step': '0.01', 'min': '0.01'}),
            'estatus': forms.Select(attrs=_ATTRS),
            'fecha': forms.DateInput(attrs={**_ATTRS, 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['terapeuta'].queryset = User.objects.filter(
            groups__name='Terapeutas'
        ).order_by('first_name', 'username')
        self.fields['terapeuta'].required = False

    def clean_monto(self):
        monto = self.cleaned_data['monto']
        if monto <= Decimal('0'):
            raise forms.ValidationError('El monto debe ser mayor a cero.')
        return monto


class DonativoForm(forms.ModelForm):
    class Meta:
        model = Donativo
        fields = [
            'donante_nombre', 'donante_rfc', 'tipo', 'monto', 'folio_cfdi',
            'estatus_cfdi', 'archivo_xml', 'archivo_pdf', 'fecha',
        ]
        widgets = {
            'donante_nombre': forms.TextInput(attrs=_ATTRS),
            'donante_rfc': forms.TextInput(attrs={**_ATTRS, 'placeholder': 'RFC (opcional)'}),
            'tipo': forms.Select(attrs=_ATTRS),
            'monto': forms.NumberInput(attrs={**_ATTRS, 'step': '0.01', 'min': '0.01'}),
            'folio_cfdi': forms.TextInput(attrs={**_ATTRS, 'placeholder': 'Folio CFDI (opcional)'}),
            'estatus_cfdi': forms.Select(attrs=_ATTRS),
            'archivo_xml': forms.ClearableFileInput(attrs=_ATTRS),
            'archivo_pdf': forms.ClearableFileInput(attrs=_ATTRS),
            'fecha': forms.DateInput(attrs={**_ATTRS, 'type': 'date'}),
        }

    def clean_monto(self):
        monto = self.cleaned_data['monto']
        if monto <= Decimal('0'):
            raise forms.ValidationError('El monto debe ser mayor a cero.')
        return monto


class ReporteRecepcionUploadForm(forms.Form):
    archivo = forms.FileField(
        label='Reporte General (Excel)',
        widget=forms.ClearableFileInput(attrs={**_ATTRS, 'accept': '.xlsx'}),
    )

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        if not archivo.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('El archivo debe ser un Excel (.xlsx) exportado del Reporte General.')
        return archivo


_MESES = [
    (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'), (5, 'Mayo'), (6, 'Junio'),
    (7, 'Julio'), (8, 'Agosto'), (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
]


class NominaAcademiaCaptureForm(forms.Form):
    maestro = forms.ModelChoiceField(
        queryset=Maestro.objects.filter(activo=True), widget=forms.Select(attrs=_ATTRS),
    )
    periodo_mes = forms.ChoiceField(choices=_MESES, widget=forms.Select(attrs=_ATTRS))
    periodo_anio = forms.IntegerField(widget=forms.NumberInput(attrs={**_ATTRS, 'min': '2020'}))
    metodo_pago = forms.ChoiceField(
        choices=[('', 'Pendiente de asignar')] + list(NominaAcademia.MetodoPago.choices),
        required=False, widget=forms.Select(attrs=_ATTRS),
    )
    cantidad_horas_clase = forms.DecimalField(
        label='Horas clase', required=False, min_value=Decimal('0'),
        widget=forms.NumberInput(attrs={**_ATTRS, 'step': '0.5', 'placeholder': '0'}),
    )
    cantidad_supervision = forms.DecimalField(
        label='Supervisión', required=False, min_value=Decimal('0'),
        widget=forms.NumberInput(attrs={**_ATTRS, 'step': '0.5', 'placeholder': '0'}),
    )
    cantidad_mesa_trabajo = forms.DecimalField(
        label='Mesa de trabajo', required=False, min_value=Decimal('0'),
        widget=forms.NumberInput(attrs={**_ATTRS, 'step': '0.5', 'placeholder': '0'}),
    )
    concepto_manual_descripcion = forms.CharField(
        label='Concepto manual autorizado', required=False,
        widget=forms.TextInput(attrs={**_ATTRS, 'placeholder': 'Descripción (opcional)'}),
    )
    concepto_manual_monto = forms.DecimalField(
        label='Monto del concepto manual', required=False, min_value=Decimal('0'),
        widget=forms.NumberInput(attrs={**_ATTRS, 'step': '0.01', 'placeholder': '0.00'}),
    )

    def clean(self):
        datos = super().clean()
        cantidades = [
            datos.get('cantidad_horas_clase'), datos.get('cantidad_supervision'), datos.get('cantidad_mesa_trabajo'),
        ]
        manual_desc = datos.get('concepto_manual_descripcion')
        manual_monto = datos.get('concepto_manual_monto')
        if not any(cantidades) and not (manual_desc and manual_monto):
            raise forms.ValidationError(
                'Captura al menos un concepto (horas clase, supervisión, mesa de trabajo, o un concepto manual con descripción y monto).'
            )
        if bool(manual_desc) != bool(manual_monto):
            raise forms.ValidationError('El concepto manual necesita descripción y monto, los dos.')
        return datos

    def cantidades(self):
        return {
            ConceptoNominaAcademia.Concepto.HORAS_CLASE: self.cleaned_data.get('cantidad_horas_clase'),
            ConceptoNominaAcademia.Concepto.SUPERVISION: self.cleaned_data.get('cantidad_supervision'),
            ConceptoNominaAcademia.Concepto.MESA_TRABAJO: self.cleaned_data.get('cantidad_mesa_trabajo'),
        }


class EgresoForm(forms.ModelForm):
    class Meta:
        model = Egreso
        fields = ['concepto', 'categoria', 'persona', 'monto', 'metodo_pago', 'estatus', 'fecha']
        widgets = {
            'concepto': forms.TextInput(attrs=_ATTRS),
            'categoria': forms.Select(attrs=_ATTRS),
            'persona': forms.TextInput(attrs={**_ATTRS, 'placeholder': 'Terapeuta o proveedor'}),
            'monto': forms.NumberInput(attrs={**_ATTRS, 'step': '0.01', 'min': '0.01'}),
            'metodo_pago': forms.Select(attrs=_ATTRS),
            'estatus': forms.Select(attrs=_ATTRS),
            'fecha': forms.DateInput(attrs={**_ATTRS, 'type': 'date'}),
        }

    def clean_monto(self):
        monto = self.cleaned_data['monto']
        if monto <= Decimal('0'):
            raise forms.ValidationError('El monto debe ser mayor a cero.')
        return monto
