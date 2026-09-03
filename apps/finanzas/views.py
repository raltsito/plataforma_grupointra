import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Count, ProtectedError, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.auditoria.models import RegistroAuditoria
from apps.core.auditoria.registro import registrar, registrar_cambio_de_campo
from apps.core.permisos.grupos import usuario_pertenece_a

from .ajustes import AjusteError, registrar_ajuste
from .duplicados import DuplicadoError
from .forms import (
    AjusteForm, CategoriaEgresoForm, ConceptoIngresoForm, DonativoForm, EgresoForm,
    IngresoForm, LineaNominaManualForm, MaestroForm, NominaAcademiaCaptureForm,
    ReporteRecepcionUploadForm, TabuladorAcademiaForm,
)
from .integraciones.consultorioweb import ConsultorioWebError
from .integraciones.importador_recepcion import importar_citas
from .integraciones.reporte_recepcion import ReporteRecepcionError, leer_reporte_api, leer_reporte_excel
from .models import (
    Ajuste, CategoriaEgreso, CitaRecepcion, ConceptoIngreso, Donativo, Egreso,
    Ingreso, LineaNominaSemanal, Maestro, NominaAcademia, NominaSemanal,
    TabuladorAcademia, Unidad,
)
from .nomina_academia import (
    NominaAcademiaError, capturar_nomina_academia, reabrir_nomina_academia,
    sellar_nomina_academia, sellar_periodo_academia,
    totales_academia, totales_periodo_academia,
)
from .nomina_semanal import (
    NominaError, calcular_ingreso_generado, ingresos_generados_por_persona,
    marcar_pago, obtener_nomina, periodo_anterior, periodo_por_defecto,
    periodo_siguiente, reabrir_periodo, sellar_linea, sellar_periodo,
    sincronizar_nomina, totales_nomina,
)
from .pdfs import render_pdf
from .reportes import (
    MESES_ABREV, concentrado_donativos, estado_de_resultados, etiqueta_periodo,
    flujo_efectivo_xlsx, rango_pedido, sufijo_archivo,
)
from .totales import donativos_efectivos, egresos_efectivos, ingresos_efectivos, suma

# Tope de filas de la tabla de Ingresos. No es paginación: es un freno para no
# volcar miles de filas de golpe. La pantalla avisa cuándo está cortando.
LIMITE_FILAS_INGRESOS = 200


def _url_conservando_filtros(request, nombre_url):
    """URL de la vista con el querystring actual. El formulario de la tabla
    hace POST a la URL con filtros incluidos, así que tras guardar hay que
    devolver al usuario al mismo rango que estaba viendo, no al de por
    defecto."""
    base = reverse(nombre_url)
    querystring = request.GET.urlencode()
    return f'{base}?{querystring}' if querystring else base

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


def _actualizar_estatus_simple(request, modelo, campo_estatus, valores_validos):
    """Cambia el campo de estatus de un registro ya existente (Egreso o
    Donativo) desde un control inline en la tabla, sin pasar por
    /admin/. `valores_validos` es el conjunto de choices válidos del campo;
    cualquier otro valor se rechaza en vez de guardarse a ciegas. El cambio
    queda asentado en la bitácora."""
    obj = get_object_or_404(modelo, pk=request.POST.get('id'))
    valor = request.POST.get(campo_estatus)
    if valor not in valores_validos:
        messages.error(request, 'Estatus inválido.')
        return
    anterior = getattr(obj, campo_estatus)
    setattr(obj, campo_estatus, valor)
    obj.save(update_fields=[campo_estatus])
    registrar_cambio_de_campo(request.user, obj, campo_estatus, anterior, valor, etiqueta='estatus')
    messages.success(request, 'Estatus actualizado correctamente.')


def _guardar_con_bitacora(request, form, mensaje):
    """Guarda un formulario de alta y deja constancia de quién lo capturó."""
    obj = form.save()
    registrar(request.user, obj, RegistroAuditoria.Accion.CREO)
    messages.success(request, mensaje)
    return obj


# El criterio de "cuánto dinero es real" vive en totales.py porque también lo
# usan los documentos descargables (reportes.py). Los alias privados de abajo
# existen para no reescribir las decenas de llamadas de este archivo.
_suma = suma
_ingresos_efectivos = ingresos_efectivos
_egresos_efectivos = egresos_efectivos
_donativos_efectivos = donativos_efectivos


def _ingresos_por_concepto_efectivo(queryset):
    """Ingresos efectivos (ver _ingresos_efectivos) agrupados por concepto,
    para la gráfica de dona del tablero."""
    totales = {}
    for fila in queryset.filter(estatus=Ingreso.Estatus.PAGADO).values('concepto').annotate(total=Sum('monto')):
        totales[fila['concepto']] = totales.get(fila['concepto'], Decimal('0')) + (fila['total'] or Decimal('0'))
    for fila in queryset.filter(estatus=Ingreso.Estatus.PARCIAL).values('concepto').annotate(total=Sum('monto_pagado')):
        totales[fila['concepto']] = totales.get(fila['concepto'], Decimal('0')) + (fila['total'] or Decimal('0'))
    return totales


def _unidad_pedida(request):
    """Unidad seleccionada en el filtro del tablero. Cadena vacía = "Todos",
    que es también a lo que cae cualquier valor desconocido (mismo criterio
    que el filtro de estatus de Ingresos: se ignora en vez de dejar la
    pantalla vacía sin explicación)."""
    unidad = request.GET.get('unidad') or ''
    return unidad if unidad in Unidad.values else ''


