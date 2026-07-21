import csv
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.permisos.grupos import usuario_pertenece_a

from .ajustes import AjusteError, registrar_ajuste
from .duplicados import DuplicadoError
from .forms import (
    AjusteForm, CategoriaEgresoForm, ConceptoIngresoForm, DonativoForm, EgresoForm,
    HonorarioForm, IngresoForm, MaestroForm, NominaAcademiaCaptureForm,
    ReporteRecepcionUploadForm, TabuladorAcademiaForm, TabuladorForm,
)
from .integraciones.consultorioweb import ConsultorioWebError, obtener_cortes_semanales
from .integraciones.importador_nomina import cortes_importables, importar_cortes, ya_importado
from .integraciones.importador_recepcion import importar_citas
from .integraciones.reporte_recepcion import ReporteRecepcionError, leer_reporte_api, leer_reporte_excel
from .models import (
    Ajuste, CategoriaEgreso, CitaRecepcion, ConceptoIngreso, Donativo, Egreso,
    Honorario, Ingreso, NominaAcademia,
)
from .nomina_academia import capturar_nomina_academia
from .pdfs import render_pdf
from .reportes_nomina import resumen_nomina_semanal

META_ANUAL_DONATIVOS = Decimal('2000000')

MESES_ABREV = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

COLOR_POR_CONCEPTO = {
    Ingreso.Concepto.CONSULTA: '#1B2C4F',
    Ingreso.Concepto.INSCRIPCION_DIPLOMADO: '#2D5F8B',
    Ingreso.Concepto.MENSUALIDAD_DIPLOMADO: '#2D5F8B',
    Ingreso.Concepto.INSCRIPCION_TALLER: '#C9A24B',
    Ingreso.Concepto.MENSUALIDAD_TALLER: '#C9A24B',
    Ingreso.Concepto.CURSO_CERTIFICACION: '#15B3C7',
}


def acceso_finanzas_requerido(vista):
    """Restringe una vista del módulo de Finanzas a los grupos Finanzas,
    Dirección o Sistemas (Sistemas incluye a cualquier superusuario), mismo
    criterio que usa la tarjeta de Finanzas en el dashboard."""
    @wraps(vista)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not usuario_pertenece_a(request.user, 'Finanzas', 'Dirección', 'Sistemas'):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return wrapper


def _suma(queryset, campo='monto'):
    return queryset.aggregate(total=Sum(campo))['total'] or Decimal('0')


def _ingresos_efectivos(queryset):
    """Ingresos que ya son dinero real: el monto completo si está Pagado,
    solo lo cobrado (monto_pagado) si está Parcial. Un ingreso Pendiente no
    cuenta todavía — así lo pidió Administración al revisar el tablero."""
    pagado = _suma(queryset.filter(estatus=Ingreso.Estatus.PAGADO))
    parcial = _suma(queryset.filter(estatus=Ingreso.Estatus.PARCIAL), 'monto_pagado')
    return pagado + parcial


def _egresos_efectivos(queryset):
    """Egresos ya pagados; uno Pendiente no cuenta hasta que se pague."""
    return _suma(queryset.filter(estatus=Egreso.Estatus.PAGADO))


def _honorarios_efectivos(queryset):
    """Honorarios ya pagados; uno Pendiente no cuenta hasta que se pague."""
    return _suma(queryset.filter(estatus=Honorario.Estatus.PAGADO), 'total')


def _donativos_efectivos(queryset):
    """Donativos vigentes o en trámite; uno Cancelado no debe sumar."""
    return _suma(queryset.exclude(estatus_cfdi=Donativo.EstatusCFDI.CANCELADO))


def _ingresos_por_concepto_efectivo(queryset):
    """Ingresos efectivos (ver _ingresos_efectivos) agrupados por concepto,
    para la gráfica de dona del tablero."""
    totales = {}
    for fila in queryset.filter(estatus=Ingreso.Estatus.PAGADO).values('concepto').annotate(total=Sum('monto')):
        totales[fila['concepto']] = totales.get(fila['concepto'], Decimal('0')) + (fila['total'] or Decimal('0'))
    for fila in queryset.filter(estatus=Ingreso.Estatus.PARCIAL).values('concepto').annotate(total=Sum('monto_pagado')):
        totales[fila['concepto']] = totales.get(fila['concepto'], Decimal('0')) + (fila['total'] or Decimal('0'))
    return totales


def _dinero(valor):
    return f'-${abs(valor):,.0f}' if valor < 0 else f'${valor:,.0f}'


