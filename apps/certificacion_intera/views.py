from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO

import qrcode
from qrcode.image.svg import SvgPathImage
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.crypto import get_random_string

from apps.core.permisos.grupos import usuario_pertenece_a
from .forms import (
    CanalizacionForm,
    ConfiguracionInstrumentoForm,
    ConsejeriaForm,
    EntrevistaSeguimientoForm,
    EscuelaForm,
    FechaNacimientoPublicoForm,
    ParticipanteForm,
    ParticipantePublicoForm,
    ProcesoCertificacionForm,
    SexoBaremoPublicoForm,
)
from .models import (
    AplicacionInstrumento,
    AplicacionPublica,
    BitacoraProceso,
    Canalizacion,
    ConfiguracionInstrumento,
    Consejeria,
    EntrevistaSeguimiento,
    Escuela,
    ResultadoInstrumento,
    Participante,
    ProcesoCertificacion,
    RespuestaInstrumento,
)
from .instrumentos import (
    CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO,
    excluir_instrumentos_de_flujo_interno,
)
from apps.portafolio.models import (
    CalculadoraInstrumento,
    Instrumento,
    PreguntaInstrumento,
)
from apps.portafolio.services_calificacion import (
    calcular_resultado,
    campos_contexto_requeridos,
    obtener_revision_resultado,
)
from .services import (
    cerrar_proceso,
    obtener_aplicacion_publica,
    obtener_aplicacion_publica_proceso,
    proceso_es_editable,
)


BATERIA_PUBLICA_VIGENTE = (
    (
        'dass-21-adolescentes',
        'DASS-21 · Adolescentes',
        21,
        CalculadoraInstrumento.Estado.ORIENTATIVA,
    ),
    (
        'rse-autoestima',
        'Escala de Autoestima de Rosenberg · Adolescentes',
        10,
        CalculadoraInstrumento.Estado.ORIENTATIVA,
    ),
    (
        'scid-ii-adolescentes',
        'SCID-II · Adolescentes',
        119,
        CalculadoraInstrumento.Estado.NO_DIAGNOSTICA,
    ),
    (
        'ersp-plutchik-adolescentes',
        'Escala de Riesgo Suicida de Plutchik · Adolescentes',
        15,
        CalculadoraInstrumento.Estado.ORIENTATIVA,
    ),
)


def acceso_certificacion_intera_requerido(vista):
    @wraps(vista)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not usuario_pertenece_a(
            request.user,
            'Certificación',
            'Dirección',
            'Sistemas',
        ):
            raise PermissionDenied
        return vista(
            request,
            *args,
            **kwargs,
        )
    return wrapper


def _proceso(proceso_id):
    return get_object_or_404(
        ProcesoCertificacion.objects.select_related('escuela'),
        id=proceso_id,
    )


def _participante(participante_id):
    return get_object_or_404(
        Participante.objects.select_related('proceso__escuela'),
        id=participante_id,
    )


def _url_retorno_segura(request, default):
    retorno = request.GET.get('return_url') or request.POST.get('return_url')
    if (
        retorno
        and url_has_allowed_host_and_scheme(retorno, {request.get_host()})
    ):
        return retorno
    return default


def _progreso_bateria(proceso):
    participantes = list(proceso.participantes.prefetch_related('aplicaciones'))
    completos = sum(
        (
            (
                bool(p.aplicaciones.exists())
                and not p.aplicaciones.filter(estado=AplicacionInstrumento.Estado.PENDIENTE).exists()
            )
            for p in participantes
        ),
    )
    total = len(participantes)
    return (
        completos,
        total,
        round(completos / total * 100) if total else 0,
    )


def _pagina(request, queryset):
    return Paginator(queryset, 15).get_page(request.GET.get('page'))


def _coincidencias_escuela(datos):
    """Busca coincidencias exactas normalizadas sin modificar registros existentes."""
    nombre = ' '.join(datos.get('nombre', '').split())
    coincidencias = Escuela.objects.none()
    if nombre:
        coincidencias = coincidencias | Escuela.objects.filter(nombre__iexact=nombre)
    for campo in ('correo', 'telefono'):
        valor = datos.get(campo, '').strip()
        if valor:
            coincidencias = coincidencias | Escuela.objects.filter(**{f'{campo}__iexact': valor})
    return coincidencias.distinct()


def _revision_escuela_clave(token):
    return f'intera_revision_escuela_{token}'


def _entrevistas_pendientes(participantes):
    """Batería completa y sin entrevista de seguimiento registrada."""
    total = 0
    for participante in participantes:
        aplicaciones = list(participante.aplicaciones.all())
        if (
            aplicaciones
            and all(
                (a.estado == AplicacionInstrumento.Estado.RESPONDIDA for a in aplicaciones),
            )
            and not hasattr(participante, 'entrevista')
        ):
            total += 1
    return total


def _proceso_editable_o_redirigir(request, proceso):
    if proceso_es_editable(proceso):
        return None
    messages.error(
        request,
        'Este proceso está cerrado y se encuentra disponible solo para consulta.',
    )
    return redirect(
        'certificacion_intera:proceso_detalle',
        proceso_id=proceso.id,
    )


def _instrumentos_para_bateria():
    instrumentos = excluir_instrumentos_de_flujo_interno(
        Instrumento.objects.filter(activo=True),
    ).annotate(
        numero_reactivos=Count('preguntas'),
    ).prefetch_related('calculadoras').order_by('nombre', 'version', 'id')
    etiquetas = {
        CalculadoraInstrumento.Estado.ACTIVA: 'Calculadora activa',
        CalculadoraInstrumento.Estado.ORIENTATIVA: 'Calculadora orientativa',
        CalculadoraInstrumento.Estado.NO_DIAGNOSTICA: 'Calculadora no diagnóstica',
        CalculadoraInstrumento.Estado.BLOQUEADA: 'Calculadora bloqueada',
    }
    disponibles = []
    for instrumento in instrumentos:
        calculadoras = list(instrumento.calculadoras.all())
        estado = calculadoras[0].estado if len(calculadoras) == 1 else None
        disponibles.append({
            'instrumento': instrumento,
            'nombre_visible': instrumento.nombre,
            'variante_visible': '',
            'numero_reactivos': instrumento.numero_reactivos,
            'estado_calculadora': estado,
            'estado_calculadora_display': etiquetas.get(
                estado, 'Sin calculadora' if not calculadoras else 'Calculadoras múltiples',
            ),
            'seleccionable': True,
            'bloqueado': False,
        })
    return disponibles, instrumentos

    # Historial de catálogo restringido; se deja inalcanzable temporalmente.
    """Catálogo público vigente, validado con trazabilidad de Portafolio."""
    instrumentos = {
        instrumento.clave: instrumento
        for instrumento in Instrumento.objects.filter(
            clave__in=[clave for clave, *_ in BATERIA_PUBLICA_VIGENTE],
            activo=True,
        ).annotate(
            numero_reactivos=Count('preguntas'),
        ).prefetch_related(
            'calculadoras',
        ).select_related(
            'importacion',
        )
    }
    disponibles, ids_seleccionables = ([], [])
    for clave, nombre_visible, reactivos_esperados, estado_esperado in BATERIA_PUBLICA_VIGENTE:
        instrumento = instrumentos.get(clave)
        if not instrumento:
            continue
        try:
            importacion = instrumento.importacion
        except Instrumento.importacion.RelatedObjectDoesNotExist:
            continue
        metadatos = importacion.metadatos or {}
        evidencia_variante = ' '.join((str(valor) for valor in metadatos.values())).lower()
        reactivos_trazables = (
            metadatos.get('Número de reactivos')
            or metadatos.get('numero_reactivos')
        )
        try:
            reactivos_trazables = int(reactivos_trazables)
        except (TypeError, ValueError):
            reactivos_trazables = None
        calculadoras = [
            calculadora
            for calculadora in instrumento.calculadoras.all()
            if calculadora.estado == estado_esperado
        ]
        if (
            'adolesc' not in evidencia_variante
            or instrumento.numero_reactivos != reactivos_esperados
            or reactivos_trazables != reactivos_esperados
            or len(calculadoras) != 1
        ):
            continue
        calculadora = calculadoras[0]
        bloqueado = estado_esperado == CalculadoraInstrumento.Estado.BLOQUEADA
        seleccionable = not bloqueado
        if seleccionable:
            ids_seleccionables.append(instrumento.id)
        disponibles.append(
            {
                'instrumento': instrumento,
                'nombre_visible': nombre_visible,
                'variante_visible': 'Variante adolescente',
                'numero_reactivos': instrumento.numero_reactivos,
                'estado_calculadora': calculadora.estado,
                'estado_calculadora_display': {
                    CalculadoraInstrumento.Estado.ACTIVA: 'Calculadora activa',
                    CalculadoraInstrumento.Estado.ORIENTATIVA: 'Calculadora orientativa',
                    CalculadoraInstrumento.Estado.NO_DIAGNOSTICA: 'Calculadora no diagnóstica',
                    CalculadoraInstrumento.Estado.BLOQUEADA: 'Calculadora bloqueada',
                }[calculadora.estado],
                'seleccionable': seleccionable,
                'bloqueado': bloqueado,
            },
        )
    return (
        disponibles,
        Instrumento.objects.filter(id__in=ids_seleccionables),
    )