def _de_unidad(queryset, unidad):
    """Recorta un queryset de Ingreso/Egreso a una unidad. Con "Todos" no
    filtra nada: cada movimiento pertenece a una sola unidad, así que la
    suma de Intra y Academia es exactamente el total."""
    return queryset.filter(unidad=unidad) if unidad else queryset


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

    # Todo el tablero (KPIs, barras, dona, movimientos y pendientes) se lee
    # con la unidad elegida. Los Donativos no: no pertenecen ni a la clínica
    # ni a la escuela, son de la institución, así que no tienen campo
    # `unidad` y se muestran igual en las tres vistas — el KPI lo dice.
    unidad = _unidad_pedida(request)
    ingresos_todos = _de_unidad(Ingreso.objects.all(), unidad)
    egresos_todos = _de_unidad(Egreso.objects.all(), unidad)

    ingresos_mes = ingresos_todos.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    egresos_mes = egresos_todos.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    donativos_mes = Donativo.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)

    ingresos_mes_ant = _ingresos_efectivos(ingresos_todos.filter(fecha__year=anio_ant, fecha__month=mes_ant))
    egresos_mes_ant = _egresos_efectivos(egresos_todos.filter(fecha__year=anio_ant, fecha__month=mes_ant))
    donativos_mes_ant = _donativos_efectivos(Donativo.objects.filter(fecha__year=anio_ant, fecha__month=mes_ant))

    # Solo cuenta dinero real: un Ingreso/Egreso Pendiente no suma al tablero
    # hasta que se marca Pagado (o, en Ingreso, lo que ya se cobró si está
    # Parcial). Un Donativo Cancelado tampoco suma.
    total_ingresos = _ingresos_efectivos(ingresos_mes)
    total_egresos = _egresos_efectivos(egresos_mes)
    total_donativos = _donativos_efectivos(donativos_mes)
    balance_neto = total_ingresos - total_egresos
    balance_neto_ant = ingresos_mes_ant - egresos_mes_ant

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
        kpi(
            'Donativos (institucional)' if unidad else 'Donativos',
            total_donativos, donativos_mes_ant, '#15B3C7',
        ),
    ]

    barras = []
    for anio, mes in _meses_recientes(6):
        ing = _ingresos_efectivos(ingresos_todos.filter(fecha__year=anio, fecha__month=mes))
        egr = _egresos_efectivos(egresos_todos.filter(fecha__year=anio, fecha__month=mes))
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
    # Filtrando por unidad no se listan: un donativo no es un movimiento de
    # Intra ni de Academia, y mezclarlo aquí haría que la lista no cuadre con
    # los KPIs de arriba.
    if not unidad:
        for d in donativos_mes.exclude(estatus_cfdi=Donativo.EstatusCFDI.CANCELADO).order_by('-fecha')[:5]:
            recientes.append({
                'concepto': f'Donativo {d.get_tipo_display().lower()}', 'meta': d.donante_nombre,
                'monto': _dinero(d.monto), 'signo': '+', 'fecha': d.fecha,
            })
    recientes.sort(key=lambda r: r['fecha'], reverse=True)
    recientes = recientes[:5]

    # Acumulado del año, sin meta: cuánto se ha recibido y en cuántos
    # donativos. Hubo una barra contra una meta anual de $2,000,000, pero ese
    # número estaba escrito a mano en el código y nadie pudo confirmar de
    # dónde salía, así que se quitó (decisión del usuario, 2026-07-31).
    donativos_anio_qs = Donativo.objects.filter(fecha__year=hoy.year).exclude(
        estatus_cfdi=Donativo.EstatusCFDI.CANCELADO
    )
    donativos_anio = {
        'anio': hoy.year,
        'acumulado': _dinero(_suma(donativos_anio_qs)),
        'cantidad': donativos_anio_qs.count(),
    }

    # Los pagos a terapeutas ya no se calculan aquí (ver Nómina): lo que
    # queda por pagar son Egresos pendientes, vengan del sellado de una
    # nómina o de una captura manual.
    #
    # A propósito sin filtrar por mes, a diferencia de los KPIs de arriba: un
    # egreso pendiente de hace tres meses sigue pendiente y es justo el que no
    # se debe perder de vista. Por eso el resumen va aparte del recorte a 6 —
    # el badge tiene que decir cuántos hay en total, no cuántos se alcanzan a
    # pintar.
    pendientes_qs = egresos_todos.filter(estatus=Egreso.Estatus.PENDIENTE)
    pendientes = [
        {
            'titulo': e.persona or e.concepto,
            'meta': e.get_categoria_display(),
            'total': _dinero(e.monto),
        }
        for e in pendientes_qs.order_by('-monto')[:6]
    ]
    pendientes_resumen = {
        'mostrados': len(pendientes),
        'total_registros': pendientes_qs.count(),
        'monto': _dinero(_suma(pendientes_qs)),
    }

    contexto = {
        'vista_actual': 'tablero',
        'unidad_filtro': unidad,
        'unidad_etiqueta': Unidad(unidad).label if unidad else 'Todos',
        'unidad_choices': Unidad.choices,
        'kpis': kpis,
        'barras': barras,
        'concepto_legend': concepto_legend,
        'donut_gradient': donut_gradient,
        'donut_total': _dinero(total_ingresos),
        'recientes': recientes,
        'donativos_anio': donativos_anio,
        'pendientes': pendientes,
        'pendientes_resumen': pendientes_resumen,
        'form_ingreso': IngresoForm(initial={'fecha': hoy}),
        'form_egreso': EgresoForm(initial={'fecha': hoy}),
        'form_donativo': DonativoForm(initial={'fecha': hoy}),
    }
    return render(request, 'finanzas/tablero.html', contexto)


