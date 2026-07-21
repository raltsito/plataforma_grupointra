import os
from io import BytesIO

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.template.loader import render_to_string
from xhtml2pdf import pisa


def _link_callback(uri, rel):
    """Resuelve rutas de /static/ y /media/ a rutas de archivo reales, como
    pide xhtml2pdf para poder incrustar imágenes (ej. el logo de INTRA)."""
    if uri.startswith(settings.STATIC_URL):
        ruta = finders.find(uri.replace(settings.STATIC_URL, ''))
        if ruta:
            return ruta
    if uri.startswith(settings.MEDIA_URL):
        return os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ''))
    return uri


def render_pdf(template_name, contexto, nombre_archivo):
    html = render_to_string(template_name, contexto)
    buffer = BytesIO()
    resultado = pisa.CreatePDF(html, dest=buffer, link_callback=_link_callback)
    if resultado.err:
        raise RuntimeError('No se pudo generar el PDF de la nómina.')
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response