def _mes_anterior(anio, mes):
    return (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def _delta_pct(actual, anterior):
    if not anterior:
        return None
    return (actual - anterior) / anterior * 100


def _meses_recientes(cantidad=6):
    hoy = timezone.now().date()
    meses = []
    anio, mes = hoy.year, hoy.month
    for _ in range(cantidad):
        meses.append((anio, mes))
        anio, mes = _mes_anterior(anio, mes)
    return list(reversed(meses))


@acceso_finanzas_requerido
def tablero_view(request):
    hoy = timezone.now().date()
    anio_ant, mes_ant = _mes_anterior(hoy.year, hoy.month)

    ingresos_mes = Ingreso.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    egresos_mes = Egreso.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    honorarios_mes = Honorario.objects.filter(periodo_anio=hoy.year, periodo_mes=hoy.month)
    donativos_mes = Donativo.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)

    ingresos_mes_ant = _ingresos_efectivos(Ingreso.objects.filter(fecha__year=anio_ant, fecha__month=mes_ant))
    egresos_mes_ant = _egresos_efectivos(Egreso.objects.filter(fecha__year=anio_ant, fecha__month=mes_ant))
    honorarios_mes_ant = _honorarios_efectivos(Honorario.objects.filter(periodo_anio=anio_ant, periodo_mes=mes_ant))
    donativos_mes_ant = _donativos_efectivos(Donativo.objects.filter(fecha__year=anio_ant, fecha__month=mes_ant))

    # Solo cuenta dinero real: un Ingreso/Egreso/Honorario Pendiente no suma
    # al tablero hasta que se marca Pagado (o, en Ingreso, lo que ya se
    # cobró si está Parcial). Un Donativo Cancelado tampoco suma.
    total_ingresos = _ingresos_efectivos(ingresos_mes)
    total_egresos = _egresos_efectivos(egresos_mes)
    total_honorarios = _honorarios_efectivos(honorarios_mes)
    total_donativos = _donativos_efectivos(donativos_mes)
    balance_neto = total_ingresos - total_egresos - total_honorarios
    balance_neto_ant = ingresos_mes_ant - egresos_mes_ant - honorarios_mes_ant

    def kpi(label, valor, anterior, accent):
        delta = _delta_pct(valor, anterior)
        return {
            'label': label,
            'value': _dinero(valor),
            'accent': accent,
            'delta': f'{"▲" if delta >= 0 else "▼"} {abs(delta):.1f}%' if delta is not None else '—',
            'delta_positivo': delta is None or delta >= 0,
        }

    kpis = [
        kpi('Ingresos del periodo', total_ingresos, ingresos_mes_ant, '#2D5F8B'),
        kpi('Egresos del periodo', total_egresos, egresos_mes_ant, '#C9A24B'),
        kpi('Balance neto', balance_neto, balance_neto_ant, '#1F8A5B'),
        kpi('Donativos', total_donativos, donativos_mes_ant, '#15B3C7'),
        kpi('Honorarios', total_honorarios, honorarios_mes_ant, '#1B2C4F'),
    ]

    barras = []
    for anio, mes in _meses_recientes(6):
        ing = _ingresos_efectivos(Ingreso.objects.filter(fecha__year=anio, fecha__month=mes))
        egr = _egresos_efectivos(Egreso.objects.filter(fecha__year=anio, fecha__month=mes))
        barras.append({'mes': MESES_ABREV[mes], 'ingreso': ing, 'egreso': egr})
    max_barra = max([b['ingreso'] for b in barras] + [b['egreso'] for b in barras] + [Decimal('1')])
    for b in barras:
        b['ingreso_pct'] = float(b['ingreso'] / max_barra * 100)
        b['egreso_pct'] = float(b['egreso'] / max_barra * 100)

    concepto_legend = []
    conic_parts = []
    acumulado_pct = 0.0
    conceptos_display = dict(Ingreso.Concepto.choices)
    totales_por_concepto = _ingresos_por_concepto_efectivo(ingresos_mes)
    for concepto, total in sorted(totales_por_concepto.items(), key=lambda kv: -kv[1]):
        if not total:
            continue
        pct = float(total / total_ingresos * 100) if total_ingresos else 0
        color = COLOR_POR_CONCEPTO.get(concepto, '#8FA0C0')
        concepto_legend.append({
            # .get() con default: un concepto agregado desde Configuración no
            # está en el enum fijo, así que se muestra tal cual (ya es un
            # nombre legible, ver ConceptoIngreso).
            'label': conceptos_display.get(concepto, concepto),
            'pct': round(pct),
            'color': color,
        })
        conic_parts.append(f'{color} {acumulado_pct:.2f}% {acumulado_pct + pct:.2f}%')
        acumulado_pct += pct
    donut_gradient = ', '.join(conic_parts) if conic_parts else '#E6EAF2 0% 100%'

    recientes = []
    for i in ingresos_mes.select_related('terapeuta').order_by('-fecha')[:5]:
        recientes.append({
            'concepto': i.get_concepto_display(),
            'meta': i.persona or (str(i.terapeuta) if i.terapeuta else ''),
            'monto': _dinero(i.monto), 'signo': '+', 'fecha': i.fecha,
        })
    for e in egresos_mes.order_by('-fecha')[:5]:
        recientes.append({
            'concepto': e.concepto, 'meta': e.get_categoria_display(),
            'monto': _dinero(e.monto), 'signo': '-', 'fecha': e.fecha,
        })
    for d in donativos_mes.exclude(estatus_cfdi=Donativo.EstatusCFDI.CANCELADO).order_by('-fecha')[:5]:
        recientes.append({
            'concepto': f'Donativo {d.get_tipo_display().lower()}', 'meta': d.donante_nombre,
            'monto': _dinero(d.monto), 'signo': '+', 'fecha': d.fecha,
        })
    recientes.sort(key=lambda r: r['fecha'], reverse=True)
    recientes = recientes[:5]

    total_donativos_anio = _donativos_efectivos(Donativo.objects.filter(fecha__year=hoy.year))
    pct_meta = min(100, round(float(total_donativos_anio / META_ANUAL_DONATIVOS * 100)))
    meta_donativos = {
        'acumulado': _dinero(total_donativos_anio),
        'meta': _dinero(META_ANUAL_DONATIVOS),
        'pct': pct_meta,
    }

    pendientes = [
        {
            'terapeuta': h.terapeuta,
            'categoria': h.tabulador.categoria,
            'num_pacientes': h.num_pacientes,
            'total': _dinero(h.total),
        }
        for h in Honorario.objects.select_related('terapeuta', 'tabulador')
        .filter(estatus=Honorario.Estatus.PENDIENTE)
        .order_by('-total')[:6]
    ]

    contexto = {
        'vista_actual': 'tablero',
        'kpis': kpis,
        'barras': barras,
        'concepto_legend': concepto_legend,
        'donut_gradient': donut_gradient,
        'donut_total': _dinero(total_ingresos),
        'recientes': recientes,
        'meta_donativos': meta_donativos,
        'pendientes': pendientes,
        'form_ingreso': IngresoForm(initial={'fecha': hoy}),
        'form_egreso': EgresoForm(initial={'fecha': hoy}),
        'form_donativo': DonativoForm(initial={'fecha': hoy}),
    }
    return render(request, 'finanzas/tablero.html', contexto)