def _orden_bateria_post(request, instrumentos):
    valores = request.POST.getlist('instrumentos')
    if len(valores) != len(set(valores)):
        raise ValueError('No es posible repetir un instrumento en la batería.')
    ordenes = []
    for instrumento in instrumentos:
        valor = request.POST.get(f'orden_{instrumento.id}', '').strip()
        try:
            orden = int(valor)
        except (TypeError, ValueError):
            raise ValueError('Asigna un orden a cada instrumento seleccionado.')
        if orden < 1:
            raise ValueError('El orden de aplicación debe iniciar en 1.')
        ordenes.append(orden)
    if len(ordenes) != len(set(ordenes)):
        raise ValueError('No puede haber órdenes repetidos.')
    if sorted(ordenes) != list(range(1, len(ordenes) + 1)):
        raise ValueError('El orden debe ser consecutivo, comenzando en 1.')
    return dict(zip((instrumento.id for instrumento in instrumentos), ordenes))


@acceso_certificacion_intera_requerido


def dashboard_view(request):
    procesos = ProcesoCertificacion.objects.select_related('escuela').all()
    activos = procesos.exclude(estado=ProcesoCertificacion.Estado.CERRADO)
    aplicaciones = AplicacionInstrumento.objects.exclude(
        instrumento__clave__in=CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO,
    )
    completadas = aplicaciones.filter(estado=AplicacionInstrumento.Estado.RESPONDIDA).count()
    pendientes_entrevista = Participante.objects.filter(entrevista__isnull=True).count()
    pendientes = []
    for proceso in activos[:10]:
        if not proceso.configuraciones_instrumento.exists():
            pendientes.append(
                {
                    'titulo': f'{proceso.escuela.nombre} · {proceso.ciclo_escolar or proceso.nombre}',
                    'situacion': 'Falta configurar la batería',
                    'url': reverse('certificacion_intera:configuracion', args=[proceso.id]),
                    'accion': 'Configurar proceso',
                },
            )
    for participante in Participante.objects.filter(entrevista__isnull=True).prefetch_related(
        'aplicaciones',
    )[:10]:
        if (
            participante.aplicaciones.exists()
            and not participante.aplicaciones.filter(
                estado=AplicacionInstrumento.Estado.PENDIENTE,
            ).exists()
        ):
            pendientes.append(
                {
                    'titulo': participante.nombre,
                    'situacion': 'Batería completada; requiere entrevista',
                    'url': reverse(
                        'certificacion_intera:proceso_detalle',
                        args=[participante.proceso_id],
                    ) + '?tab=entrevistas',
                    'accion': 'Revisar proceso',
                },
            )
    return render(
        request,
        'certificacion_intera/dashboard.html',
        {
            'vista_actual': 'dashboard',
            'total_escuelas': Escuela.objects.count(),
            'participantes_registrados': Participante.objects.count(),
            'procesos_activos': activos.count(),
            'baterias_completadas': completadas,
            'entrevistas_pendientes': pendientes_entrevista,
            'seguimientos_pendientes': Consejeria.objects.filter(estado=Consejeria.Estado.PENDIENTE).count(),
            'trabajo_pendiente': pendientes[:5],
            'escuelas_recientes': Escuela.objects.order_by('-fecha_registro')[:5],
            'procesos_recientes': activos.order_by('-creado_en')[:5],
        },
    )


@acceso_certificacion_intera_requerido


def escuelas_view(request):
    seleccion_proceso = (
        request.GET.get('accion') == 'crear_proceso'
        or request.GET.get('modo') == 'crear_proceso'
    )
    retorno = (
        _url_retorno_segura(
            request,
            reverse('certificacion_intera:dashboard'),
        )
        if seleccion_proceso
        else None
    )
    q = request.GET.get('q', '').strip()
    escuelas = Escuela.objects.annotate(
        procesos_activos=Count(
            'procesos',
            filter=~Q(procesos__estado=ProcesoCertificacion.Estado.CERRADO),
        ),
    ).all()
    if q:
        for term in q.split():
            escuelas = escuelas.filter(
                Q(nombre__icontains=term)
                | Q(municipio__icontains=term)
                | Q(estado__icontains=term)
                | Q(contacto__icontains=term)
                | Q(correo__icontains=term)
                | Q(telefono__icontains=term),
            )
    if request.GET.get('estado'):
        escuelas = escuelas.filter(estado__iexact=request.GET['estado'])
    if request.GET.get('municipio'):
        escuelas = escuelas.filter(municipio__icontains=request.GET['municipio'].strip())
    if request.GET.get('proceso') == 'activo':
        escuelas = escuelas.filter(procesos_activos__gt=0)
    if request.GET.get('proceso') == 'sin_activo':
        escuelas = escuelas.filter(procesos_activos=0)
    return render(
        request,
        'certificacion_intera/escuelas.html',
        {
            'vista_actual': 'escuelas',
            'escuelas': _pagina(request, escuelas.order_by('nombre')),
            'q': q,
            'filtros': request.GET,
            'estados': Escuela.objects.values_list('estado', flat=True).distinct().order_by(
                'estado',
            ),
            'seleccion_proceso': seleccion_proceso,
            'return_url': retorno,
        },
    )


@acceso_certificacion_intera_requerido


def procesos_view(request):
    q = request.GET.get('q', '').strip()
    procesos = ProcesoCertificacion.objects.select_related('escuela').all()
    if q:
        procesos = procesos.filter(
            Q(nombre__icontains=q) | Q(ciclo_escolar__icontains=q) | Q(escuela__nombre__icontains=q),
        )
    if request.GET.get('escuela'):
        procesos = procesos.filter(escuela_id=request.GET['escuela'])
    if request.GET.get('estado'):
        procesos = procesos.filter(estado=request.GET['estado'])
    if request.GET.get('periodo'):
        procesos = procesos.filter(ciclo_escolar__icontains=request.GET['periodo'])
    return render(
        request,
        'certificacion_intera/listado.html',
        {
            'vista_actual': 'procesos',
            'titulo_listado': 'Procesos de certificación',
            'descripcion_listado': 'Consulta los procesos registrados y entra a su expediente.',
            'elementos': _pagina(request, procesos.order_by('-fecha_inicio')),
            'tipo_listado': 'procesos',
            'q': q,
            'escuelas_filtro': Escuela.objects.all(),
            'estados_proceso': ProcesoCertificacion.Estado.choices,
            'filtros': request.GET,
        },
    )


@acceso_certificacion_intera_requerido


def participantes_view(request):
    return render(
        request,
        'certificacion_intera/listado.html',
        {
            'vista_actual': 'participantes',
            'titulo_listado': 'Participantes',
            'descripcion_listado': 'Consulta los participantes de los procesos de certificación.',
            'elementos': Participante.objects.select_related('proceso__escuela').all(),
            'tipo_listado': 'participantes',
        },
    )


@acceso_certificacion_intera_requerido


def entrevistas_view(request):
    return render(
        request,
        'certificacion_intera/listado.html',
        {
            'vista_actual': 'entrevistas',
            'titulo_listado': 'Entrevistas',
            'descripcion_listado': 'Consulta las entrevistas de seguimiento registradas.',
            'elementos': EntrevistaSeguimiento.objects.select_related(
                'participante__proceso__escuela',
            ).all(),
            'tipo_listado': 'entrevistas',
        },
    )


@acceso_certificacion_intera_requerido