@acceso_finanzas_requerido
def ingresos_view(request):
    hoy = timezone.now().date()

    if request.method == 'POST':
        if request.POST.get('accion') == 'estatus':
            ingreso = get_object_or_404(Ingreso, pk=request.POST.get('id'))
            estatus = request.POST.get('estatus')
            try:
                monto_pagado = Decimal(request.POST.get('monto_pagado') or '0')
            except InvalidOperation:
                monto_pagado = Decimal('0')
            if estatus not in Ingreso.Estatus.values:
                messages.error(request, 'Estatus inválido.')
            elif estatus == Ingreso.Estatus.PARCIAL and monto_pagado > ingreso.monto:
                messages.error(request, 'Lo cobrado no puede ser mayor que el monto total.')
            else:
                estatus_anterior = ingreso.estatus
                cobrado_anterior = ingreso.monto_pagado
                ingreso.estatus = estatus
                ingreso.monto_pagado = monto_pagado if estatus == Ingreso.Estatus.PARCIAL else Decimal('0')
                ingreso.save(update_fields=['estatus', 'monto_pagado'])
                registrar_cambio_de_campo(
                    request.user, ingreso, 'estatus', estatus_anterior, estatus, etiqueta='estatus',
                )
                registrar_cambio_de_campo(
                    request.user, ingreso, 'monto_pagado', cobrado_anterior, ingreso.monto_pagado,
                    etiqueta='cobrado',
                )
                messages.success(request, 'Estatus actualizado correctamente.')
            return redirect(_url_conservando_filtros(request, 'finanzas:ingresos'))
        form_ingreso = IngresoForm(request.POST)
        if form_ingreso.is_valid():
            _guardar_con_bitacora(request, form_ingreso, 'Ingreso registrado correctamente.')
            return redirect(_url_conservando_filtros(request, 'finanzas:ingresos'))
    else:
        form_ingreso = IngresoForm(initial={'fecha': hoy})

    # El filtro manda sobre TODO lo que se ve: las tres cifras y la tabla
    # salen del mismo queryset. Antes las cifras eran del mes en curso y la
    # tabla los últimos 200 de cualquier fecha, así que el encabezado y las
    # filas describían periodos distintos (y con 239 ingresos en un mes, la
    # tabla ni siquiera alcanzaba a mostrar el mes que estaba resumiendo).
    fecha_inicio = _fecha_desde_query(request, 'fecha_inicio') or hoy.replace(day=1)
    fecha_fin = _fecha_desde_query(request, 'fecha_fin') or hoy
    if fecha_inicio > fecha_fin:
        messages.error(request, 'El rango de fechas no es válido: "Desde" es posterior a "Hasta".')
        fecha_inicio, fecha_fin = hoy.replace(day=1), hoy

    # Un estatus que no exista se ignora en vez de dejar la tabla vacía sin
    # explicación (mismo criterio que _actualizar_estatus_simple).
    estatus_filtro = request.GET.get('estatus') or ''
    if estatus_filtro not in Ingreso.Estatus.values:
        estatus_filtro = ''

    ingresos_filtrados = Ingreso.objects.filter(fecha__gte=fecha_inicio, fecha__lte=fecha_fin)
    if estatus_filtro:
        ingresos_filtrados = ingresos_filtrados.filter(estatus=estatus_filtro)

    # Se diferencia el total capturado (lo que se debe cobrar en total) de
    # lo efectivamente cobrado (Pagado completo + la parte ya cobrada de un
    # Parcial) y lo que todavía falta por cobrar — antes "Cobrado" solo veía
    # los Pagado completos e ignoraba lo ya cobrado de un Parcial.
    total_capturado = _suma(ingresos_filtrados)
    cobrado = _ingresos_efectivos(ingresos_filtrados)
    stats = [
        {'label': 'Total capturado', 'value': _dinero(total_capturado), 'color': '#1B2C4F'},
        {'label': 'Cobrado', 'value': _dinero(cobrado), 'color': '#1F8A5B'},
        {'label': 'Pendiente por cobrar', 'value': _dinero(total_capturado - cobrado), 'color': '#9A6B12'},
    ]

    # El tope se queda como red de seguridad, pero ahora la pantalla dice
    # cuántos hay en total: un corte silencioso es peor que un corte visible.
    total_en_rango = ingresos_filtrados.count()
    filas = ingresos_filtrados.select_related('terapeuta').order_by('-fecha')[:LIMITE_FILAS_INGRESOS]

    contexto = {
        'vista_actual': 'ingresos',
        'stats': stats,
        'ingresos': filas,
        'form_ingreso': form_ingreso,
        'estatus_choices': Ingreso.Estatus.choices,
        'fecha_inicio': fecha_inicio.isoformat(),
        'fecha_fin': fecha_fin.isoformat(),
        'estatus_filtro': estatus_filtro,
        'total_en_rango': total_en_rango,
        'mostradas': min(total_en_rango, LIMITE_FILAS_INGRESOS),
        'hay_corte': total_en_rango > LIMITE_FILAS_INGRESOS,
    }
    return render(request, 'finanzas/ingresos.html', contexto)


@acceso_finanzas_requerido
def egresos_view(request):
    hoy = timezone.now().date()

    form_egreso = EgresoForm(initial={'fecha': hoy})

    if request.method == 'POST':
        if request.POST.get('accion') == 'estatus_egreso':
            _actualizar_estatus_simple(request, Egreso, 'estatus', Egreso.Estatus.values)
            return redirect('finanzas:egresos')
        form_egreso = EgresoForm(request.POST)
        if form_egreso.is_valid():
            _guardar_con_bitacora(request, form_egreso, 'Egreso registrado correctamente.')
            return redirect('finanzas:egresos')

    egresos_mes = Egreso.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month).order_by('-fecha')
    contexto = {
        'vista_actual': 'egresos',
        'egresos': egresos_mes,
        'total_egresos_periodo': _dinero(_suma(egresos_mes)),
        'form_egreso': form_egreso,
        'egreso_estatus_choices': Egreso.Estatus.choices,
    }
    return render(request, 'finanzas/egresos.html', contexto)


def _periodo_de_nomina(request, hoy):
    """Tipo y rango del periodo elegido en la pantalla de Nómina. El rango
    inicial es la semana de nómina de INTRA (viernes→jueves), igual para los
    tres tipos; el usuario puede moverlo."""
    tipo = request.GET.get('tipo') or request.POST.get('tipo') or NominaSemanal.Tipo.SEMANAL
    if tipo not in NominaSemanal.Tipo.values:
        tipo = NominaSemanal.Tipo.SEMANAL

    inicio_defecto, fin_defecto = periodo_por_defecto(hoy)
    inicio = _fecha_desde_query(request, 'fecha_inicio') or inicio_defecto
    fin = _fecha_desde_query(request, 'fecha_fin') or fin_defecto
    if request.method == 'POST':
        inicio = _fecha_desde_post(request, 'fecha_inicio') or inicio
        fin = _fecha_desde_post(request, 'fecha_fin') or fin
    return tipo, inicio, fin


def _url_nomina(tipo, inicio, fin):
    return (
        f"{reverse('finanzas:nomina')}?tipo={tipo}"
        f'&fecha_inicio={inicio.isoformat()}&fecha_fin={fin.isoformat()}'
    )


def _url_nomina_academia(mes, anio):
    """URL de la pantalla de Nómina Academia para un periodo (mes/año)."""
    return f"{reverse('finanzas:nomina_academia')}?mes={mes}&anio={anio}"


def _periodo_academia_adyacente(mes, anio, delta_meses):
    """Devuelve (mes, anio) desplazado `delta_meses` meses desde mes/anio."""
    ref = date(anio, mes, 1)
    if delta_meses >= 0:
        nuevo = ref
        for _ in range(delta_meses):
            nuevo = date(
                nuevo.year + (1 if nuevo.month == 12 else 0),
                (nuevo.month % 12) + 1, 1,
            )
    else:
        nuevo = ref
        for _ in range(-delta_meses):
            nuevo = date(
                nuevo.year - (1 if nuevo.month == 1 else 0),
                (nuevo.month - 2) % 12 + 1, 1,
            )
    return nuevo.month, nuevo.year