@acceso_finanzas_requerido
def ingresos_view(request):
    hoy = timezone.now().date()

    if request.method == 'POST':
        form_ingreso = IngresoForm(request.POST)
        if form_ingreso.is_valid():
            form_ingreso.save()
            messages.success(request, 'Ingreso registrado correctamente.')
            return redirect('finanzas:ingresos')
    else:
        form_ingreso = IngresoForm(initial={'fecha': hoy})

    ingresos_mes = Ingreso.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    # Se diferencia el total capturado (lo que se debe cobrar en total) de
    # lo efectivamente cobrado (Pagado completo + la parte ya cobrada de un
    # Parcial) y lo que todavía falta por cobrar — antes "Cobrado" solo veía
    # los Pagado completos e ignoraba lo ya cobrado de un Parcial.
    total_capturado = _suma(ingresos_mes)
    cobrado = _ingresos_efectivos(ingresos_mes)
    stats = [
        {'label': 'Total capturado', 'value': _dinero(total_capturado), 'color': '#1B2C4F'},
        {'label': 'Cobrado', 'value': _dinero(cobrado), 'color': '#1F8A5B'},
        {'label': 'Pendiente por cobrar', 'value': _dinero(total_capturado - cobrado), 'color': '#9A6B12'},
    ]
    contexto = {
        'vista_actual': 'ingresos',
        'stats': stats,
        'ingresos': Ingreso.objects.select_related('terapeuta').order_by('-fecha')[:200],
        'form_ingreso': form_ingreso,
    }
    return render(request, 'finanzas/ingresos.html', contexto)