def seguimiento_view(request):
    return render(
        request,
        'certificacion_intera/listado.html',
        {
            'vista_actual': 'seguimiento',
            'titulo_listado': 'Seguimiento',
            'descripcion_listado': 'Consulta las consejerías de los participantes.',
            'elementos': Consejeria.objects.select_related('participante__proceso__escuela').all(),
            'tipo_listado': 'seguimiento',
        },
    )


@acceso_certificacion_intera_requerido


def configuracion_general_view(request):
    return render(
        request,
        'certificacion_intera/listado.html',
        {
            'vista_actual': 'configuracion',
            'titulo_listado': 'Configuración de instrumentos',
            'descripcion_listado': 'Consulta las configuraciones activas por proceso.',
            'elementos': ConfiguracionInstrumento.objects.select_related(
                'proceso__escuela',
                'instrumento',
            ).all(),
            'tipo_listado': 'configuracion',
        },
    )


@acceso_certificacion_intera_requerido


def escuela_crear_view(request):
    form = EscuelaForm(request.POST or None)
    if False:
        permitidos = {
            str(instrumento_id)
            for instrumento_id in instrumentos_seleccionables.values_list('id', flat=True)
        }
        if any(
            (valor not in permitidos for valor in request.POST.getlist('instrumentos')),
        ):
            form.add_error(
                'instrumentos',
                'Este instrumento no está disponible para esta batería.',
            )
    if request.method == 'POST' and form.is_valid():
        coincidencias = _coincidencias_escuela(form.cleaned_data)
        if coincidencias.exists():
            token = get_random_string(32)
            request.session[_revision_escuela_clave(token)] = {
                'datos': form.cleaned_data,
                'creado_en': timezone.now().timestamp(),
                'return_url': _url_retorno_segura(request, reverse('certificacion_intera:escuelas')),
            }
            return render(
                request,
                'certificacion_intera/escuela_coincidencias.html',
                {
                    'form': form,
                    'coincidencias': coincidencias,
                    'datos': request.POST,
                    'revision_token': token,
                },
            )
        escuela = form.save()
        messages.success(request, 'La escuela se registró correctamente.')
        return redirect(
            'certificacion_intera:escuela_detalle',
            escuela_id=escuela.id,
        )
    return render(
        request,
        'certificacion_intera/form.html',
        {
            'vista_actual': 'escuelas',
            'form': form,
            'titulo_formulario': 'Registrar escuela',
            'volver_url': reverse('certificacion_intera:escuelas'),
        },
    )


@acceso_certificacion_intera_requerido


def escuela_confirmar_view(request):
    if request.method != 'POST':
        raise PermissionDenied
    token = request.POST.get('revision_token', '')
    revision = request.session.get(_revision_escuela_clave(token))
    if (
        not revision
        or timezone.now().timestamp() - revision['creado_en'] > 20 * 60
    ):
        messages.error(
            request,
            'La revisión expiró. Captura nuevamente los datos de la escuela.',
        )
        if token:
            request.session.pop(_revision_escuela_clave(token), None)
        return redirect('certificacion_intera:escuela_crear')
    form = EscuelaForm(revision['datos'])
    if not form.is_valid():
        request.session.pop(_revision_escuela_clave(token), None)
        messages.error(
            request,
            'No fue posible validar la revisión de la escuela.',
        )
        return redirect('certificacion_intera:escuela_crear')
    request.session.pop(_revision_escuela_clave(token), None)
    escuela = form.save()
    messages.success(request, 'Escuela registrada correctamente.')
    return redirect(
        'certificacion_intera:escuela_detalle',
        escuela_id=escuela.id,
    )


@acceso_certificacion_intera_requerido


def escuela_detalle_view(request, escuela_id):
    escuela = get_object_or_404(Escuela, id=escuela_id)
    tab = request.GET.get('tab', 'resumen')
    if tab not in {
        'resumen',
        'datos',
        'contactos',
        'procesos',
        'historial',
    }:
        tab = 'resumen'
    procesos = escuela.procesos.prefetch_related('participantes__aplicaciones').all()
    participantes_registrados = Participante.objects.filter(proceso__escuela=escuela).count()
    procesos_activos = procesos.exclude(estado=ProcesoCertificacion.Estado.CERRADO).count()
    historial = BitacoraProceso.objects.filter(proceso__escuela=escuela).select_related(
        'usuario',
    ).order_by(
        '-creado_en',
    )[:20]
    return render(
        request,
        'certificacion_intera/escuela_detalle.html',
        {
            'vista_actual': 'escuelas',
            'escuela': escuela,
            'procesos': procesos,
            'tab': tab,
            'participantes_registrados': participantes_registrados,
            'procesos_activos': procesos_activos,
            'historial': historial,
            'return_url': _url_retorno_segura(request, reverse('certificacion_intera:escuelas')),
        },
    )


@acceso_certificacion_intera_requerido


def escuela_editar_view(request, escuela_id):
    escuela = get_object_or_404(Escuela, id=escuela_id)
    form = EscuelaForm(request.POST or None, instance=escuela)
    if request.method == 'POST' and form.is_valid():
        escuela = form.save()
        messages.success(request, 'La escuela se actualizó correctamente.')
        return redirect(
            'certificacion_intera:escuela_detalle',
            escuela_id=escuela.id,
        )
    return render(
        request,
        'certificacion_intera/form.html',
        {
            'vista_actual': 'escuelas',
            'form': form,
            'titulo_formulario': 'Editar escuela',
            'volver_url': reverse('certificacion_intera:escuela_detalle', args=[escuela.id]),
        },
    )


@acceso_certificacion_intera_requerido


def proceso_crear_view(request, escuela_id=None):
    escuela_preseleccionada = get_object_or_404(Escuela, id=escuela_id) if escuela_id else None
    bateria, instrumentos_seleccionables = _instrumentos_para_bateria()
    seleccionados_post = (
        set(request.POST.getlist('instrumentos'))
        if request.method == 'POST'
        else set()
    )
    for item in bateria:
        item['seleccionada'] = str(item['instrumento'].id) in seleccionados_post
        item['orden'] = (
            request.POST.get(f"orden_{item['instrumento'].id}", '')
            if request.method == 'POST'
            else ''
        )
    form = ProcesoCertificacionForm(
        request.POST or None,
        instrumentos_disponibles=instrumentos_seleccionables,
        escuela_preseleccionada=escuela_preseleccionada,
        initial={'fecha_cierre': None},
    )
    volver_url = (
        reverse(
            'certificacion_intera:escuela_detalle',
            args=[escuela_preseleccionada.id],
        )
        if escuela_preseleccionada
        else reverse('certificacion_intera:dashboard')
    )
    return_url = _url_retorno_segura(request, volver_url)
    formulario_valido = form.is_valid() if request.method == 'POST' else False
    if request.method == 'POST' and (not formulario_valido):
        permitidos = {
            str(instrumento_id)
            for instrumento_id in instrumentos_seleccionables.values_list('id', flat=True)
        }
        if any(
            (valor not in permitidos for valor in request.POST.getlist('instrumentos')),
        ):
            form.add_error(
                'instrumentos',
                'Este instrumento no está disponible para esta batería.',
            )
    if request.method == 'POST' and formulario_valido:
        instrumentos = list(form.cleaned_data['instrumentos'])
        escuela = escuela_preseleccionada or form.cleaned_data.get('escuela')
        if form.cleaned_data.get('fecha_cierre'):
            form.add_error(
                'fecha_cierre',
                'La fecha de cierre debe permanecer vacía durante el alta del proceso.',
            )
        try:
            ordenes = _orden_bateria_post(request, instrumentos)
        except ValueError as error:
            form.add_error('instrumentos', str(error))
        else:
            if not form.errors:
                try:
                    with transaction.atomic():
                        proceso = form.save(commit=False)
                        proceso.escuela = escuela
                        proceso.estado = ProcesoCertificacion.Estado.CONFIGURACION
                        proceso.fecha_cierre = None
                        proceso.creado_por = request.user
                        proceso.full_clean()
                        proceso.save()
                        ConfiguracionInstrumento.objects.bulk_create(
                            [
                                ConfiguracionInstrumento(
                                    proceso=proceso,
                                    instrumento=instrumento,
                                    orden=ordenes[instrumento.id],
                                )
                                for instrumento in instrumentos
                            ],
                        )
                        BitacoraProceso.objects.create(
                            proceso=proceso,
                            evento='Proceso creado',
                            descripcion='Proceso creado con batería inicial de evaluación.',
                            usuario=request.user,
                        )
                except Exception as error:
                    form.add_error(None, f'No fue posible crear el proceso: {error}')
                else:
                    messages.success(
                        request,
                        'El proceso de certificación y su batería inicial se crearon correctamente.',
                    )
                    return redirect(
                        'certificacion_intera:proceso_detalle',
                        proceso_id=proceso.id,
                    )
    return render(
        request,
        'certificacion_intera/proceso_form.html',
        {
            'vista_actual': 'escuelas',
            'form': form,
            'bateria': bateria,
            'escuela_preseleccionada': escuela_preseleccionada,
            'volver_url': return_url,
            'return_url': return_url,
        },
    )