def _guardar_borrador_nomina(request, nomina):
    """Guarda de un golpe los cambios hechos en la tabla: método de pago,
    observaciones y los tres montos. Solo toca líneas no selladas — una vez
    sellada, la corrección es un Ajuste, no una edición."""
    cambios = 0
    for linea in nomina.lineas.filter(sellada=False):
        metodo = request.POST.get(f'metodo_{linea.id}')
        observaciones = request.POST.get(f'obs_{linea.id}', '').strip()
        campos = {}
        if metodo in LineaNominaSemanal.MetodoPago.values and metodo != linea.metodo_pago:
            campos['metodo_pago'] = (linea.metodo_pago, metodo)
        if observaciones != linea.observaciones:
            campos['observaciones'] = (linea.observaciones, observaciones)
        monto_cambiado = False
        for campo, prefijo in (('pago_base', 'base'), ('vale_gasolina', 'vale'), ('extras', 'extra')):
            crudo = request.POST.get(f'{prefijo}_{linea.id}')
            if crudo is None:
                continue
            try:
                valor = Decimal(crudo or '0')
            except InvalidOperation:
                continue
            if valor < 0:
                continue
            if valor != getattr(linea, campo):
                campos[campo] = (getattr(linea, campo), valor)
                monto_cambiado = True
        if not campos:
            continue
        if monto_cambiado and not linea.montos_editados:
            # Marca la línea para que la próxima sincronización no pise la
            # corrección (ver LineaNominaSemanal.montos_editados).
            campos['montos_editados'] = (False, True)
        for campo, (_, nuevo) in campos.items():
            setattr(linea, campo, nuevo)
        linea.save(update_fields=list(campos))
        for campo, (anterior, nuevo) in campos.items():
            if campo == 'montos_editados':
                continue  # bandera interna, no es un dato de negocio que auditar
            registrar_cambio_de_campo(request.user, linea, campo, anterior, nuevo)
        cambios += 1
    return cambios


@acceso_finanzas_requerido
def nomina_view(request):
    """Nómina por periodo con su ciclo de vida completo (secciones 3 y 7 del
    documento): se sincroniza en Borrador, se revisa persona por persona, y
    al sellar —por persona o el periodo entero— nacen los Egresos.

    La nómina semanal se llena desde ConsultorioWeb; la quincenal y la
    administrativa se capturan a mano en esta misma pantalla."""
    hoy = timezone.now().date()
    tipo, fecha_inicio, fecha_fin = _periodo_de_nomina(request, hoy)
    nomina = obtener_nomina(tipo, fecha_inicio, fecha_fin)

    if request.method == 'POST':
        accion = request.POST.get('accion')
        destino = _url_nomina(tipo, fecha_inicio, fecha_fin)

        if accion == 'sincronizar':
            try:
                nomina, resumen = sincronizar_nomina(fecha_inicio, fecha_fin, request.user)
                mensaje = (
                    f"Sincronizado con ConsultorioWeb: {resumen['nuevas']} persona(s) nueva(s), "
                    f"{resumen['actualizadas']} actualizada(s)."
                )
                if resumen['selladas']:
                    mensaje += f" {resumen['selladas']} ya estaban selladas y no se tocaron."
                if resumen['con_error']:
                    mensaje += f" {resumen['con_error']} corte(s) se omitieron por datos inesperados."
                messages.success(request, mensaje)
            except ConsultorioWebError as exc:
                messages.error(request, str(exc))
            return redirect(destino)

        if nomina is None:
            if accion == 'linea_manual':
                nomina = NominaSemanal.objects.create(
                    tipo=tipo, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                    usuario_genera=request.user,
                )
                registrar(request.user, nomina, RegistroAuditoria.Accion.CREO)
            else:
                messages.error(request, 'Todavía no existe una nómina para ese periodo.')
                return redirect(destino)

        if accion == 'linea_manual':
            form_linea = LineaNominaManualForm(request.POST, nomina=nomina)
            if form_linea.is_valid():
                if nomina.esta_sellada:
                    messages.error(request, 'Esta nómina ya está sellada; usa un Ajuste para corregirla.')
                else:
                    linea = form_linea.save(commit=False)
                    linea.nomina = nomina
                    linea.save()
                    registrar(request.user, linea, RegistroAuditoria.Accion.CREO)
                    messages.success(request, f'{linea.persona} agregado a la nómina.')
                return redirect(destino)
            # Con errores se vuelve a pintar la pantalla con el modal abierto.
        elif accion == 'guardar_borrador':
            cambios = _guardar_borrador_nomina(request, nomina)
            messages.success(
                request,
                f'Borrador guardado: {cambios} línea(s) actualizada(s).' if cambios
                else 'No hubo cambios que guardar.',
            )
            return redirect(destino)
        elif accion == 'sellar_linea':
            # El botón "Sellar" de una fila envía el mismo <form> que trae los
            # inputs de método/observaciones/montos de TODAS las filas: si no
            # se guardan aquí primero, sellar_linea() lee de la base de datos
            # los valores de ANTES de la edición y lo que se ve en pantalla
            # (método de pago recién cambiado, observaciones recién escritas)
            # se pierde en silencio.
            _guardar_borrador_nomina(request, nomina)
            linea = get_object_or_404(LineaNominaSemanal, pk=request.POST.get('id'), nomina=nomina)
            try:
                creados = sellar_linea(linea, request.user)
                messages.success(
                    request,
                    f'{linea.persona} sellado: se generaron {len(creados)} egreso(s) por '
                    f'{_dinero(linea.total)}.',
                )
            except NominaError as exc:
                messages.error(request, str(exc))
            return redirect(destino)
        elif accion == 'sellar_periodo':
            try:
                resultado = sellar_periodo(
                    nomina, request.user, _fecha_desde_post(request, 'fecha_pago'),
                )
                mensaje = f"Nómina sellada: {resultado['selladas']} persona(s)."
                if resultado['omitidas']:
                    mensaje += f" {resultado['omitidas']} se omitieron por estar en cero."
                messages.success(request, mensaje)
            except NominaError as exc:
                messages.error(request, str(exc))
            return redirect(destino)
        elif accion == 'reabrir_periodo':
            try:
                resultado = reabrir_periodo(nomina, request.user)
                messages.success(
                    request,
                    f"Nómina reabierta a Borrador: {resultado['lineas']} línea(s), "
                    f"{resultado['egresos_eliminados']} egreso(s) eliminado(s).",
                )
            except NominaError as exc:
                messages.error(request, str(exc))
            return redirect(destino)
        elif accion == 'estatus_pago':
            linea = get_object_or_404(LineaNominaSemanal, pk=request.POST.get('id'), nomina=nomina)
            try:
                marcar_pago(linea, request.POST.get('estatus_pago'), request.user)
                messages.success(request, 'Estatus de pago actualizado.')
            except NominaError as exc:
                messages.error(request, str(exc))
            return redirect(destino)
        else:
            return redirect(destino)
    else:
        form_linea = LineaNominaManualForm()

    # Al abrir por primera vez un periodo semanal, la nómina se trae sola:
    # el documento pide que el egreso aparezca sin doble captura. En las
    # visitas siguientes no se vuelve a llamar a la API (sería lento en cada
    # recarga); para eso está el botón "Sincronizar ahora".
    aviso_sync = None
    if (
        request.method == 'GET' and nomina is None
        and tipo == NominaSemanal.Tipo.SEMANAL and settings.CONSULTORIOWEB_API_URL
    ):
        try:
            nomina, resumen = sincronizar_nomina(fecha_inicio, fecha_fin, request.user)
            if resumen['nuevas']:
                aviso_sync = f"Se trajeron {resumen['nuevas']} persona(s) de ConsultorioWeb."
        except ConsultorioWebError as exc:
            aviso_sync = f'No se pudo sincronizar con ConsultorioWeb: {exc}'

    lineas = list(nomina.lineas.all()) if nomina else []
    # El ingreso generado se resuelve al mostrar, no al sincronizar: si
    # Recepción se sincroniza después de la nómina (que es el orden normal),
    # la columna se actualiza sola.
    ingresos_recepcion = ingresos_generados_por_persona(fecha_inicio, fecha_fin)
    for linea in lineas:
        linea.ingreso_generado_actual = ingresos_recepcion.get(linea.persona)
    sin_recepcion = tipo == NominaSemanal.Tipo.SEMANAL and lineas and not ingresos_recepcion

    contexto = {
        'vista_actual': 'nomina',
        'tipo': tipo,
        'tipos': NominaSemanal.Tipo.choices,
        'fecha_inicio': fecha_inicio.isoformat(),
        'fecha_fin': fecha_fin.isoformat(),
        'nomina': nomina,
        'lineas': lineas,
        'totales': totales_nomina(nomina) if nomina else None,
        'hay_por_sellar': any(not l.sellada and l.total > 0 for l in lineas),
        'sin_recepcion': sin_recepcion,
        'url_anterior': _url_nomina(tipo, *periodo_anterior(fecha_inicio)),
        'url_siguiente': _url_nomina(tipo, *periodo_siguiente(fecha_fin)),
        'url_periodo_actual': _url_nomina(tipo, *periodo_por_defecto(hoy)),
        # El pago se entrega el día que cierra el periodo (jueves en la
        # semanal); es el valor que se propone al sellar.
        'fecha_pago_sugerida': (nomina.fecha_pago or fecha_fin).isoformat() if nomina else fecha_fin.isoformat(),
        'metodos': LineaNominaSemanal.MetodoPago.choices,
        'estatus_pago_choices': LineaNominaSemanal.EstatusPago.choices,
        'form_linea': form_linea,
        'api_configurada': bool(settings.CONSULTORIOWEB_API_URL),
        'es_semanal': tipo == NominaSemanal.Tipo.SEMANAL,
        'aviso_sync': aviso_sync,
        'hoy': hoy.isoformat(),
    }
    return render(request, 'finanzas/nomina.html', contexto)


