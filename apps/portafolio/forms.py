from django import forms

from .models import (
    Documento,
    Instrumento,
    PlantillaPDF,
    PreguntaInstrumento,
    RecursoCompartido,
    Reporte,
)


class InstrumentoForm(forms.ModelForm):
    class Meta:
        model = Instrumento

        fields = (
            'nombre',
            'clave',
            'documento_origen',
            'descripcion',
            'instrucciones',
            'activo',
        )

        widgets = {
            'descripcion': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
            'instrucciones': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['documento_origen'].queryset = Documento.objects.filter(
            categoria__nombre__iexact='Instrumento',
            estado=Documento.Estado.ACTIVO,
        )


class ImportarInstrumentoForm(forms.Form):
    archivo = forms.FileField(
        label='Archivo Excel',
        help_text='Selecciona un archivo .xlsx con la estructura de Portafolio.',
    )

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        if not archivo.name.lower().endswith('.xlsx'):
            raise forms.ValidationError(
                'Selecciona un archivo Excel válido con extensión .xlsx.'
            )
        return archivo


class PreguntaInstrumentoForm(forms.ModelForm):
    class Meta:
        model = PreguntaInstrumento

        fields = (
            'orden',
            'texto',
            'clave',
            'tipo_respuesta',
            'opciones',
            'requerida',
        )

        widgets = {
            'texto': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
            'opciones': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento

        fields = (
            'nombre',
            'archivo',
            'categoria',
            'descripcion',
            'estado',
            'version',
            'observaciones',
        )

        widgets = {
            'descripcion': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
            'observaciones': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }


class PlantillaPDFForm(forms.ModelForm):
    class Meta:
        model = PlantillaPDF

        fields = (
            'nombre',
            'descripcion',
            'archivo',
            'activa',
        )

        widgets = {
            'descripcion': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }


class ReporteForm(forms.ModelForm):
    class Meta:
        model = Reporte

        fields = (
            'nombre',
            'clave',
            'descripcion',
            'activo',
        )

        widgets = {
            'descripcion': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }


class RecursoCompartidoForm(forms.ModelForm):
    class Meta:
        model = RecursoCompartido

        fields = (
            'nombre',
            'tipo',
            'descripcion',
            'archivo',
            'activo',
        )

        widgets = {
            'descripcion': forms.Textarea(
                attrs={
                    'rows': 3,
                }
            ),
        }