@acceso_certificacion_intera_requerido


def proceso_detalle_view(request, proceso_id):
    proceso = _proceso(proceso_id)
    tab = request.GET.get('tab', 'resumen')
    if tab not in {
        'resumen',
        'participantes',
        'bateria',
        'entrevistas',
        'seguimiento',
        'configuracion',
        'bitacora',
    }:
        tab = 'resumen'
    aplicaciones = proceso.aplicaciones.select_related('participante', 'instrumento')
    participantes = proceso.participantes.annotate(
        total_aplicaciones=Count('aplicaciones'),
    ).prefetch_related(
        'aplicaciones',
        'consejerias',
        'canalizaciones',
    ).all()
    configuraciones = list(
        proceso.configuraciones_instrumento.select_related(
            'instrumento',
            'aplicacion_publica',
        ).exclude(
            instrumento__clave__in=CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO,
        ),
    )
    tarjetas_instrumento = []
    for configuracion in configuraciones:
        aplicaciones_instrumento = aplicaciones.filter(instrumento=configuracion.instrumento)
        publica, _ = obtener_aplicacion_publica(configuracion, request.user)
        tarjetas_instrumento.append(
            {
                'configuracion': configuracion,
                'preguntas': configuracion.instrumento.preguntas.count(),
                'participantes': aplicaciones_instrumento.count(),
                'respondidos': aplicaciones_instrumento.filter(
                    estado=AplicacionInstrumento.Estado.RESPONDIDA,
                ).count(),
                'pendientes': aplicaciones_instrumento.filter(
                    estado=AplicacionInstrumento.Estado.PENDIENTE,
                ).count(),
                'url_publica': request.build_absolute_uri(publica.url_publica),
            },
        )
    entrevistas = EntrevistaSeguimiento.objects.filter(participante__proceso=proceso).select_related(
        'participante',
    )
    consejerias = Consejeria.objects.filter(participante__proceso=proceso).select_related(
        'participante',
    )
    canalizaciones = Canalizacion.objects.filter(participante__proceso=proceso).select_related(
        'participante',
    )
    respondidas = aplicaciones.filter(estado=AplicacionInstrumento.Estado.RESPONDIDA)
    participantes_workflow = []
    for participante in participantes:
        aplicaciones_participante = list(participante.aplicaciones.all())
        respondidos_participante = sum(
            (a.estado == AplicacionInstrumento.Estado.RESPONDIDA for a in aplicaciones_participante),
        )
        entrevista = next(
            (e for e in entrevistas if e.participante_id == participante.id),
            None,
        )
        consejerias_participante = list(participante.consejerias.all())
        canalizacion = next(iter(participante.canalizaciones.all()), None)
        pendiente = (
            'Pendiente de responder'
            if any(
                (a.estado == AplicacionInstrumento.Estado.PENDIENTE for a in aplicaciones_participante),
            )
            else (
                'Pendiente de entrevista'
                if not entrevista
                else (
                    'Pendiente de consejería'
                    if (
                        entrevista.decision == EntrevistaSeguimiento.Decision.CONSEJERIA
                        and len(consejerias_participante) < 3
                    )
                    else (
                        'Pendiente de canalización'
                        if (
                            entrevista.decision == EntrevistaSeguimiento.Decision.CONSEJERIA
                            and len(consejerias_participante) >= 3
                            and not canalizacion
                        )
                        else 'Al día'
                    )
                )
            )
        )
        participantes_workflow.append(
            {
                'participante': participante,
                'respondidos': respondidos_participante,
                'total': len(aplicaciones_participante),
                'entrevista': entrevista,
                'consejerias': consejerias_participante,
                'canalizacion': canalizacion,
                'pendiente': pendiente,
            },
        )
    completos, total_participantes, progreso_bateria = _progreso_bateria(proceso)
    entrevistas_pendientes = _entrevistas_pendientes(participantes)
    aplicacion_publica_general = AplicacionPublica.objects.filter(proceso=proceso).first()
    url_publica_general = (
        request.build_absolute_uri(aplicacion_publica_general.url_publica)
        if aplicacion_publica_general
        else ''
    )
    return render(
        request,
        'certificacion_intera/proceso_detalle.html',
        {
            'vista_actual': 'procesos',
            'proceso': proceso,
            'tab': tab,
            'progreso_bateria': progreso_bateria,
            'baterias_completas': completos,
            'total_participantes': total_participantes,
            'entrevistas_pendientes': entrevistas_pendientes,
            'proceso_cerrado': not proceso_es_editable(proceso),
            'participantes': participantes,
            'participantes_workflow': participantes_workflow,
            'configuraciones': configuraciones,
            'tarjetas_instrumento': tarjetas_instrumento,
            'aplicacion_publica_general': aplicacion_publica_general,
            'url_publica_general': url_publica_general,
            'aplicaciones': aplicaciones[:12],
            'resultados': respondidas[:12],
            'entrevistas': entrevistas[:12],
            'consejerias': consejerias[:12],
            'canalizaciones': canalizaciones[:12],
            'indicadores': {
                'instrumentos': len(configuraciones),
                'participantes': participantes.count(),
                'respondidos': respondidas.count(),
                'pendientes': aplicaciones.filter(estado=AplicacionInstrumento.Estado.PENDIENTE).count(),
                'entrevistas': entrevistas.count(),
                'consejerias': consejerias.count(),
                'canalizaciones': canalizaciones.count(),
            },
        },
    )


@acceso_certificacion_intera_requerido


def proceso_cerrar_view(request, proceso_id):
    proceso = _proceso(proceso_id)
    if request.method == 'POST':
        with transaction.atomic():
            proceso = ProcesoCertificacion.objects.select_for_update().get(
                id=proceso.id,
            )
            cerrado = cerrar_proceso(proceso, request.user)
        if cerrado:
            messages.success(request, 'El proceso de certificación ha finalizado.')
        return redirect(
            'certificacion_intera:proceso_detalle',
            proceso_id=proceso.id,
        )
    if not proceso_es_editable(proceso):
        return redirect(
            'certificacion_intera:proceso_detalle',
            proceso_id=proceso.id,
        )
    return render(
        request,
        'certificacion_intera/proceso_cerrar.html',
        {
            'vista_actual': 'procesos',
            'proceso': proceso,
        },
    )


def _configuraciones_publicas(proceso):
    """La misma secuencia configurada para la batería; nunca crea otra lista."""
    return list(
        proceso.configuraciones_instrumento.select_related('instrumento').filter(
            estado=ConfiguracionInstrumento.Estado.ACTIVA,
            orden__gt=0,
        ).exclude(
            instrumento__clave__in=CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO,
        ).order_by(
            'orden',
            'id',
        ),
    )


def _sesion_publica_clave(publica):
    return f'intera_bateria_publica_{publica.token}'


@acceso_certificacion_intera_requerido


def aplicacion_publica_proceso_generar_view(request, proceso_id):
    proceso = _proceso(proceso_id)
    if request.method != 'POST':
        raise PermissionDenied
    if not proceso_es_editable(proceso):
        messages.error(
            request,
            'Este proceso está cerrado y se encuentra disponible solo para consulta.',
        )
    else:
        obtener_aplicacion_publica_proceso(proceso, request.user)
        messages.success(
            request,
            'El enlace público general está disponible.',
        )
    return redirect(
        f"{reverse('certificacion_intera:proceso_detalle', args=[proceso.id])}?tab=bateria",
    )


@acceso_certificacion_intera_requerido