@acceso_finanzas_requerido
def honorarios_view(request):
    hoy = timezone.now().date()

    form_egreso = EgresoForm(initial={'fecha': hoy})
    form_tabulador = TabuladorForm(initial={'vigente_desde': hoy})
    form_honorario = HonorarioForm(initial={'periodo_mes': hoy.month, 'periodo_anio': hoy.year})

    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'tabulador':
            form_tabulador = TabuladorForm(request.POST)
            if form_tabulador.is_valid():
                form_tabulador.save()
                messages.success(request, 'Tabulador registrado correctamente.')
                return redirect('finanzas:honorarios')
        elif accion == 'honorario':
            form_honorario = HonorarioForm(request.POST)
            if form_honorario.is_valid():
                form_honorario.save()
                messages.success(request, 'Honorario registrado correctamente.')
                return redirect('finanzas:honorarios')
        else:
            form_egreso = EgresoForm(request.POST)
            if form_egreso.is_valid():
                form_egreso.save()
                messages.success(request, 'Egreso registrado correctamente.')
                return redirect('finanzas:honorarios')

    honorarios = (
        Honorario.objects.select_related('terapeuta', 'tabulador')
        .filter(periodo_anio=hoy.year, periodo_mes=hoy.month)
        .order_by('terapeuta__first_name', 'terapeuta__username')
    )
    egresos_mes = Egreso.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month).order_by('-fecha')
    contexto = {
        'vista_actual': 'honorarios',
        'honorarios': honorarios,
        'total_periodo': _dinero(_suma(honorarios, 'total')),
        'egresos': egresos_mes,
        'total_egresos_periodo': _dinero(_suma(egresos_mes)),
        'form_egreso': form_egreso,
        'form_tabulador': form_tabulador,
        'form_honorario': form_honorario,
    }
    return render(request, 'finanzas/honorarios.html', contexto)


@acceso_finanzas_requerido
def nomina_view(request):
    hoy = timezone.now().date()

    if request.method == 'POST':
        fecha_inicio = request.POST.get('fecha_inicio', '')
        fecha_fin = request.POST.get('fecha_fin', '')
        ids_seleccionados = set(request.POST.getlist('corte_id'))
        try:
            cortes_raw = obtener_cortes_semanales(fecha_inicio, fecha_fin)
            cortes_por_id = {str(c['id']): c for c in cortes_importables(cortes_raw)}
            seleccionados = [cortes_por_id[i] for i in ids_seleccionados if i in cortes_por_id]
            resumen = importar_cortes(seleccionados)
            messages.success(
                request,
                f"Se importaron {resumen['creados']} movimientos a Egresos "
                f"({resumen['omitidos']} cortes ya estaban importados y se omitieron).",
            )
        except ConsultorioWebError as exc:
            messages.error(request, str(exc))
        return redirect(f"{reverse('finanzas:nomina')}?fecha_inicio={fecha_inicio}&fecha_fin={fecha_fin}")

    fecha_inicio = request.GET.get('fecha_inicio') or str(hoy - timedelta(weeks=4))
    fecha_fin = request.GET.get('fecha_fin') or str(hoy)

    cortes = []
    error = None
    try:
        cortes_raw = obtener_cortes_semanales(fecha_inicio, fecha_fin)
        for c in cortes_importables(cortes_raw):
            c['importado'] = ya_importado(c['id'])
            # No existe clase CSS fin-badge-aprobado; 'aprobado' reusa el
            # estilo verde de 'vigente' (ya definido en finanzas.css).
            c['estatus_badge'] = 'vigente' if c['estatus'] == 'aprobado' else c['estatus']
            c['total_pago_fmt'] = _dinero(Decimal(str(c['total_pago'])))
            c['subtotal_sesiones_fmt'] = _dinero(Decimal(str(c['subtotal_sesiones'])))
            c['total_bonos_fmt'] = _dinero(Decimal(str(c['total_bonos'])))
            cortes.append(c)
    except ConsultorioWebError as exc:
        error = str(exc)

    contexto = {
        'vista_actual': 'nomina',
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'cortes': cortes,
        'error': error,
        'hay_seleccionables': any(not c['importado'] for c in cortes),
    }
    return render(request, 'finanzas/nomina.html', contexto)


@acceso_finanzas_requerido
def nomina_descargar_view(request):
    """Genera el PDF descargable de la nómina semanal (sección 4 del
    documento de requerimientos), a partir de los Egresos ya importados de
    ConsultorioWeb en el rango de fechas seleccionado en la pantalla de
    Nómina."""
    hoy = timezone.now().date()
    fecha_inicio = _fecha_desde_query(request, 'fecha_inicio') or (hoy - timedelta(weeks=4))
    fecha_fin = _fecha_desde_query(request, 'fecha_fin') or hoy

    filas, totales = resumen_nomina_semanal(fecha_inicio, fecha_fin)
    estatus_general = Egreso.Estatus.PENDIENTE if any(
        f['estatus'] == Egreso.Estatus.PENDIENTE for f in filas
    ) else Egreso.Estatus.PAGADO

    contexto = {
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'filas': filas,
        'totales': totales,
        'estatus_general': estatus_general,
        'generado_en': timezone.now(),
    }
    nombre_archivo = f'nomina_semanal_{fecha_inicio.isoformat()}_{fecha_fin.isoformat()}.pdf'
    return render_pdf('finanzas/nomina_pdf.html', contexto, nombre_archivo)


