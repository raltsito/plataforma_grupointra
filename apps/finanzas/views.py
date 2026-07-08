from decimal import Decimal
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from apps.core.permisos.grupos import usuario_pertenece_a

from .models import Donativo, Egreso, Honorario, Ingreso

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

    ingresos_mes_ant = _suma(Ingreso.objects.filter(fecha__year=anio_ant, fecha__month=mes_ant))
    egresos_mes_ant = _suma(Egreso.objects.filter(fecha__year=anio_ant, fecha__month=mes_ant))
    honorarios_mes_ant = _suma(Honorario.objects.filter(periodo_anio=anio_ant, periodo_mes=mes_ant), 'total')
    donativos_mes_ant = _suma(Donativo.objects.filter(fecha__year=anio_ant, fecha__month=mes_ant))

    total_ingresos = _suma(ingresos_mes)
    total_egresos = _suma(egresos_mes)
    total_honorarios = _suma(honorarios_mes, 'total')
    total_donativos = _suma(donativos_mes)
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
        ing = _suma(Ingreso.objects.filter(fecha__year=anio, fecha__month=mes))
        egr = _suma(Egreso.objects.filter(fecha__year=anio, fecha__month=mes))
        barras.append({'mes': MESES_ABREV[mes], 'ingreso': ing, 'egreso': egr})
    max_barra = max([b['ingreso'] for b in barras] + [b['egreso'] for b in barras] + [Decimal('1')])
    for b in barras:
        b['ingreso_pct'] = float(b['ingreso'] / max_barra * 100)
        b['egreso_pct'] = float(b['egreso'] / max_barra * 100)

    por_concepto = ingresos_mes.values('concepto').annotate(total=Sum('monto')).order_by('-total')
    concepto_legend = []
    conic_parts = []
    acumulado_pct = 0.0
    for fila in por_concepto:
        pct = float(fila['total'] / total_ingresos * 100) if total_ingresos else 0
        color = COLOR_POR_CONCEPTO.get(fila['concepto'], '#8FA0C0')
        concepto_legend.append({
            'label': dict(Ingreso.Concepto.choices)[fila['concepto']],
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
    for d in donativos_mes.order_by('-fecha')[:5]:
        recientes.append({
            'concepto': f'Donativo {d.get_tipo_display().lower()}', 'meta': d.donante_nombre,
            'monto': _dinero(d.monto), 'signo': '+', 'fecha': d.fecha,
        })
    recientes.sort(key=lambda r: r['fecha'], reverse=True)
    recientes = recientes[:5]

    total_donativos_anio = _suma(Donativo.objects.filter(fecha__year=hoy.year))
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
    }
    return render(request, 'finanzas/tablero.html', contexto)


@acceso_finanzas_requerido
def ingresos_view(request):
    hoy = timezone.now().date()
    ingresos_mes = Ingreso.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    stats = [
        {'label': 'Total ingresos del mes', 'value': _dinero(_suma(ingresos_mes)), 'color': '#1F8A5B'},
        {'label': 'Cobrado', 'value': _dinero(_suma(ingresos_mes.filter(estatus=Ingreso.Estatus.PAGADO))), 'color': '#1B2C4F'},
        {'label': 'Pendiente / parcial', 'value': _dinero(_suma(ingresos_mes.exclude(estatus=Ingreso.Estatus.PAGADO))), 'color': '#9A6B12'},
    ]
    contexto = {
        'vista_actual': 'ingresos',
        'stats': stats,
        'ingresos': Ingreso.objects.select_related('terapeuta').order_by('-fecha')[:200],
    }
    return render(request, 'finanzas/ingresos.html', contexto)


@acceso_finanzas_requerido
def honorarios_view(request):
    hoy = timezone.now().date()
    honorarios = (
        Honorario.objects.select_related('terapeuta', 'tabulador')
        .filter(periodo_anio=hoy.year, periodo_mes=hoy.month)
        .order_by('terapeuta__first_name', 'terapeuta__username')
    )
    contexto = {
        'vista_actual': 'honorarios',
        'honorarios': honorarios,
        'total_periodo': _dinero(_suma(honorarios, 'total')),
    }
    return render(request, 'finanzas/honorarios.html', contexto)


@acceso_finanzas_requerido
def donativos_view(request):
    hoy = timezone.now().date()
    donativos_mes = Donativo.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    donativos_anio = Donativo.objects.filter(fecha__year=hoy.year)
    stats = [
        {'label': 'Donativos del mes', 'value': _dinero(_suma(donativos_mes)), 'sub': f'{donativos_mes.count()} donantes'},
        {'label': f'Acumulado {hoy.year}', 'value': _dinero(_suma(donativos_anio)), 'sub': f'meta {_dinero(META_ANUAL_DONATIVOS)}'},
        {
            'label': 'CFDI emitidos',
            'value': str(donativos_anio.exclude(folio_cfdi='').exclude(folio_cfdi__isnull=True).count()),
            'sub': f"{donativos_anio.filter(estatus_cfdi=Donativo.EstatusCFDI.VIGENTE).count()} vigentes",
        },
        {'label': 'En especie', 'value': _dinero(_suma(donativos_anio.filter(tipo=Donativo.Tipo.ESPECIE))), 'sub': 'valuación fiscal'},
    ]
    contexto = {
        'vista_actual': 'donativos',
        'stats': stats,
        'donativos': Donativo.objects.order_by('-fecha')[:200],
    }
    return render(request, 'finanzas/donativos.html', contexto)


@acceso_finanzas_requerido
def reportes_view(request):
    hoy = timezone.now().date()
    ingresos_anio = Ingreso.objects.filter(fecha__year=hoy.year)
    donativos_anio = Donativo.objects.filter(fecha__year=hoy.year)
    honorarios_anio = Honorario.objects.filter(periodo_anio=hoy.year)
    egresos_anio = Egreso.objects.filter(fecha__year=hoy.year)

    total_ingresos_servicios = _suma(ingresos_anio)
    total_donativos = _suma(donativos_anio)
    total_ingresos = total_ingresos_servicios + total_donativos

    total_honorarios = _suma(honorarios_anio, 'total')
    total_renta = (
        _suma(egresos_anio.filter(categoria=Egreso.Categoria.RENTA))
        + _suma(egresos_anio.filter(categoria=Egreso.Categoria.SERVICIOS))
    )
    total_nomina = _suma(egresos_anio.filter(categoria=Egreso.Categoria.NOMINA_ADMIN))
    total_insumos = _suma(egresos_anio.filter(categoria=Egreso.Categoria.INSUMOS))
    total_egresos = total_honorarios + total_renta + total_nomina + total_insumos

    resultado_ejercicio = total_ingresos - total_egresos

    contexto = {
        'vista_actual': 'reportes',
        'anio': hoy.year,
        'total_ingresos_servicios': _dinero(total_ingresos_servicios),
        'total_donativos': _dinero(total_donativos),
        'total_ingresos': _dinero(total_ingresos),
        'total_honorarios': _dinero(-total_honorarios),
        'total_nomina': _dinero(-total_nomina),
        'total_renta': _dinero(-total_renta),
        'total_insumos': _dinero(-total_insumos),
        'total_egresos': _dinero(-total_egresos),
        'resultado_ejercicio': _dinero(resultado_ejercicio),
    }
    return render(request, 'finanzas/reportes.html', contexto)