def aplicacion_publica_proceso_qr_view(request, proceso_id):
    proceso = _proceso(proceso_id)
    publica = get_object_or_404(AplicacionPublica, proceso=proceso)
    url_publica = request.build_absolute_uri(publica.url_publica)
    imagen = qrcode.make(
        url_publica,
        image_factory=SvgPathImage,
        box_size=10,
        border=4,
    )
    contenido = BytesIO()
    imagen.save(contenido)
    respuesta = HttpResponse(
        contenido.getvalue(),
        content_type='image/svg+xml',
    )
    if request.GET.get('descargar') == '1':
        respuesta['Content-Disposition'] = (
            f'attachment; filename="acceso-intera-{proceso.id}.svg"'
        )
    return respuesta


@acceso_certificacion_intera_requerido


def aplicacion_publica_proceso_estado_view(request, proceso_id):
    proceso = _proceso(proceso_id)
    if request.method != 'POST':
        raise PermissionDenied
    publica = get_object_or_404(AplicacionPublica, proceso=proceso)
    if not proceso_es_editable(proceso):
        messages.error(
            request,
            'Este proceso está cerrado y se encuentra disponible solo para consulta.',
        )
    else:
        activar = request.POST.get('accion') == 'activar'
        publica.estado = (
            AplicacionPublica.Estado.ACTIVA
            if activar
            else AplicacionPublica.Estado.CERRADA
        )
        publica.save(update_fields=['estado'])
        if (
            activar
            and proceso.estado == ProcesoCertificacion.Estado.CONFIGURACION
        ):
            proceso.estado = ProcesoCertificacion.Estado.APLICACION
            proceso.save(update_fields=['estado', 'actualizado_en'])
        BitacoraProceso.objects.create(
            proceso=proceso,
            evento=(
                'Aplicación pública activada'
                if activar
                else 'Aplicación pública desactivada'
            ),
            usuario=request.user,
        )
    return redirect(
        f"{reverse('certificacion_intera:proceso_detalle', args=[proceso.id])}?tab=bateria",
    )


def aplicacion_publica_proceso_view(request, publica):
    proceso = publica.proceso
    if (
        publica.estado != AplicacionPublica.Estado.ACTIVA
        or proceso.estado == ProcesoCertificacion.Estado.CERRADO
    ):
        return render(
            request,
            'certificacion_intera/aplicacion_bateria_publica.html',
            {'pantalla': 'finalizada'},
        )
    configuraciones = _configuraciones_publicas(proceso)
    if not configuraciones:
        return render(
            request,
            'certificacion_intera/aplicacion_bateria_publica.html',
            {
                'pantalla': 'sin_instrumentos',
                'proceso': proceso,
            },
        )
    clave_sesion = _sesion_publica_clave(publica)
    participante_id = request.session.get(clave_sesion)
    participante = (
        Participante.objects.filter(id=participante_id, proceso=proceso).first()
        if participante_id
        else None
    )
    if not participante:
        form = ParticipantePublicoForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            with transaction.atomic():
                existente = Participante.objects.filter(
                    proceso=proceso,
                    numero_alumno=form.cleaned_data['numero_alumno'],
                ).first()
                if (
                    existente
                    and (
                        existente.nombre.strip().casefold() != form.cleaned_data['nombre'].strip().casefold()
                        or existente.fecha_nacimiento != form.cleaned_data['fecha_nacimiento']
                    )
                ):
                    form.add_error(
                        None,
                        (
                            'No fue posible confirmar la información. '
                            'Revisa tus datos o comunícate con Coordinación INTERA.'
                        ),
                    )
                else:
                    participante = existente or form.save(commit=False)
                    if not existente:
                        participante.proceso = proceso
                        participante.save()
                    aplicaciones = []
                    for configuracion in configuraciones:
                        aplicacion, _ = AplicacionInstrumento.objects.get_or_create(
                            proceso=proceso,
                            participante=participante,
                            instrumento=configuracion.instrumento,
                            defaults={'aplicacion_publica': publica},
                        )
                        if aplicacion.aplicacion_publica_id != publica.id:
                            aplicacion.aplicacion_publica = publica
                            aplicacion.save(update_fields=['aplicacion_publica'])
                        aplicaciones.append(aplicacion)
                    request.session[clave_sesion] = participante.id
                    return redirect(
                        'certificacion_intera:aplicacion_publica',
                        token=publica.token,
                    )
        return render(
            request,
            'certificacion_intera/aplicacion_bateria_publica.html',
            {
                'pantalla': 'datos',
                'form': form,
                'proceso': proceso,
            },
        )
    aplicaciones = {
        aplicacion.instrumento_id: aplicacion
        for aplicacion in participante.aplicaciones.filter(proceso=proceso)
    }
    pendientes = [
        configuracion
        for configuracion in configuraciones
        if (
            aplicaciones.get(configuracion.instrumento_id)
            and aplicaciones[configuracion.instrumento_id].estado != AplicacionInstrumento.Estado.RESPONDIDA
        )
    ]
    if not pendientes:
        if request.method == 'POST' and request.POST.get('accion') == 'enviar':
            if request.POST.get('privacidad') != 'acepto':
                return render(
                    request,
                    'certificacion_intera/aplicacion_bateria_publica.html',
                    {
                        'pantalla': 'revision',
                        'proceso': proceso,
                        'total': len(configuraciones),
                        'error': 'Debes aceptar el aviso de privacidad para enviar tus respuestas.',
                    },
                )
            participante.privacidad_aceptada_en = timezone.now()
            participante.privacidad_version = 'INTERA-v1'
            participante.save(
                update_fields=['privacidad_aceptada_en', 'privacidad_version'],
            )
            BitacoraProceso.objects.create(
                proceso=proceso,
                evento='Batería pública finalizada',
                descripcion='Respuestas enviadas por participante.',
            )
            request.session.pop(clave_sesion, None)
            return render(
                request,
                'certificacion_intera/aplicacion_bateria_publica.html',
                {'pantalla': 'gracias'},
            )
        return render(
            request,
            'certificacion_intera/aplicacion_bateria_publica.html',
            {
                'pantalla': 'revision',
                'proceso': proceso,
                'total': len(configuraciones),
            },
        )
    configuracion = pendientes[0]
    aplicacion = aplicaciones[configuracion.instrumento_id]
    indice = configuraciones.index(configuracion) + 1
    preguntas = list(configuracion.instrumento.preguntas.all())
    if (
        'sexo' in campos_contexto_requeridos(configuracion.instrumento)
        and not participante.sexo
    ):
        form_sexo = SexoBaremoPublicoForm(request.POST or None)
        if request.method == 'POST' and form_sexo.is_valid():
            participante.sexo = form_sexo.cleaned_data['sexo']
            participante.save(update_fields=['sexo'])
            return redirect(
                'certificacion_intera:aplicacion_publica',
                token=publica.token,
            )
        return render(
            request,
            'certificacion_intera/aplicacion_bateria_publica.html',
            {
                'pantalla': 'contexto_baremo',
                'form': form_sexo,
                'instrumento': configuracion.instrumento,
                'indice': indice,
                'total': len(configuraciones),
            },
        )
    if request.method == 'POST' and request.POST.get('accion') == 'comenzar':
        if not aplicacion.iniciada_en:
            aplicacion.iniciada_en = timezone.now()
            aplicacion.save(update_fields=['iniciada_en'])
        return render(
            request,
            'certificacion_intera/aplicacion_bateria_publica.html',
            {
                'pantalla': 'preguntas',
                'instrumento': configuracion.instrumento,
                'preguntas': preguntas,
                'indice': indice,
                'total': len(configuraciones),
            },
        )
    if request.method == 'POST' and request.POST.get('accion') == 'responder':
        respuestas, faltantes = ([], [])
        for pregunta in preguntas:
            valor = request.POST.get(f'pregunta_{pregunta.id}', '').strip()
            if pregunta.requerida and (not valor):
                faltantes.append(pregunta.id)
            elif valor:
                respuestas.append(
                    RespuestaInstrumento(
                        aplicacion=aplicacion,
                        pregunta=pregunta,
                        valor=valor,
                    ),
                )
        if faltantes:
            return render(
                request,
                'certificacion_intera/aplicacion_bateria_publica.html',
                {
                    'pantalla': 'preguntas',
                    'instrumento': configuracion.instrumento,
                    'preguntas': preguntas,
                    'indice': indice,
                    'total': len(configuraciones),
                    'faltantes': faltantes,
                    'error': 'Completa las preguntas obligatorias.',
                },
            )
        with transaction.atomic():
            RespuestaInstrumento.objects.filter(aplicacion=aplicacion).delete()
            RespuestaInstrumento.objects.bulk_create(respuestas)
            aplicacion.estado = AplicacionInstrumento.Estado.RESPONDIDA
            aplicacion.respondido_en = timezone.now()
            aplicacion.save(update_fields=['estado', 'respondido_en'])
        return redirect(
            'certificacion_intera:aplicacion_publica',
            token=publica.token,
        )
    return render(
        request,
        'certificacion_intera/aplicacion_bateria_publica.html',
        {
            'pantalla': 'instrucciones',
            'instrumento': configuracion.instrumento,
            'indice': indice,
            'total': len(configuraciones),
        },
    )