@acceso_finanzas_requerido
def reporte_recepcion_view(request):
    """Importa el Reporte General de Recepción y alimenta Ingresos, ranking
    de terapeutas y comparativo por método de pago, sin copiar manualmente a
    otra plantilla (sección 5 del documento de requerimientos). Fuente
    principal: sincronización directa con GET /api/reporte-general/ de
    ConsultorioWeb. El Excel exportado a mano se conserva como respaldo, por
    si la API no responde o se necesita importar un periodo puntual."""
    hoy = timezone.now().date()

    if request.method == 'POST':
        if request.POST.get('accion') == 'sincronizar':
            fecha_inicio_str = request.POST.get('fecha_inicio', '')
            fecha_fin_str = request.POST.get('fecha_fin', '')
            try:
                filas = leer_reporte_api(fecha_inicio_str, fecha_fin_str)
                resumen = importar_citas(filas)
                messages.success(
                    request,
                    f"Sincronizado con ConsultorioWeb: {resumen['creadas']} citas nuevas, "
                    f"{resumen['actualizadas']} actualizadas "
                    f"({resumen['con_ingreso']} generaron ingreso).",
                )
            except (ConsultorioWebError, ReporteRecepcionError) as exc:
                messages.error(request, f'{exc} Puedes usar el respaldo de Excel mientras tanto.')
            return redirect(f"{reverse('finanzas:reporte_recepcion')}?fecha_inicio={fecha_inicio_str}&fecha_fin={fecha_fin_str}")

        form_upload = ReporteRecepcionUploadForm(request.POST, request.FILES)
        if form_upload.is_valid():
            try:
                filas = leer_reporte_excel(form_upload.cleaned_data['archivo'])
                resumen = importar_citas(filas)
                messages.success(
                    request,
                    f"Reporte importado desde Excel: {resumen['creadas']} citas nuevas, "
                    f"{resumen['actualizadas']} actualizadas "
                    f"({resumen['con_ingreso']} generaron ingreso).",
                )
            except ReporteRecepcionError as exc:
                messages.error(request, str(exc))
        return redirect('finanzas:reporte_recepcion')

    form_upload = ReporteRecepcionUploadForm()
    fecha_inicio = request.GET.get('fecha_inicio') or str(hoy - timedelta(weeks=4))
    fecha_fin = request.GET.get('fecha_fin') or str(hoy)

    citas = CitaRecepcion.objects.all()
    total_citas = citas.count()
    total_asistidas = citas.filter(estatus=CitaRecepcion.Estatus.SI_ASISTIO).count()
    total_ingresos_generados = _suma(Ingreso.objects.filter(cita_recepcion__isnull=False))

    ranking = (
        citas.filter(estatus=CitaRecepcion.Estatus.SI_ASISTIO)
        .values('terapeuta')
        .annotate(citas_atendidas=Count('id'), total_generado=Sum('costo'))
        .order_by('-total_generado')[:10]
    )
    for fila in ranking:
        fila['total_generado_fmt'] = _dinero(fila['total_generado'] or Decimal('0'))

    por_metodo = (
        citas.filter(estatus=CitaRecepcion.Estatus.SI_ASISTIO)
        .exclude(metodo_pago='')
        .values('metodo_pago')
        .annotate(total=Sum('costo'), citas=Count('id'))
        .order_by('-total')
    )
    metodos_display = dict(CitaRecepcion.MetodoPago.choices)
    for fila in por_metodo:
        fila['metodo_pago_display'] = metodos_display.get(fila['metodo_pago'], fila['metodo_pago'])
        fila['total_fmt'] = _dinero(fila['total'] or Decimal('0'))

    contexto = {
        'vista_actual': 'reporte_recepcion',
        'form_upload': form_upload,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'api_configurada': bool(settings.CONSULTORIOWEB_API_URL),
        'total_citas': total_citas,
        'total_asistidas': total_asistidas,
        'total_ingresos_generados': _dinero(total_ingresos_generados),
        'ranking': ranking,
        'por_metodo': por_metodo,
        'ultimas_citas': citas.select_related('ingreso')[:20],
    }
    return render(request, 'finanzas/reporte_recepcion.html', contexto)


