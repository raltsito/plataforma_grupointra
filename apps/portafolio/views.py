from functools import wraps
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Q
from apps.core.permisos.grupos import usuario_pertenece_a
from .forms import DocumentoForm, ImportarInstrumentoForm, InstrumentoForm, PlantillaPDFForm, PreguntaInstrumentoForm, RecursoCompartidoForm, ReporteForm
from .models import Documento, Instrumento, PlantillaPDF, PreguntaInstrumento, RecursoCompartido, Reporte
from .services_importacion import importar_preguntas_desde_documento
from .services_importacion_instrumentos import importar_archivo_subido

CATALOGOS = {
    'instrumento': (Instrumento, InstrumentoForm, 'portafolio:instrumentos'),
    'documento': (Documento, DocumentoForm, 'portafolio:documentos'),
    'plantilla': (PlantillaPDF, PlantillaPDFForm, 'portafolio:plantillas'),
    'reporte': (Reporte, ReporteForm, 'portafolio:reportes'),
    'recurso': (RecursoCompartido, RecursoCompartidoForm, 'portafolio:recursos'),
}


def acceso_portafolio_requerido(vista):
    @wraps(vista)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not usuario_pertenece_a(request.user, 'Dirección', 'Sistemas', 'Certificación'):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return wrapper


@acceso_portafolio_requerido
def dashboard_view(request):
    return render(request, 'portafolio/dashboard.html', {'vista_actual': 'dashboard', 'totales': [('Instrumentos', Instrumento.objects.count(), 'portafolio:instrumentos'), ('Documentos', Documento.objects.count(), 'portafolio:documentos'), ('Plantillas PDF', PlantillaPDF.objects.count(), 'portafolio:plantillas'), ('Reportes', Reporte.objects.count(), 'portafolio:reportes'), ('Recursos', RecursoCompartido.objects.count(), 'portafolio:recursos')]})


def _catalogo(request, modelo, template, titulo, vista, crear_url, form_class=None, instrumento=None):
    if request.method == 'POST' and form_class:
        form = form_class(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            if instrumento: item.instrumento = instrumento
            item.save()
            if instrumento:
                return redirect('portafolio:preguntas', instrumento_id=instrumento.id)
            return redirect(crear_url)
    items = modelo.all() if hasattr(modelo, 'all') else modelo.objects.all()
    return render(request, template, {'vista_actual': vista, 'titulo': titulo, 'items': items, 'form': form_class() if form_class else None, 'instrumento': instrumento, 'es_instrumento': modelo is Instrumento})


@acceso_portafolio_requerido
def instrumentos_view(request):
    formulario_importacion = ImportarInstrumentoForm()
    if request.method == 'POST' and request.POST.get('accion') == 'importar':
        formulario_importacion = ImportarInstrumentoForm(request.POST, request.FILES)
        if formulario_importacion.is_valid():
            try:
                reporte = importar_archivo_subido(
                    formulario_importacion.cleaned_data['archivo'],
                    cargado_por=request.user,
                )
            except ValidationError as error:
                formulario_importacion.add_error('archivo', '; '.join(error.messages))
            else:
                if reporte['decision'] == 'sin cambios':
                    messages.info(request, 'El instrumento ya se encuentra importado y no presenta cambios.')
                else:
                    messages.success(
                        request,
                        'Instrumento importado correctamente. '
                        f"Versión: {reporte['version']}. "
                        f"Preguntas: {reporte['preguntas']}. "
                        f"Calculadora: {reporte['estado_calculadora']}.",
                    )
                return redirect('portafolio:instrumentos')
    formulario_manual = InstrumentoForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and not request.POST.get('accion') and formulario_manual.is_valid():
        formulario_manual.save()
        return redirect('portafolio:instrumentos')
    return render(
        request,
        'portafolio/catalogo.html',
        {
            'vista_actual': 'instrumentos',
            'titulo': 'Instrumentos',
            'items': Instrumento.objects.all(),
            'form': formulario_manual,
            'formulario_importacion': formulario_importacion,
            'es_instrumento': True,
        },
    )


@acceso_portafolio_requerido
def importar_preguntas_view(request, instrumento_id):
    instrumento = get_object_or_404(Instrumento, id=instrumento_id)
    if request.method != 'POST':
        return redirect('portafolio:instrumentos')
    try:
        total = importar_preguntas_desde_documento(instrumento)
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, f'Se importaron {total} preguntas desde el Documento origen de Portafolio.')
    return redirect('portafolio:instrumentos')