@acceso_certificacion_intera_requerido


def participante_crear_view(request, proceso_id):
    proceso = _proceso(proceso_id)
    form = ParticipanteForm(request.POST or None)
    bloqueo = _proceso_editable_o_redirigir(request, proceso)
    if bloqueo:
        return bloqueo
    if proceso.estado == ProcesoCertificacion.Estado.CERRADO:
        messages.error(
            request,
            'Este proceso está cerrado y se encuentra disponible solo para consulta.',
        )
        return redirect(
            'certificacion_intera:proceso_detalle',
            proceso_id=proceso.id,
        )
    if request.method == 'POST' and form.is_valid():
        participante = form.save(commit=False)
        participante.proceso = proceso
        participante.save()
        return redirect(
            'certificacion_intera:participante_detalle',
            participante_id=participante.id,
        )
    return render(
        request,
        'certificacion_intera/form.html',
        {
            'vista_actual': 'procesos',
            'form': form,
            'titulo_formulario': 'Registrar participante',
            'volver_url': reverse('certificacion_intera:proceso_detalle', args=[proceso.id]),
        },
    )


@acceso_certificacion_intera_requerido


def participante_editar_view(request, participante_id):
    participante = _participante(participante_id)
    bloqueo = _proceso_editable_o_redirigir(request, participante.proceso)
    if bloqueo:
        return bloqueo
    form = ParticipanteForm(request.POST or None, instance=participante)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Participante actualizado.')
        return redirect(
            'certificacion_intera:participante_detalle',
            participante_id=participante.id,
        )
    return render(
        request,
        'certificacion_intera/form.html',
        {
            'vista_actual': 'procesos',
            'form': form,
            'titulo_formulario': 'Editar participante',
            'volver_url': reverse(
                'certificacion_intera:participante_detalle',
                args=[participante.id],
            ),
        },
    )


@acceso_certificacion_intera_requerido


def participante_eliminar_view(request, participante_id):
    participante = _participante(participante_id)
    bloqueo = _proceso_editable_o_redirigir(request, participante.proceso)
    if bloqueo:
        return bloqueo
    if request.method == 'POST':
        proceso_id, nombre = (participante.proceso_id, participante.nombre)
        participante.delete()
        BitacoraProceso.objects.create(
            proceso_id=proceso_id,
            evento='Participante eliminado',
            descripcion=nombre,
            usuario=request.user,
        )
        return redirect(
            'certificacion_intera:proceso_detalle',
            proceso_id=proceso_id,
        )
    return render(
        request,
        'certificacion_intera/eliminar.html',
        {
            'vista_actual': 'procesos',
            'objeto': participante,
            'volver_url': reverse(
                'certificacion_intera:participante_detalle',
                args=[participante.id],
            ),
        },
    )


@acceso_certificacion_intera_requerido


def participante_detalle_view(request, participante_id):
    participante = _participante(participante_id)
    return render(
        request,
        'certificacion_intera/participante_detalle.html',
        {
            'vista_actual': 'procesos',
            'participante': participante,
            'aplicaciones': participante.aplicaciones.select_related(
                'instrumento',
            ).exclude(
                instrumento__clave__in=CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO,
            ),
            'consejerias': participante.consejerias.all(),
            'canalizaciones': participante.canalizaciones.select_related('solicitud_atencion'),
        },
    )


@acceso_certificacion_intera_requerido


def configuracion_view(request, proceso_id):
    proceso = _proceso(proceso_id)
    if (
        proceso.estado != ProcesoCertificacion.Estado.CONFIGURACION
        or proceso.aplicaciones.exists()
    ):
        messages.error(
            request,
            'La batería solo puede modificarse durante la creación del proceso y antes de generar aplicaciones.',
        )
        return redirect(
            'certificacion_intera:proceso_detalle',
            proceso_id=proceso.id,
        )
    bateria, instrumentos_seleccionables = _instrumentos_para_bateria()
    seleccionados_post = (
        set(request.POST.getlist('instrumentos'))
        if request.method == 'POST'
        else set(
            proceso.configuraciones_instrumento.values_list(
                'instrumento_id',
                flat=True,
            ),
        )
    )
    ordenes_actuales = dict(
        proceso.configuraciones_instrumento.values_list(
            'instrumento_id',
            'orden',
        ),
    )
    for item in bateria:
        instrumento_id = item['instrumento'].id
        item['seleccionada'] = (
            str(instrumento_id) in seleccionados_post
            or instrumento_id in seleccionados_post
        )
        item['orden'] = (
            request.POST.get(
                f'orden_{instrumento_id}',
                ordenes_actuales.get(instrumento_id, ''),
            )
            if request.method == 'POST'
            else ordenes_actuales.get(instrumento_id, '')
        )
    errores_bateria = []
    if request.method == 'POST':
        try:
            instrumentos = list(
                instrumentos_seleccionables.filter(
                    id__in=request.POST.getlist('instrumentos'),
                ),
            )
            if not instrumentos:
                raise ValueError('Selecciona al menos un instrumento disponible.')
            if len(instrumentos) != len(request.POST.getlist('instrumentos')):
                raise ValueError(
                    'La batería incluye un instrumento inexistente, inactivo o bloqueado.',
                )
            ordenes = _orden_bateria_post(request, instrumentos)
        except ValueError as error:
            errores_bateria.append(str(error))
        else:
            with transaction.atomic():
                proceso.configuraciones_instrumento.exclude(
                    instrumento__in=instrumentos,
                ).delete()
                existentes = {
                    configuracion.instrumento_id: configuracion
                    for configuracion in proceso.configuraciones_instrumento.all()
                }
                for instrumento in instrumentos:
                    configuracion = existentes.get(instrumento.id)
                    if configuracion:
                        configuracion.orden = ordenes[instrumento.id]
                        configuracion.save(update_fields=['orden'])
                    else:
                        ConfiguracionInstrumento.objects.create(
                            proceso=proceso,
                            instrumento=instrumento,
                            orden=ordenes[instrumento.id],
                        )
                for configuracion in proceso.configuraciones_instrumento.select_related('instrumento'):
                    obtener_aplicacion_publica(configuracion, request.user)
                BitacoraProceso.objects.create(
                    proceso=proceso,
                    evento='Batería actualizada',
                    descripcion='Se actualizó la selección y el orden de instrumentos.',
                    usuario=request.user,
                )
            messages.success(
                request,
                'La batería de evaluación se actualizó correctamente.',
            )
            return redirect(
                'certificacion_intera:proceso_detalle',
                proceso_id=proceso.id,
            )
    return render(
        request,
        'certificacion_intera/configuracion.html',
        {
            'vista_actual': 'configuracion',
            'proceso': proceso,
            'bateria': bateria,
            'errores_bateria': errores_bateria,
        },
    )