@acceso_finanzas_requerido
def donativos_view(request):
    hoy = timezone.now().date()

    if request.method == 'POST':
        form_donativo = DonativoForm(request.POST, request.FILES)
        if form_donativo.is_valid():
            form_donativo.save()
            messages.success(request, 'Donativo registrado correctamente.')
            return redirect('finanzas:donativos')
    else:
        form_donativo = DonativoForm(initial={'fecha': hoy})

    donativos_mes = Donativo.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    donativos_anio = Donativo.objects.filter(fecha__year=hoy.year)
    stats = [
        # Un CFDI Cancelado nunca fue dinero real: no suma en ninguna de
        # estas tarjetas (mismo criterio que el tablero).
        {'label': 'Donativos del mes', 'value': _dinero(_donativos_efectivos(donativos_mes)), 'sub': f'{donativos_mes.count()} donantes'},
        {'label': f'Acumulado {hoy.year}', 'value': _dinero(_donativos_efectivos(donativos_anio)), 'sub': f'meta {_dinero(META_ANUAL_DONATIVOS)}'},
        {
            'label': 'CFDI emitidos',
            'value': str(donativos_anio.exclude(folio_cfdi='').exclude(folio_cfdi__isnull=True).count()),
            'sub': f"{donativos_anio.filter(estatus_cfdi=Donativo.EstatusCFDI.VIGENTE).count()} vigentes",
        },
        {'label': 'En especie', 'value': _dinero(_donativos_efectivos(donativos_anio.filter(tipo=Donativo.Tipo.ESPECIE))), 'sub': 'valuación fiscal'},
    ]
    contexto = {
        'vista_actual': 'donativos',
        'stats': stats,
        'donativos': Donativo.objects.order_by('-fecha')[:200],
        'form_donativo': form_donativo,
    }
    return render(request, 'finanzas/donativos.html', contexto)


@acceso_finanzas_requerido
def nomina_academia_view(request):
    """Captura la nómina de Academia por maestro/periodo: selecciona
    maestro, captura cantidades por concepto (horas clase, supervisión,
    mesa de trabajo, más un concepto manual autorizado opcional), calcula
    el total con los tabuladores vigentes y genera un Egreso por concepto
    (sección 6 del documento de requerimientos)."""
    hoy = timezone.now().date()

    form = NominaAcademiaCaptureForm(initial={'periodo_mes': hoy.month, 'periodo_anio': hoy.year})
    form_maestro = MaestroForm()
    form_tabulador_academia = TabuladorAcademiaForm(initial={'vigente_desde': hoy})

    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'maestro':
            form_maestro = MaestroForm(request.POST)
            if form_maestro.is_valid():
                form_maestro.save()
                messages.success(request, 'Maestro agregado correctamente.')
                return redirect('finanzas:nomina_academia')
        elif accion == 'tabulador_academia':
            form_tabulador_academia = TabuladorAcademiaForm(request.POST)
            if form_tabulador_academia.is_valid():
                form_tabulador_academia.save()
                messages.success(request, 'Tabulador de Academia registrado correctamente.')
                return redirect('finanzas:nomina_academia')
        else:
            form = NominaAcademiaCaptureForm(request.POST)
            if form.is_valid():
                try:
                    nomina = capturar_nomina_academia(
                        maestro=form.cleaned_data['maestro'],
                        periodo_mes=int(form.cleaned_data['periodo_mes']),
                        periodo_anio=form.cleaned_data['periodo_anio'],
                        metodo_pago=form.cleaned_data['metodo_pago'],
                        cantidades=form.cantidades(),
                        concepto_manual_descripcion=form.cleaned_data['concepto_manual_descripcion'],
                        concepto_manual_monto=form.cleaned_data['concepto_manual_monto'],
                    )
                    messages.success(
                        request,
                        f"Nómina de Academia capturada: {nomina.maestro} · "
                        f"{nomina.periodo_mes}/{nomina.periodo_anio} · total {_dinero(nomina.total)}.",
                    )
                except DuplicadoError as exc:
                    messages.error(request, str(exc))
                return redirect('finanzas:nomina_academia')

    nominas = (
        NominaAcademia.objects.select_related('maestro')
        .prefetch_related('conceptos')
        .order_by('-periodo_anio', '-periodo_mes')[:50]
    )
    contexto = {
        'vista_actual': 'nomina_academia',
        'form': form,
        'form_maestro': form_maestro,
        'form_tabulador_academia': form_tabulador_academia,
        'nominas': nominas,
    }
    return render(request, 'finanzas/nomina_academia.html', contexto)