@acceso_portafolio_requerido
def preguntas_view(request, instrumento_id):
    instrumento = get_object_or_404(Instrumento, id=instrumento_id)
    return _catalogo(request, instrumento.preguntas, 'portafolio/catalogo.html', f'Preguntas · {instrumento.nombre}', 'instrumentos', 'portafolio:preguntas', PreguntaInstrumentoForm, instrumento)


@acceso_portafolio_requerido
def pregunta_editar_view(request, pregunta_id):
    pregunta = get_object_or_404(PreguntaInstrumento, id=pregunta_id)
    form = PreguntaInstrumentoForm(request.POST or None, instance=pregunta)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('portafolio:preguntas', instrumento_id=pregunta.instrumento_id)
    return render(request, 'portafolio/editar.html', {'titulo': 'Editar pregunta', 'form': form})


@acceso_portafolio_requerido
def pregunta_eliminar_view(request, pregunta_id):
    pregunta = get_object_or_404(PreguntaInstrumento, id=pregunta_id)
    instrumento_id = pregunta.instrumento_id
    if request.method == 'POST':
        pregunta.delete()
        return redirect('portafolio:preguntas', instrumento_id=instrumento_id)
    return render(request, 'portafolio/eliminar.html', {'item': pregunta})
@acceso_portafolio_requerido
def documentos_view(request):
    form = DocumentoForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        documento = form.save(commit=False); documento.cargado_por = request.user; documento.save()
        return redirect('portafolio:documentos')
    documentos = Documento.objects.select_related('categoria', 'cargado_por').all()
    busqueda = request.GET.get('q', '').strip(); categoria = request.GET.get('categoria', '')
    if busqueda: documentos = documentos.filter(Q(nombre__icontains=busqueda) | Q(descripcion__icontains=busqueda))
    if categoria: documentos = documentos.filter(categoria_id=categoria)
    from .models import CategoriaDocumento
    return render(request, 'portafolio/documentos.html', {'vista_actual': 'documentos', 'form': form, 'items': documentos, 'busqueda': busqueda, 'categoria_actual': categoria, 'categorias': CategoriaDocumento.objects.filter(activa=True)})


