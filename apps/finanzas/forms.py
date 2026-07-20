from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model

from .models import Egreso, Ingreso

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