@acceso_finanzas_requerido
def nomina_linea_view(request, linea_id):
    """Botón "Ver detalle" de la sección 7: el desglose por paciente que
    respalda el monto de esa persona, para revisarlo antes de sellar."""
    linea = get_object_or_404(
        LineaNominaSemanal.objects.select_related('nomina'), pk=linea_id,
    )
    detalle = linea.detalle_json if isinstance(linea.detalle_json, list) else []
    linea.ingreso_generado_actual = calcular_ingreso_generado(
        linea.persona, linea.nomina.fecha_inicio, linea.nomina.fecha_fin,
    )
    contexto = {
        'vista_actual': 'nomina',
        'linea': linea,
        'nomina': linea.nomina,
        'detalle': detalle,
        'total_detalle': sum((Decimal(str(d.get('monto') or 0)) for d in detalle), Decimal('0')),
        'egresos': linea.egresos.all(),
        'volver': _url_nomina(
            linea.nomina.tipo, linea.nomina.fecha_inicio, linea.nomina.fecha_fin,
        ),
    }
    return render(request, 'finanzas/nomina_linea.html', contexto)


@acceso_finanzas_requerido
def nomina_descargar_view(request, nomina_id):
    """PDF descargable de la nómina (sección 4 del documento): encabezado con
    tipo, periodo, fecha de pago y estado; tabla por persona con los tres
    conceptos separados y observaciones; y los cuatro totales que se usan
    para solicitar la dispersión del dinero."""
    nomina = get_object_or_404(
        NominaSemanal.objects.select_related('usuario_genera').prefetch_related('lineas'),
        pk=nomina_id,
    )
    contexto = {
        'nomina': nomina,
        'lineas': nomina.lineas.all(),
        'totales': totales_nomina(nomina),
        'generado_en': timezone.now(),
    }
    nombre_archivo = (
        f'nomina_{nomina.tipo}_{nomina.fecha_inicio.isoformat()}_{nomina.fecha_fin.isoformat()}.pdf'
    )
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
                registrar(
                    request.user, None, RegistroAuditoria.Accion.IMPORTO,
                    detalle=f'Reporte de Recepción vía API {fecha_inicio_str} a {fecha_fin_str}: '
                            f"{resumen['creadas']} nuevas, {resumen['actualizadas']} actualizadas.",
                )
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
                registrar(
                    request.user, None, RegistroAuditoria.Accion.IMPORTO,
                    detalle=f'Reporte de Recepción vía Excel: {resumen["creadas"]} nuevas, '
                            f'{resumen["actualizadas"]} actualizadas.',
                )
                messages.success(
                    request,
                    f"Reporte importado desde Excel: {resumen['creadas']} citas nuevas, "
                    f"{resumen['actualizadas']} actualizadas "
                    f"({resumen['con_ingreso']} generaron ingreso).",
                )
            except ReporteRecepcionError as exc:
                messages.error(request, str(exc))
            return redirect('finanzas:reporte_recepcion')
        # Formulario inválido (ej. archivo que no es .xlsx): antes esto
        # redirigía igual sin mostrar ningún error, y el usuario veía la
        # pantalla exactamente igual que antes de intentar subir el archivo.
        messages.error(
            request,
            form_upload.errors.get('archivo', ['No se pudo subir el archivo.'])[0],
        )
        return redirect('finanzas:reporte_recepcion')

    form_upload = ReporteRecepcionUploadForm()
    fecha_inicio = _fecha_desde_query(request, 'fecha_inicio') or (hoy - timedelta(weeks=4))
    fecha_fin = _fecha_desde_query(request, 'fecha_fin') or hoy
    if fecha_inicio > fecha_fin:
        messages.error(request, 'El rango de fechas no es válido: "Desde" es posterior a "Hasta".')
        fecha_inicio, fecha_fin = hoy - timedelta(weeks=4), hoy
    terapeuta = request.GET.get('terapeuta') or ''

    # El rango y el terapeuta filtran de verdad lo que se muestra. Antes solo
    # servían para sincronizar, y los KPIs, el ranking y el comparativo se
    # calculaban sobre TODO el histórico — un reporte de julio mostrando
    # números de todo el año.
    citas = CitaRecepcion.objects.filter(fecha__gte=fecha_inicio, fecha__lte=fecha_fin)
    if terapeuta:
        citas = citas.filter(terapeuta=terapeuta)

    asistidas = citas.filter(estatus=CitaRecepcion.Estatus.SI_ASISTIO)
    total_citas = citas.count()
    # La tarjeta "Citas con asistencia confirmada" es más amplia que el
    # ranking/ingreso (que solo cuentan "Sí asistió", ver _ingresos_efectivos
    # y el banner de esta pantalla): también cuenta las citas en "Confirmada"
    # a pedido de Administración, aunque todavía no se hayan atendido.
    total_asistidas = citas.filter(
        estatus__in=[CitaRecepcion.Estatus.SI_ASISTIO, CitaRecepcion.Estatus.CONFIRMADA]
    ).count()
    # Pacientes distintos atendidos (criterio 6 del documento: los datos de
    # recepción deben alimentar también el conteo de pacientes).
    total_pacientes = asistidas.values('paciente').distinct().count()
    total_ingresos_generados = _suma(
        Ingreso.objects.filter(cita_recepcion__in=citas)
    )
    terapeutas = (
        CitaRecepcion.objects.filter(fecha__gte=fecha_inicio, fecha__lte=fecha_fin)
        .values_list('terapeuta', flat=True).distinct().order_by('terapeuta')
    )

    ranking = (
        asistidas.values('terapeuta')
        .annotate(citas_atendidas=Count('id'), total_generado=Sum('costo'))
        .order_by('-total_generado')[:10]
    )
    for fila in ranking:
        fila['total_generado_fmt'] = _dinero(fila['total_generado'] or Decimal('0'))

    por_metodo = (
        asistidas.exclude(metodo_pago='')
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
        'fecha_inicio': fecha_inicio.isoformat(),
        'fecha_fin': fecha_fin.isoformat(),
        'terapeuta': terapeuta,
        'terapeutas': terapeutas,
        'api_configurada': bool(settings.CONSULTORIOWEB_API_URL),
        'total_citas': total_citas,
        'total_asistidas': total_asistidas,
        'total_pacientes': total_pacientes,
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
        if request.POST.get('accion') == 'estatus_donativo':
            _actualizar_estatus_simple(request, Donativo, 'estatus_cfdi', Donativo.EstatusCFDI.values)
            return redirect('finanzas:donativos')
        form_donativo = DonativoForm(request.POST, request.FILES)
        if form_donativo.is_valid():
            _guardar_con_bitacora(request, form_donativo, 'Donativo registrado correctamente.')
            return redirect('finanzas:donativos')
    else:
        form_donativo = DonativoForm(initial={'fecha': hoy})

    donativos_mes = Donativo.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    donativos_anio = Donativo.objects.filter(fecha__year=hoy.year)
    # Sin meta anual: había una de $2,000,000 escrita a mano en el código,
    # sin nada que respaldara ese número (se quitó junto con la del tablero,
    # 2026-07-31). El subtítulo dice cuántos donativos hay detrás del monto.
    cuenta_anio = donativos_anio.exclude(estatus_cfdi=Donativo.EstatusCFDI.CANCELADO).count()
    stats = [
        # Un CFDI Cancelado nunca fue dinero real: no suma en ninguna de
        # estas tarjetas (mismo criterio que el tablero).
        {'label': 'Donativos del mes', 'value': _dinero(_donativos_efectivos(donativos_mes)), 'sub': f'{donativos_mes.count()} donantes'},
        {'label': f'Acumulado {hoy.year}', 'value': _dinero(_donativos_efectivos(donativos_anio)), 'sub': f'{cuenta_anio} donativo{"s" if cuenta_anio != 1 else ""}'},
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
        'estatus_cfdi_choices': Donativo.EstatusCFDI.choices,
    }
    return render(request, 'finanzas/donativos.html', contexto)


@acceso_finanzas_requerido
def nomina_academia_view(request):
    """Captura la nómina de Academia por maestro/periodo: selecciona
    maestro, captura cantidades por concepto (horas clase, supervisión,
    mesa de trabajo, más un concepto manual autorizado opcional) y calcula
    el total con los tabuladores vigentes (sección 6 del documento).

    La captura deja la nómina en Borrador; los Egresos se generan al sellar,
    por docente o por periodo completo."""
    hoy = timezone.now().date()

    form = NominaAcademiaCaptureForm(initial={'periodo_mes': hoy.month, 'periodo_anio': hoy.year})
    form_maestro = MaestroForm()
    form_tabulador_academia = TabuladorAcademiaForm(initial={'vigente_desde': hoy})

    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'maestro':
            form_maestro = MaestroForm(request.POST)
            if form_maestro.is_valid():
                _guardar_con_bitacora(request, form_maestro, 'Maestro agregado correctamente.')
                return redirect('finanzas:nomina_academia')
        elif accion == 'tabulador_academia':
            form_tabulador_academia = TabuladorAcademiaForm(request.POST)
            if form_tabulador_academia.is_valid():
                _guardar_con_bitacora(request, form_tabulador_academia, 'Tabulador de Academia registrado correctamente.')
                return redirect('finanzas:nomina_academia')
        elif accion == 'eliminar_tabulador_academia':
            tabulador = get_object_or_404(TabuladorAcademia, pk=request.POST.get('id'))
            try:
                tabulador.delete()
            except ProtectedError:
                messages.error(
                    request,
                    'No se puede eliminar: ya se usó para calcular al menos una nómina de Academia. '
                    'Registra un tabulador nuevo con la tarifa correcta en su lugar.',
                )
            else:
                registrar(request.user, None, RegistroAuditoria.Accion.ELIMINO, detalle=f'Tabulador de Academia: {tabulador}.')
                messages.success(request, 'Tabulador de Academia eliminado correctamente.')
            return redirect('finanzas:nomina_academia')
        elif accion == 'sellar_academia':
            nomina = get_object_or_404(NominaAcademia, pk=request.POST.get('id'))
            try:
                sellar_nomina_academia(nomina, request.user, _fecha_desde_post(request, 'fecha_pago'))
                messages.success(
                    request,
                    f'Nómina de {nomina.maestro} sellada: se generaron sus egresos por '
                    f'{_dinero(nomina.total)}.',
                )
            except NominaAcademiaError as exc:
                messages.error(request, str(exc))
            return redirect('finanzas:nomina_academia')
        elif accion == 'reabrir_academia':
            nomina = get_object_or_404(NominaAcademia, pk=request.POST.get('id'))
            try:
                borrados = reabrir_nomina_academia(nomina, request.user)
                messages.success(
                    request,
                    f'Nómina de {nomina.maestro} reabierta a Borrador: {borrados} egreso(s) eliminado(s).',
                )
            except NominaAcademiaError as exc:
                messages.error(request, str(exc))
            return redirect('finanzas:nomina_academia')
        elif accion == 'sellar_periodo_academia':
            mes = int(request.POST.get('periodo_mes') or hoy.month)
            anio = int(request.POST.get('periodo_anio') or hoy.year)
            try:
                resultado = sellar_periodo_academia(
                    mes, anio, request.user, _fecha_desde_post(request, 'fecha_pago'),
                )
                mensaje = f"Periodo {mes}/{anio} sellado: {resultado['selladas']} docente(s)."
                if resultado['omitidas']:
                    mensaje += f" {resultado['omitidas']} se omitieron por no tener conceptos con monto."
                messages.success(request, mensaje)
            except NominaAcademiaError as exc:
                messages.error(request, str(exc))
            return redirect('finanzas:nomina_academia')
        elif accion == 'estatus_academia':
            nomina = get_object_or_404(NominaAcademia, pk=request.POST.get('id'))
            if nomina.esta_sellada:
                messages.error(request, 'Esta nómina ya está sellada; su estatus de pago no se puede modificar.')
            else:
                _actualizar_estatus_simple(request, NominaAcademia, 'estatus', NominaAcademia.Estatus.values)
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
                        usuario=request.user,
                    )
                    messages.success(
                        request,
                        f"Nómina de Academia capturada en borrador: {nomina.maestro} · "
                        f"{nomina.periodo_mes}/{nomina.periodo_anio} · total {_dinero(nomina.total)}. "
                        'Revísala y séllala para generar los egresos.',
                    )
                except (DuplicadoError, NominaAcademiaError) as exc:
                    messages.error(request, str(exc))
                return redirect('finanzas:nomina_academia')

    mes = hoy.month
    anio = hoy.year
    try:
        mes_q = int(request.GET.get('mes') or '')
        anio_q = int(request.GET.get('anio') or '')
        if 1 <= mes_q <= 12 and 1900 <= anio_q <= 2200:
            mes, anio = mes_q, anio_q
    except (TypeError, ValueError):
        pass

    nominas = (
        NominaAcademia.objects.select_related('maestro', 'usuario_genera')
        .prefetch_related('conceptos')
        .filter(periodo_mes=mes, periodo_anio=anio)
        .order_by('maestro__nombre')
    )
    periodos = (
        NominaAcademia.objects.values('periodo_anio', 'periodo_mes')
        .distinct().order_by('-periodo_anio', '-periodo_mes')[:12]
    )
    for p in periodos:
        p['etiqueta'] = f"{MESES_ABREV[p['periodo_mes']]} {p['periodo_anio']}"
    totales = totales_academia(
        NominaAcademia.objects.filter(periodo_mes=mes, periodo_anio=anio),
    )
    mes_ant, anio_ant = _periodo_academia_adyacente(mes, anio, -1)
    mes_sig, anio_sig = _periodo_academia_adyacente(mes, anio, 1)
    contexto = {
        'vista_actual': 'nomina_academia',
        'form': form,
        'form_maestro': form_maestro,
        'form_tabulador_academia': form_tabulador_academia,
        'nominas': nominas,
        'periodos': periodos,
        'hay_borradores': any(not n.esta_sellada for n in nominas),
        'estatus_choices': NominaAcademia.Estatus.choices,
        'maestros': Maestro.objects.order_by('-activo', 'nombre'),
        'tabuladores_academia': TabuladorAcademia.objects.order_by('concepto', '-vigente_desde'),
        'hoy': hoy.isoformat(),
        'periodo_mes': mes,
        'periodo_anio': anio,
        'mes_actual': hoy.month,
        'anio_actual': hoy.year,
        'meses': [(m, MESES_ABREV[m]) for m in range(1, 13)],
        'anios': list(range(hoy.year - 2, hoy.year + 2)),
        'totales': totales,
        'periodo_totales': f'{MESES_ABREV[mes]} {anio}',
        'url_anterior': _url_nomina_academia(mes_ant, anio_ant),
        'url_siguiente': _url_nomina_academia(mes_sig, anio_sig),
        'url_periodo_actual': _url_nomina_academia(hoy.month, hoy.year),
    }
    return render(request, 'finanzas/nomina_academia.html', contexto)