def aplicacion_publica_config_view(request, token):
    publica = get_object_or_404(
        AplicacionPublica.objects.select_related(
            'proceso__escuela',
            'configuracion__proceso__escuela',
            'configuracion__instrumento',
        ),
        token=token,
    )
    if publica.proceso_id:
        return aplicacion_publica_proceso_view(request, publica)
    configuracion = publica.configuracion
    proceso = configuracion.proceso
    instrumento = configuracion.instrumento
    hoy = timezone.localdate()
    campos_contexto = campos_contexto_requeridos(instrumento)
    contexto = {
        'publica': publica,
        'instrumento': instrumento,
        'solicitar_sexo': 'sexo' in campos_contexto,
        'solicitar_fecha_nacimiento': 'fecha_nacimiento' in campos_contexto,
    }
    if proceso.estado == ProcesoCertificacion.Estado.CERRADO:
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {**contexto, 'pantalla': 'finalizada'},
        )
    if (
        publica.estado != AplicacionPublica.Estado.ACTIVA
        or configuracion.estado != ConfiguracionInstrumento.Estado.ACTIVA
    ):
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {**contexto, 'pantalla': 'inactiva'},
        )
    if configuracion.fecha_inicio and hoy < configuracion.fecha_inicio:
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {**contexto, 'pantalla': 'no_abierta'},
        )
    if configuracion.fecha_cierre and hoy > configuracion.fecha_cierre:
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {**contexto, 'pantalla': 'cerrada'},
        )
    preguntas = list(instrumento.preguntas.all())
    if not preguntas:
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {**contexto, 'pantalla': 'sin_preguntas'},
        )
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        numero = request.POST.get('numero_alumno', '').strip()
        grupo = request.POST.get('grupo', '').strip()
        sexo = request.POST.get('sexo', '').strip()
        fecha_nacimiento = request.POST.get('fecha_nacimiento', '').strip()
        if not nombre or not numero:
            return render(
                request,
                'certificacion_intera/aplicacion_publica.html',
                {
                    **contexto,
                    'preguntas': preguntas,
                    'error': 'Captura nombre y número de alumno.',
                    'pantalla': 'formulario',
                },
            )
        if (
            'sexo' in campos_contexto and sexo not in {'femenino', 'masculino'}
            or 'fecha_nacimiento' in campos_contexto and (not fecha_nacimiento)
        ):
            return render(
                request,
                'certificacion_intera/aplicacion_publica.html',
                {
                    **contexto,
                    'preguntas': preguntas,
                    'error': 'Captura los datos requeridos para calcular este instrumento.',
                    'pantalla': 'formulario',
                },
            )
        try:
            fecha_nacimiento_valor = date.fromisoformat(fecha_nacimiento) if fecha_nacimiento else None
        except ValueError:
            return render(
                request,
                'certificacion_intera/aplicacion_publica.html',
                {
                    **contexto,
                    'preguntas': preguntas,
                    'error': 'Captura una fecha de nacimiento valida.',
                    'pantalla': 'formulario',
                },
            )
        respuestas_datos = []
        faltantes = []
        for pregunta in preguntas:
            campo = f'pregunta_{pregunta.id}'
            if pregunta.tipo_respuesta == PreguntaInstrumento.Tipo.OPCION_MULTIPLE:
                legibles = [_opcion(pregunta, valor) for valor in request.POST.getlist(campo)]
                valor, numero_valor = (
                    ', '.join((x[0] for x in legibles)),
                    (
                        sum((x[1] for x in legibles if x[1] is not None), Decimal('0'))
                        if legibles
                        else None
                    ),
                )
            elif pregunta.tipo_respuesta == PreguntaInstrumento.Tipo.TEXTO_LIBRE:
                valor, numero_valor = (request.POST.get(campo, '').strip(), None)
            else:
                valor, numero_valor = _opcion(pregunta, request.POST.get(campo, '').strip())
            if pregunta.requerida and (not valor):
                faltantes.append(pregunta.id)
            elif valor:
                respuestas_datos.append((pregunta, valor, numero_valor))
        if faltantes:
            return render(
                request,
                'certificacion_intera/aplicacion_publica.html',
                {
                    **contexto,
                    'preguntas': preguntas,
                    'faltantes': faltantes,
                    'error': f'Faltan {len(faltantes)} preguntas obligatorias por responder.',
                    'pantalla': 'formulario',
                },
            )
        participante, _ = Participante.objects.get_or_create(
            proceso=proceso,
            numero_alumno=numero,
            defaults={
                'nombre': nombre,
                'grupo': grupo,
                'sexo': sexo,
                'fecha_nacimiento': fecha_nacimiento_valor,
            },
        )
        if 'sexo' in campos_contexto and participante.sexo != sexo:
            participante.sexo = sexo
            participante.save(update_fields=['sexo'])
        aplicacion, _ = AplicacionInstrumento.objects.get_or_create(
            proceso=proceso,
            participante=participante,
            instrumento=instrumento,
            defaults={'aplicacion_publica': publica},
        )
        if proceso.estado == ProcesoCertificacion.Estado.CONFIGURACION:
            proceso.estado = ProcesoCertificacion.Estado.APLICACION
            proceso.save(update_fields=['estado', 'actualizado_en'])
        if aplicacion.aplicacion_publica_id is None:
            aplicacion.aplicacion_publica = publica
            aplicacion.save(update_fields=['aplicacion_publica'])
        if aplicacion.estado == AplicacionInstrumento.Estado.RESPONDIDA:
            return render(
                request,
                'certificacion_intera/aplicacion_publica.html',
                {**contexto, 'pantalla': 'respondida'},
            )
        respuestas = [
            RespuestaInstrumento(
                aplicacion=aplicacion,
                pregunta=pregunta,
                valor=valor,
                valor_numerico=numero_valor,
            )
            for (pregunta, valor, numero_valor) in respuestas_datos
        ]
        with transaction.atomic():
            RespuestaInstrumento.objects.filter(aplicacion=aplicacion).delete()
            RespuestaInstrumento.objects.bulk_create(respuestas)
            aplicacion.estado = AplicacionInstrumento.Estado.RESPONDIDA
            aplicacion.respondido_en = timezone.now()
            calculo = calcular_resultado(
                instrumento,
                respuestas,
                {
                    'sexo': participante.sexo,
                    'fecha_nacimiento': participante.fecha_nacimiento,
                    'fecha_aplicacion': aplicacion.respondido_en.date(),
                },
            )
            if calculo:
                aplicacion.puntaje_total, aplicacion.interpretacion, aplicacion.resultado_detalle = (
                    calculo['puntaje_total'],
                    calculo['interpretacion'],
                    calculo['detalle'],
                )
                aplicacion.revision_calculadora = calculo['revision_calculadora']
            aplicacion.save()
            resultado, _ = ResultadoInstrumento.objects.get_or_create(aplicacion=aplicacion)
            if calculo:
                resultado.estado = ResultadoInstrumento.Estado.EVALUADO
                resultado.save(update_fields=['estado'])
            BitacoraProceso.objects.create(
                proceso=proceso,
                evento='Alumno respondió',
                descripcion=participante.nombre,
            )
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {**contexto, 'pantalla': 'gracias'},
        )
    return render(
        request,
        'certificacion_intera/aplicacion_publica.html',
        {
            **contexto,
            'preguntas': preguntas,
            'pantalla': 'formulario',
        },
    )


@acceso_certificacion_intera_requerido


def aplicacion_crear_view(request, participante_id):
    participante = _participante(participante_id)
    configuraciones = participante.proceso.configuraciones_instrumento.select_related(
        'instrumento',
    ).exclude(
        instrumento__clave__in=CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO,
    )
    if request.method == 'POST':
        configuracion = get_object_or_404(
            configuraciones,
            id=request.POST.get('configuracion_id'),
        )
        aplicacion = AplicacionInstrumento.objects.create(
            proceso=participante.proceso,
            participante=participante,
            instrumento=configuracion.instrumento,
            generado_por=request.user,
        )
        if participante.proceso.estado == ProcesoCertificacion.Estado.CONFIGURACION:
            participante.proceso.estado = ProcesoCertificacion.Estado.APLICACION
            participante.proceso.save(update_fields=['estado', 'actualizado_en'])
        link = request.build_absolute_uri(
            reverse(
                'certificacion_intera:aplicacion_individual',
                args=[aplicacion.token],
            ),
        )
        return render(
            request,
            'certificacion_intera/enlace_aplicacion.html',
            {
                'vista_actual': 'procesos',
                'participante': participante,
                'aplicacion': aplicacion,
                'link': link,
            },
        )
    return render(
        request,
        'certificacion_intera/aplicacion_form.html',
        {
            'vista_actual': 'procesos',
            'participante': participante,
            'configuraciones': configuraciones,
        },
    )


def _opcion(pregunta, valor):
    for opcion in pregunta.opciones or []:
        if str(opcion.get('valor')) == str(valor):
            try:
                numerico = Decimal(str(opcion.get('valor')))
            except (InvalidOperation, TypeError, ValueError):
                numerico = None
            return (opcion.get('etiqueta') or str(valor), numerico)
    return (valor, None)