@acceso_finanzas_requerido
def nomina_academia_descargar_view(request, nomina_id):
    nomina = get_object_or_404(
        NominaAcademia.objects.select_related('maestro').prefetch_related('conceptos'), pk=nomina_id,
    )
    es_pendiente = nomina.estatus == NominaAcademia.Estatus.PENDIENTE
    contexto = {
        'nomina': nomina,
        'conceptos': nomina.conceptos.all(),
        'total_transferencia': nomina.total if nomina.metodo_pago == NominaAcademia.MetodoPago.TRANSFERENCIA else Decimal('0'),
        'total_efectivo': nomina.total if nomina.metodo_pago == NominaAcademia.MetodoPago.EFECTIVO else Decimal('0'),
        'total_pendiente': nomina.total if es_pendiente else Decimal('0'),
        'generado_en': timezone.now(),
    }
    nombre_archivo = f'nomina_academia_{nomina.maestro.nombre}_{nomina.periodo_mes}_{nomina.periodo_anio}.pdf'.replace(' ', '_')
    return render_pdf('finanzas/nomina_academia_pdf.html', contexto, nombre_archivo)


@acceso_finanzas_requerido
def ajustes_view(request):
    """Corrige un Honorario, Nómina Academia o Egreso ya capturado sin
    reescribir su historial: registra motivo + diferencia, y si la
    diferencia es un monto adicional a favor, genera un Egreso nuevo
    (criterio 10 del documento de requerimientos)."""
    if request.method == 'POST':
        form = AjusteForm(request.POST)
        if form.is_valid():
            modelo, objeto_id = form.registro_elegido()
            try:
                ajuste = registrar_ajuste(
                    modelo, objeto_id, form.cleaned_data['motivo'], form.cleaned_data['diferencia'],
                )
                mensaje = f'Ajuste registrado: {_dinero(ajuste.diferencia)}.'
                if ajuste.egreso_generado_id:
                    mensaje += ' Se generó un Egreso nuevo por ese monto.'
                messages.success(request, mensaje)
            except AjusteError as exc:
                messages.error(request, str(exc))
            return redirect('finanzas:ajustes')
    else:
        form = AjusteForm()

    ajustes = (
        Ajuste.objects.select_related('content_type', 'egreso_generado')
        .prefetch_related('registro')
        .order_by('-creado_en')[:50]
    )
    contexto = {
        'vista_actual': 'ajustes',
        'form': form,
        'ajustes': ajustes,
    }
    return render(request, 'finanzas/ajustes.html', contexto)


@acceso_finanzas_requerido
def configuracion_view(request):
    """Catálogos administrables sin tocar código: conceptos adicionales de
    Ingreso y categorías adicionales de Egreso. Las opciones base siguen
    fijas en el código porque otras pantallas (tablero, reportes) las usan
    por nombre; esto solo agrega opciones extra a los selectores."""
    form_concepto = ConceptoIngresoForm()
    form_categoria = CategoriaEgresoForm()

    if request.method == 'POST':
        if request.POST.get('accion') == 'categoria_egreso':
            form_categoria = CategoriaEgresoForm(request.POST)
            if form_categoria.is_valid():
                form_categoria.save()
                messages.success(request, 'Categoría de Egreso agregada correctamente.')
                return redirect('finanzas:configuracion')
        else:
            form_concepto = ConceptoIngresoForm(request.POST)
            if form_concepto.is_valid():
                form_concepto.save()
                messages.success(request, 'Concepto de Ingreso agregado correctamente.')
                return redirect('finanzas:configuracion')

    contexto = {
        'vista_actual': 'configuracion',
        'form_concepto': form_concepto,
        'form_categoria': form_categoria,
        'conceptos_base': [c[1] for c in Ingreso.Concepto.choices],
        'categorias_base': [c[1] for c in Egreso.Categoria.choices],
        'conceptos_extra': ConceptoIngreso.objects.order_by('nombre'),
        'categorias_extra': CategoriaEgreso.objects.order_by('nombre'),
    }
    return render(request, 'finanzas/configuracion.html', contexto)