@acceso_finanzas_requerido
def nomina_academia_descargar_view(request, nomina_id):
    nomina = get_object_or_404(
        NominaAcademia.objects.select_related('maestro', 'usuario_genera').prefetch_related('conceptos'),
        pk=nomina_id,
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
def nomina_academia_periodo_descargar_view(request, anio, mes):
    """Consolidado del periodo: todos los docentes del mes en un solo
    documento, con total por docente y total general (sección 6.1 del
    documento, "Totales")."""
    nominas, totales = totales_periodo_academia(mes, anio)
    totales.update(totales_academia(nominas))
    contexto = {
        'nominas': nominas,
        'totales': totales,
        'periodo_mes': mes,
        'periodo_anio': anio,
        'periodo_etiqueta': f'{MESES_ABREV[mes]} {anio}' if 1 <= mes <= 12 else f'{mes}/{anio}',
        'usuario_genera': request.user,
        'generado_en': timezone.now(),
    }
    nombre_archivo = f'nomina_academia_periodo_{anio}_{mes:02d}.pdf'
    return render_pdf('finanzas/nomina_academia_periodo_pdf.html', contexto, nombre_archivo)


@acceso_finanzas_requerido
def ajustes_view(request):
    """Corrige una Nómina Academia o un Egreso ya capturado sin
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
                    usuario=request.user,
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
def bitacora_view(request):
    """Histórico de cambios: quién, cuándo, qué registro, qué campo, y de qué
    valor a qué valor (sección 9 del documento de requerimientos, "Mantener
    historico de cambios: usuario, fecha, monto anterior, monto nuevo").
    Es de solo lectura a propósito — una bitácora que se puede editar no
    sirve como bitácora."""
    movimientos = RegistroAuditoria.objects.select_related('usuario', 'content_type')

    desde = _fecha_desde_query(request, 'desde')
    hasta = _fecha_desde_query(request, 'hasta')
    tipo = request.GET.get('tipo') or ''
    if desde and hasta and desde > hasta:
        messages.error(request, 'El rango de fechas no es válido: "Desde" es posterior a "Hasta".')
        desde = hasta = None
    if desde:
        movimientos = movimientos.filter(fecha__date__gte=desde)
    if hasta:
        movimientos = movimientos.filter(fecha__date__lte=hasta)
    if tipo:
        movimientos = movimientos.filter(content_type_id=tipo)

    # Solo se ofrecen como filtro los tipos que de verdad aparecen en la
    # bitácora; un selector con los 30 modelos del proyecto no ayudaría.
    tipos = ContentType.objects.filter(
        id__in=RegistroAuditoria.objects.values('content_type_id').distinct()
    ).order_by('model')

    contexto = {
        'vista_actual': 'bitacora',
        'movimientos': movimientos[:200],
        'total': movimientos.count(),
        'tipos': tipos,
        'tipo_elegido': tipo,
        'desde': request.GET.get('desde', ''),
        'hasta': request.GET.get('hasta', ''),
    }
    return render(request, 'finanzas/bitacora.html', contexto)


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
                _guardar_con_bitacora(request, form_categoria, 'Categoría de Egreso agregada correctamente.')
                return redirect('finanzas:configuracion')
        else:
            form_concepto = ConceptoIngresoForm(request.POST)
            if form_concepto.is_valid():
                _guardar_con_bitacora(request, form_concepto, 'Concepto de Ingreso agregado correctamente.')
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
    # La pantalla siempre muestra el ejercicio en curso; los documentos que se
    # descargan sí piden rango. El cálculo es el mismo (reportes.py) para que
    # el PDF de este año no pueda diferir de lo que se ve aquí.
    hoy = timezone.now().date()
    datos = estado_de_resultados(date(hoy.year, 1, 1), date(hoy.year, 12, 31))

    contexto = {
        'vista_actual': 'reportes',
        'anio': hoy.year,
        'total_ingresos_servicios': _dinero(datos['ingresos_servicios']),
        'total_donativos': _dinero(datos['donativos']),
        'total_ingresos': _dinero(datos['total_ingresos']),
        'total_nomina': _dinero(-datos['nomina_admin']),
        'total_nomina_terapeutas': _dinero(-datos['nomina_terapeutas']),
        'total_nomina_academia': _dinero(-datos['nomina_academia']),
        'total_renta': _dinero(-datos['renta']),
        'total_insumos': _dinero(-datos['insumos']),
        'total_otros': _dinero(-datos['otros']),
        'total_egresos': _dinero(-datos['total_egresos']),
        'resultado_ejercicio': _dinero(datos['resultado']),
        'resultado_negativo': datos['resultado'] < 0,
    }
    return render(request, 'finanzas/reportes.html', contexto)


# ===== Los tres documentos de "Generar reportes" =====
# Los tres reciben el rango del mismo modal (`?periodo=todo` o
# `?periodo=rango&desde=…&hasta=…`) y devuelven un archivo para descargar, no
# una pantalla. La lógica está en reportes.py; aquí solo se resuelve el rango.
# No se escriben en la bitácora: descargar es una consulta, no un cambio
# (mismo criterio que `exportar_view`).

@acceso_finanzas_requerido
def reporte_estado_resultados_view(request):
    desde, hasta = rango_pedido(request)
    contexto = {
        'datos': estado_de_resultados(desde, hasta),
        'periodo_etiqueta': etiqueta_periodo(desde, hasta),
        'usuario_genera': request.user,
        'generado_en': timezone.now(),
    }
    return render_pdf(
        'finanzas/estado_resultados_pdf.html', contexto,
        f'estado_resultados_{sufijo_archivo(desde, hasta)}.pdf',
    )


@acceso_finanzas_requerido
def reporte_flujo_efectivo_view(request):
    desde, hasta = rango_pedido(request)
    return flujo_efectivo_xlsx(
        desde, hasta,
        generado_por=request.user.get_full_name() or request.user.username,
    )


@acceso_finanzas_requerido
def reporte_donativos_view(request):
    desde, hasta = rango_pedido(request)
    contexto = {
        'datos': concentrado_donativos(desde, hasta),
        'periodo_etiqueta': etiqueta_periodo(desde, hasta),
        'usuario_genera': request.user,
        'generado_en': timezone.now(),
    }
    return render_pdf(
        'finanzas/donativos_pdf.html', contexto,
        f'concentrado_donativos_{sufijo_archivo(desde, hasta)}.pdf',
    )


def _fecha_desde_query(request, nombre):
    return _fecha(request.GET.get(nombre))


def _fecha_desde_post(request, nombre):
    return _fecha(request.POST.get(nombre))


def _fecha(valor):
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

    if desde:
        ingresos = ingresos.filter(fecha__gte=desde)
        egresos = egresos.filter(fecha__gte=desde)
        donativos = donativos.filter(fecha__gte=desde)
    if hasta:
        ingresos = ingresos.filter(fecha__lte=hasta)
        egresos = egresos.filter(fecha__lte=hasta)
        donativos = donativos.filter(fecha__lte=hasta)

    filas = []
    for i in ingresos:
        filas.append(('Ingreso', i.get_unidad_display(), i.get_concepto_display(), i.persona or (str(i.terapeuta) if i.terapeuta else ''), i.monto, i.get_estatus_display(), i.fecha))
    for e in egresos:
        filas.append(('Egreso', e.get_unidad_display(), e.concepto, e.persona, e.monto, e.get_estatus_display(), e.fecha))
    # Los donativos son de la institución, no de una unidad (ver tablero_view).
    for d in donativos:
        filas.append(('Donativo', '', f'Donativo {d.get_tipo_display().lower()}', d.donante_nombre, d.monto, d.get_estatus_cfdi_display(), d.fecha))
    filas.sort(key=lambda f: f[6])

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="finanzas_movimientos.csv"'
    writer = csv.writer(response)
    writer.writerow(['Tipo', 'Unidad', 'Concepto', 'Persona', 'Monto', 'Estatus', 'Fecha'])
    for tipo, unidad, concepto, persona, monto, estatus, fecha in filas:
        writer.writerow([tipo, unidad, concepto, persona, monto, estatus, fecha.isoformat()])
    return response
