from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model

from .models import Donativo, Egreso, Ingreso

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