@acceso_portafolio_requerido
def documento_descargar_view(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    archivo = documento.archivo
    if not archivo or not archivo.name or not archivo.storage.exists(archivo.name):
        return render(
            request,
            'portafolio/archivo_no_disponible.html',
            {'documento': documento},
            status=404,
        )
    try:
        contenido = archivo.storage.open(archivo.name, 'rb')
    except Exception:
        return render(
            request,
            'portafolio/archivo_no_disponible.html',
            {'documento': documento},
            status=404,
        )
    return FileResponse(
        contenido,
        as_attachment=True,
        filename=Path(archivo.name).name,
    )
@acceso_portafolio_requerido
def plantillas_view(request): return _catalogo(request, PlantillaPDF, 'portafolio/catalogo.html', 'Plantillas PDF', 'plantillas', 'portafolio:plantillas', PlantillaPDFForm)
@acceso_portafolio_requerido
def reportes_view(request): return _catalogo(request, Reporte, 'portafolio/catalogo.html', 'Reportes', 'reportes', 'portafolio:reportes', ReporteForm)
@acceso_portafolio_requerido
def recursos_view(request): return _catalogo(request, RecursoCompartido, 'portafolio/catalogo.html', 'Recursos compartidos', 'recursos', 'portafolio:recursos', RecursoCompartidoForm)


@acceso_portafolio_requerido
def editar_view(request, tipo, item_id):
    modelo, form_class, destino = CATALOGOS[tipo]
    item = get_object_or_404(modelo, id=item_id)
    form = form_class(request.POST or None, request.FILES or None, instance=item)
    if request.method == 'POST' and form.is_valid(): form.save(); return redirect(destino)
    return render(request, 'portafolio/editar.html', {'titulo': f'Editar {item}', 'form': form, 'volver': destino})


@acceso_portafolio_requerido
def eliminar_view(request, tipo, item_id):
    if tipo == 'documento':
        return eliminar_documento_view(request, item_id)
    if tipo == 'instrumento':
        return eliminar_instrumento_view(request, item_id)
    modelo, _, destino = CATALOGOS[tipo]
    item = get_object_or_404(modelo, id=item_id)
    if request.method == 'POST': item.delete(); return redirect(destino)
    return render(request, 'portafolio/eliminar.html', {'item': item, 'volver': destino})


def _referencias_documento(documento):
    referencias = []
    for nombre, descripcion in (
        ('instrumentos_origen', 'un instrumento'),
        ('importaciones_instrumento', 'una importación de instrumento'),
        ('plantillas_pdf', 'una plantilla PDF'),
        ('recursos_compartidos', 'un recurso compartido'),
    ):
        if getattr(documento, nombre).exists():
            referencias.append(descripcion)
    return referencias


def _programar_eliminacion_archivo(archivo):
    if archivo and archivo.name:
        transaction.on_commit(lambda: archivo.storage.delete(archivo.name))


@acceso_portafolio_requerido
def eliminar_documento_view(request, item_id):
    documento = get_object_or_404(Documento, id=item_id)
    referencias = _referencias_documento(documento)
    contexto = {
        'item': documento,
        'titulo': 'Eliminar documento',
        'volver': 'portafolio:documentos',
        'referencias': referencias,
    }
    if referencias:
        contexto['mensaje_bloqueo'] = (
            'Este documento está siendo utilizado por ' + ', '.join(referencias) +
            ' y no puede eliminarse.'
        )
        if request.method == 'POST':
            messages.error(request, contexto['mensaje_bloqueo'])
            return redirect('portafolio:documentos')
        return render(request, 'portafolio/eliminar.html', contexto)
    if request.method == 'POST':
        archivo = documento.archivo
        with transaction.atomic():
            documento.delete()
            _programar_eliminacion_archivo(archivo)
        messages.success(request, 'Documento eliminado correctamente.')
        return redirect('portafolio:documentos')
    return render(request, 'portafolio/eliminar.html', contexto)


def _referencias_instrumento(instrumento):
    referencias = []
    if instrumento.configuraciones_intera.exists():
        referencias.append('configuraciones de procesos de certificación')
    if instrumento.aplicaciones_intera.exists():
        referencias.append('aplicaciones de Certificación INTERA')
    if instrumento.entrevistaunoauno_set.exists():
        referencias.append('entrevistas 1:1')
    if instrumento.preguntas.filter(respuestas_intera__isnull=False).exists():
        referencias.append('respuestas de instrumentos')
    if instrumento.preguntas.filter(respuestaentrevistaunoauno__isnull=False).exists():
        referencias.append('respuestas de entrevistas 1:1')
    if instrumento.revisiones.filter(entrevistaunoauno__isnull=False).exists():
        referencias.append('revisiones usadas por entrevistas 1:1')
    return referencias


@acceso_portafolio_requerido
def eliminar_instrumento_view(request, item_id):
    instrumento = get_object_or_404(Instrumento, id=item_id)
    referencias = _referencias_instrumento(instrumento)
    contexto = {
        'item': instrumento,
        'titulo': 'Eliminar instrumento',
        'volver': 'portafolio:instrumentos',
    }
    if referencias:
        contexto['mensaje_bloqueo'] = (
            'Este instrumento tiene historial en ' + ', '.join(referencias) +
            ' y no puede eliminarse. Puedes desactivarlo para impedir nuevas aplicaciones.'
        )
        if request.method == 'POST':
            messages.error(request, contexto['mensaje_bloqueo'])
            return redirect('portafolio:instrumentos')
        return render(request, 'portafolio/eliminar.html', contexto)
    if request.method == 'POST':
        documento = instrumento.documento_origen
        try:
            documento_importado = instrumento.importacion.documento_id == instrumento.documento_origen_id
        except Instrumento.importacion.RelatedObjectDoesNotExist:
            documento_importado = False
        with transaction.atomic():
            instrumento.calculadoras.all().delete()
            instrumento.revisiones.all().delete()
            instrumento.delete()
            if documento_importado and documento and not _referencias_documento(documento):
                archivo = documento.archivo
                documento.delete()
                _programar_eliminacion_archivo(archivo)
        messages.success(request, 'Instrumento eliminado correctamente.')
        return redirect('portafolio:instrumentos')
    return render(request, 'portafolio/eliminar.html', contexto)