def aplicacion_publica_view(request, token):
    aplicacion = get_object_or_404(
        AplicacionInstrumento.objects.select_related(
            'instrumento',
            'participante',
            'proceso',
        ),
        token=token,
    )
    if aplicacion.proceso.estado == ProcesoCertificacion.Estado.CERRADO:
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {
                'aplicacion': aplicacion,
                'instrumento': aplicacion.instrumento,
                'pantalla': 'finalizada',
            },
        )
    if aplicacion.estado != AplicacionInstrumento.Estado.PENDIENTE:
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {
                'aplicacion': aplicacion,
                'instrumento': aplicacion.instrumento,
                'pantalla': aplicacion.estado,
            },
        )
    preguntas = list(aplicacion.instrumento.preguntas.all())
    if (
        'sexo' in campos_contexto_requeridos(aplicacion.instrumento)
        and not aplicacion.participante.sexo
    ):
        form_sexo = SexoBaremoPublicoForm(request.POST or None)
        if request.method == 'POST' and form_sexo.is_valid():
            aplicacion.participante.sexo = form_sexo.cleaned_data['sexo']
            aplicacion.participante.save(update_fields=['sexo'])
            return redirect(
                'certificacion_intera:aplicacion_individual',
                token=aplicacion.token,
            )
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {
                'aplicacion': aplicacion,
                'instrumento': aplicacion.instrumento,
                'form': form_sexo,
                'pantalla': 'contexto_baremo',
            },
        )
    if (
        'fecha_nacimiento' in campos_contexto_requeridos(aplicacion.instrumento)
        and not aplicacion.participante.fecha_nacimiento
    ):
        form_fecha = FechaNacimientoPublicoForm(request.POST or None)
        if request.method == 'POST' and form_fecha.is_valid():
            aplicacion.participante.fecha_nacimiento = form_fecha.cleaned_data['fecha_nacimiento']
            aplicacion.participante.save(update_fields=['fecha_nacimiento'])
            return redirect('certificacion_intera:aplicacion_individual', token=aplicacion.token)
        return render(
            request,
            'certificacion_intera/aplicacion_publica.html',
            {
                'aplicacion': aplicacion,
                'instrumento': aplicacion.instrumento,
                'form': form_fecha,
                'pantalla': 'contexto_baremo',
            },
        )
    if request.method == 'POST':
        respuestas, faltantes = ([], [])
        for pregunta in preguntas:
            campo = f'pregunta_{pregunta.id}'
            if pregunta.tipo_respuesta == PreguntaInstrumento.Tipo.OPCION_MULTIPLE:
                valores = request.POST.getlist(campo)
                legibles = [_opcion(pregunta, valor) for valor in valores]
                valor, numerico = (
                    ', '.join((x[0] for x in legibles)),
                    (
                        sum((x[1] for x in legibles if x[1] is not None), Decimal('0'))
                        if legibles
                        else None
                    ),
                )
            elif pregunta.tipo_respuesta == PreguntaInstrumento.Tipo.TEXTO_LIBRE:
                valor, numerico = (request.POST.get(campo, '').strip(), None)
            else:
                valor, numerico = _opcion(pregunta, request.POST.get(campo, '').strip())
            if pregunta.requerida and (not valor):
                faltantes.append(pregunta.id)
            elif valor:
                respuestas.append(
                    RespuestaInstrumento(
                        aplicacion=aplicacion,
                        pregunta=pregunta,
                        valor=valor,
                        valor_numerico=numerico,
                    ),
                )
        if not faltantes:
            with transaction.atomic():
                RespuestaInstrumento.objects.filter(aplicacion=aplicacion).delete()
                RespuestaInstrumento.objects.bulk_create(respuestas)
                aplicacion.estado = AplicacionInstrumento.Estado.RESPONDIDA
                aplicacion.respondido_en = timezone.now()
                calculo = calcular_resultado(
                    aplicacion.instrumento,
                    respuestas,
                    {
                    'sexo': aplicacion.participante.sexo,
                    'fecha_nacimiento': aplicacion.participante.fecha_nacimiento,
                    'fecha_aplicacion': aplicacion.respondido_en.date(),
                    },
                )
                if calculo:
                    aplicacion.puntaje_total, aplicacion.interpretacion, aplicacion.resultado_detalle = (
                        calculo['puntaje_total'],
                        calculo['interpretacion'],
                        calculo['detalle'],
                    )
                    aplicacion.revision_calculadora = calculo['revision_calculadora']
                aplicacion.save()
                resultado, _ = ResultadoInstrumento.objects.get_or_create(aplicacion=aplicacion)
                if calculo:
                    resultado.estado = ResultadoInstrumento.Estado.EVALUADO
                    resultado.save(update_fields=['estado'])
            return render(
                request,
                'certificacion_intera/aplicacion_publica.html',
                {
                    'aplicacion': aplicacion,
                    'instrumento': aplicacion.instrumento,
                    'pantalla': 'gracias',
                },
            )
    return render(
        request,
        'certificacion_intera/aplicacion_publica.html',
        {
            'aplicacion': aplicacion,
            'instrumento': aplicacion.instrumento,
            'preguntas': preguntas,
            'faltantes': locals().get('faltantes', []),
            'pantalla': 'formulario',
        },
    )


@acceso_certificacion_intera_requerido


def resultado_view(request, aplicacion_id):
    aplicacion = get_object_or_404(
        AplicacionInstrumento.objects.select_related(
            'participante__proceso__escuela',
            'instrumento',
        ),
        id=aplicacion_id,
    )
    return render(
        request,
        'certificacion_intera/resultado.html',
        {
            'vista_actual': 'resultados',
            'aplicacion': aplicacion,
            'respuestas': aplicacion.respuestas.select_related('pregunta'),
            'revision_resultado': obtener_revision_resultado(
                aplicacion.revision_calculadora
            ),
            'advertencia_prioritaria': (
                (aplicacion.resultado_detalle or {}).get(
                    'advertencia_prioritaria',
                    '',
                )
            ),
        },
    )


@acceso_certificacion_intera_requerido


def entrevista_crear_view(request, participante_id):
    participante = _participante(participante_id)
    form = EntrevistaSeguimientoForm(
        request.POST or None,
        initial={
            'nombre_confirmado': participante.nombre,
            'numero_alumno_confirmado': participante.numero_alumno,
        },
    )
    if request.method == 'POST' and form.is_valid():
        entrevista = form.save(commit=False)
        entrevista.participante = participante
        entrevista.registrada_por = request.user
        try:
            entrevista.full_clean()
            entrevista.save()
        except Exception as error:
            form.add_error(None, error)
        else:
            BitacoraProceso.objects.create(
                proceso=participante.proceso,
                evento='Entrevista registrada',
                descripcion=participante.nombre,
                usuario=request.user,
            )
            return redirect(
                'certificacion_intera:participante_detalle',
                participante_id=participante.id,
            )
    return render(
        request,
        'certificacion_intera/form.html',
        {
            'vista_actual': 'seguimiento',
            'form': form,
            'titulo_formulario': 'Entrevista individual',
            'volver_url': reverse(
                'certificacion_intera:participante_detalle',
                args=[participante.id],
            ),
        },
    )


def _registro_view(request, participante_id, form_class, modelo, titulo, nombre_url):
    participante = _participante(participante_id)
    form = form_class(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        registro = form.save(commit=False)
        registro.participante = participante
        try:
            registro.full_clean()
            registro.save()
        except Exception as error:
            form.add_error(None, error)
        else:
            BitacoraProceso.objects.create(
                proceso=participante.proceso,
                evento=titulo,
                descripcion=participante.nombre,
                usuario=request.user,
            )
            return redirect(
                'certificacion_intera:participante_detalle',
                participante_id=participante.id,
            )
    return render(
        request,
        'certificacion_intera/form.html',
        {
            'vista_actual': nombre_url,
            'form': form,
            'titulo_formulario': titulo,
            'volver_url': reverse(
                'certificacion_intera:participante_detalle',
                args=[participante.id],
            ),
        },
    )


@acceso_certificacion_intera_requerido


def consejeria_crear_view(request, participante_id):
    return _registro_view(
        request,
        participante_id,
        ConsejeriaForm,
        Consejeria,
        'Registrar consejería',
        'consejerias',
    )


@acceso_certificacion_intera_requerido


def canalizacion_crear_view(request, participante_id):
    return _registro_view(
        request,
        participante_id,
        CanalizacionForm,
        Canalizacion,
        'Registrar canalización a INTRA',
        'canalizaciones',
    )