@acceso_finanzas_requerido
def reportes_view(request):
    hoy = timezone.now().date()
    ingresos_anio = Ingreso.objects.filter(fecha__year=hoy.year)
    donativos_anio = Donativo.objects.filter(fecha__year=hoy.year)
    honorarios_anio = Honorario.objects.filter(periodo_anio=hoy.year)
    egresos_anio = Egreso.objects.filter(fecha__year=hoy.year)

    # Solo dinero real: Pendientes no suman hasta que se paguen, Cancelados
    # no suman nunca (mismo criterio que el tablero, ver _ingresos_efectivos).
    total_ingresos_servicios = _ingresos_efectivos(ingresos_anio)
    total_donativos = _donativos_efectivos(donativos_anio)
    total_ingresos = total_ingresos_servicios + total_donativos

    total_honorarios = _honorarios_efectivos(honorarios_anio)
    total_renta = (
        _egresos_efectivos(egresos_anio.filter(categoria=Egreso.Categoria.RENTA))
        + _egresos_efectivos(egresos_anio.filter(categoria=Egreso.Categoria.SERVICIOS))
    )
    total_nomina = _egresos_efectivos(egresos_anio.filter(categoria=Egreso.Categoria.NOMINA_ADMIN))
    total_nomina_terapeutas = _egresos_efectivos(egresos_anio.filter(categoria=Egreso.Categoria.NOMINA_TERAPEUTAS))
    total_nomina_academia = _egresos_efectivos(egresos_anio.filter(categoria=Egreso.Categoria.NOMINA_ACADEMIA))
    total_insumos = _egresos_efectivos(egresos_anio.filter(categoria=Egreso.Categoria.INSUMOS))
    # "Otros egresos": cualquier categoría agregada desde Configuración que
    # no sea una de las categorías fijas de arriba. Así el total siempre
    # cuadra con la suma real, sin importar cuántas categorías nuevas agregue
    # el usuario despues.
    categorias_fijas = [c[0] for c in Egreso.Categoria.choices]
    total_otros = _egresos_efectivos(egresos_anio.exclude(categoria__in=categorias_fijas))
    total_egresos = (
        total_honorarios + total_renta + total_nomina + total_nomina_terapeutas
        + total_nomina_academia + total_insumos + total_otros
    )

    resultado_ejercicio = total_ingresos - total_egresos

    contexto = {
        'vista_actual': 'reportes',
        'anio': hoy.year,
        'total_ingresos_servicios': _dinero(total_ingresos_servicios),
        'total_donativos': _dinero(total_donativos),
        'total_ingresos': _dinero(total_ingresos),
        'total_honorarios': _dinero(-total_honorarios),
        'total_nomina': _dinero(-total_nomina),
        'total_nomina_terapeutas': _dinero(-total_nomina_terapeutas),
        'total_nomina_academia': _dinero(-total_nomina_academia),
        'total_renta': _dinero(-total_renta),
        'total_insumos': _dinero(-total_insumos),
        'total_otros': _dinero(-total_otros),
        'total_egresos': _dinero(-total_egresos),
        'resultado_ejercicio': _dinero(resultado_ejercicio),
        'resultado_negativo': resultado_ejercicio < 0,
    }
    return render(request, 'finanzas/reportes.html', contexto)


def _fecha_desde_query(request, nombre):
    valor = request.GET.get(nombre)
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


@acceso_finanzas_requerido
def exportar_view(request):
    desde = _fecha_desde_query(request, 'desde')
    hasta = _fecha_desde_query(request, 'hasta')

    ingresos = Ingreso.objects.select_related('terapeuta').order_by('fecha')
    egresos = Egreso.objects.order_by('fecha')
    donativos = Donativo.objects.order_by('fecha')
    honorarios = Honorario.objects.select_related('terapeuta', 'tabulador').order_by('periodo_anio', 'periodo_mes')

    if desde:
        ingresos = ingresos.filter(fecha__gte=desde)
        egresos = egresos.filter(fecha__gte=desde)
        donativos = donativos.filter(fecha__gte=desde)
        honorarios = honorarios.filter(periodo_anio__gte=desde.year)
    if hasta:
        ingresos = ingresos.filter(fecha__lte=hasta)
        egresos = egresos.filter(fecha__lte=hasta)
        donativos = donativos.filter(fecha__lte=hasta)
        honorarios = honorarios.filter(periodo_anio__lte=hasta.year)

    filas = []
    for i in ingresos:
        filas.append(('Ingreso', i.get_concepto_display(), i.persona or (str(i.terapeuta) if i.terapeuta else ''), i.monto, i.get_estatus_display(), i.fecha))
    for e in egresos:
        filas.append(('Egreso', e.concepto, e.persona, e.monto, e.get_estatus_display(), e.fecha))
    for d in donativos:
        filas.append(('Donativo', f'Donativo {d.get_tipo_display().lower()}', d.donante_nombre, d.monto, d.get_estatus_cfdi_display(), d.fecha))
    for h in honorarios:
        fecha_periodo = date(h.periodo_anio, h.periodo_mes, 1)
        if (desde and fecha_periodo < desde.replace(day=1)) or (hasta and fecha_periodo > hasta):
            continue
        filas.append(('Honorario', f'Honorario cat. {h.tabulador.categoria}', str(h.terapeuta), h.total, h.get_estatus_display(), fecha_periodo))
    filas.sort(key=lambda f: f[5])

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="finanzas_movimientos.csv"'
    writer = csv.writer(response)
    writer.writerow(['Tipo', 'Concepto', 'Persona', 'Monto', 'Estatus', 'Fecha'])
    for tipo, concepto, persona, monto, estatus, fecha in filas:
        writer.writerow([tipo, concepto, persona, monto, estatus, fecha.isoformat()])
    return response
