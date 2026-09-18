"""Nómina semanal: sincronización, sellado y generación de egresos.

Reemplaza a `integraciones/importador_nomina.py`, que creaba Egresos
directamente al importar. Ahora la sincronización llena una `NominaSemanal`
en Borrador y los Egresos nacen al **sellar**, que es lo que pide la sección
3 del documento de requerimientos ("Al presionar Sellar / Aprobar, guardar
automáticamente el egreso en Finanzas"). De paso, eso da el momento en el
que el usuario puede revisar y corregir montos, elegir método de pago y
escribir observaciones antes de que el movimiento sea definitivo.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.core.auditoria.models import RegistroAuditoria
from apps.core.auditoria.registro import registrar

from .integraciones.consultorioweb import obtener_cortes_semanales
from .models import CitaRecepcion, Egreso, LineaNominaSemanal, NominaSemanal, Unidad
from .textos import concepto_egreso

logger = logging.getLogger(__name__)

# Un corte solo se sincroniza una vez sellado del lado de ConsultorioWeb. La
# API de origen no filtra por estatus, así que ese filtro vive aquí: nunca se
# trae un corte en 'borrador', porque todavía puede recalcularse allá.
ESTATUS_IMPORTABLES = {'aprobado', 'pagado'}

# Cada concepto de la línea se convierte en un Egreso separado, para que
# nunca se mezclen pago por servicio, vale de gasolina y bonos autorizados
# (problema "Errores de clasificacion" de la sección 2 del documento).
CONCEPTOS_EGRESO = (
    ('base', 'pago_base', 'Pago a terapeuta'),
    ('vale', 'vale_gasolina', 'Vale de gasolina / bono'),
    ('extra', 'extras', 'Bono extra / otros autorizados'),
)


class NominaError(Exception):
    """Validación de negocio de nómina (no es un error técnico)."""


# La semana de nómina de INTRA corre de VIERNES a JUEVES, no de lunes a
# domingo (confirmado por Administración el 2026-07-28: "a partir del viernes
# 31 se contabilizan las citas y se da el pago acumulado el jueves 6"). El
# pago se entrega el jueves que cierra el periodo.
#
# Los TRES tipos de nómina —semanal, quincenal y administrativa— usan este
# mismo corte de 7 días (confirmado el 2026-07-28: "todas siguen el mismo
# calendario"). Lo que distingue a una quincenal de una semanal es el
# concepto de pago de cada persona, no las fechas del documento; así aparece
# también en el formato de referencia de la sección 4 del documento, donde
# "Prenómina quincenal" es un concepto dentro de la nómina y no un periodo
# aparte. Por eso `periodo_por_defecto` no recibe el tipo: no varía.
DIA_INICIO_SEMANA = 4  # viernes, en la numeración de date.weekday() (lunes=0)


def periodo_por_defecto(hoy):
    """Semana de nómina (viernes→jueves) que contiene a `hoy`. Es solo el
    valor inicial de la pantalla; el usuario puede mover las fechas."""
    inicio = hoy - timedelta(days=(hoy.weekday() - DIA_INICIO_SEMANA) % 7)
    return inicio, inicio + timedelta(days=6)


def periodo_anterior(inicio):
    """El periodo que cierra justo antes del que se está viendo."""
    return periodo_por_defecto(inicio - timedelta(days=1))


def periodo_siguiente(fin):
    return periodo_por_defecto(fin + timedelta(days=1))


def _decimal(valor):
    try:
        return Decimal(str(valor or 0))
    except (InvalidOperation, TypeError):
        return Decimal('0')


def _iniciales(persona):
    partes = [p for p in str(persona).split() if p]
    return ''.join(p[0] for p in partes[:2]).upper() or 'XX'


def referencia_egreso(linea, parte):
    """Referencia legible del movimiento, al estilo del ejemplo de la
    sección 3.1 del documento (NOM-2026-07-03-JA). Se le agrega el id de la
    línea porque dos personas pueden compartir iniciales."""
    return f'NOM-{linea.nomina.fecha_fin:%Y-%m-%d}-{_iniciales(linea.persona)}{linea.pk}-{parte}'


def calcular_ingreso_generado(persona, fecha_inicio, fecha_fin):
    """Ingreso de clínica que generó esa persona en el periodo, según las
    citas ya sincronizadas de Recepción. Regresa None (no 0) si no hay
    ninguna cita de esa persona en el rango: significa "todavía no lo
    sabemos", no "no generó nada".

    Para pintar la tabla completa usa `ingresos_generados_por_persona`, que
    hace lo mismo en una sola consulta."""
    datos = CitaRecepcion.objects.filter(
        terapeuta=persona,
        estatus=CitaRecepcion.Estatus.SI_ASISTIO,
        fecha__gte=fecha_inicio,
        fecha__lte=fecha_fin,
    ).aggregate(total=Sum('costo'), citas=Count('id'))
    if not datos['citas']:
        return None
    return datos['total'] or Decimal('0')


def ingresos_generados_por_persona(fecha_inicio, fecha_fin):
    """Lo mismo que `calcular_ingreso_generado` pero para todas las personas
    de un periodo en una sola consulta, para pintarlo al vuelo en la tabla.

    Se calcula al mostrar y no solo al sincronizar a propósito: el orden
    natural de trabajo es abrir la nómina primero y sincronizar Recepción
    después, y con un valor congelado en el momento de la sincronización la
    columna se quedaba en "—" para siempre aunque Recepción ya tuviera los
    datos.
    """
    filas = (
        CitaRecepcion.objects.filter(
            estatus=CitaRecepcion.Estatus.SI_ASISTIO,
            fecha__gte=fecha_inicio,
            fecha__lte=fecha_fin,
        )
        .values('terapeuta')
        .annotate(total=Sum('costo'))
    )
    return {f['terapeuta']: (f['total'] or Decimal('0')) for f in filas}


def obtener_nomina(tipo, fecha_inicio, fecha_fin):
    return NominaSemanal.objects.filter(
        tipo=tipo, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
    ).first()


@transaction.atomic
def sincronizar_nomina(fecha_inicio, fecha_fin, usuario=None):
    """Trae los cortes sellados de ConsultorioWeb y los deja como líneas de
    la nómina semanal del periodo, en Borrador.

    Reglas: nunca toca una línea ya sellada (esa ya generó egresos), y al
    actualizar una línea en borrador respeta lo que el usuario haya editado
    a mano — método de pago, observaciones y, si los corrigió, los montos —
    porque son decisiones suyas, no datos de ConsultorioWeb.
    """
    cortes = [c for c in obtener_cortes_semanales(fecha_inicio, fecha_fin)
              if c.get('estatus') in ESTATUS_IMPORTABLES]

    nomina, _ = NominaSemanal.objects.get_or_create(
        tipo=NominaSemanal.Tipo.SEMANAL, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        defaults={'usuario_genera': usuario if getattr(usuario, 'is_authenticated', False) else None},
    )

    resumen = {'nuevas': 0, 'actualizadas': 0, 'selladas': 0, 'con_error': 0}
    if nomina.esta_sellada:
        resumen['selladas'] = len(cortes)
        return nomina, resumen

    for corte in cortes:
        try:
            persona = corte['terapeuta']
            subtotal = _decimal(corte['subtotal_sesiones'])
            vale = _decimal(corte['total_bonos'])
            extras = _decimal(corte['total_pago']) - subtotal - vale
        except (KeyError, TypeError):
            # Un corte con un campo faltante no debe tumbar la corrida
            # completa: se omite y se reporta, y queda disponible para
            # reintentar después de corregirlo en ConsultorioWeb.
            logger.warning('Corte %s omitido por datos inesperados.', corte.get('id', '?'))
            resumen['con_error'] += 1
            continue

        linea = LineaNominaSemanal.objects.filter(nomina=nomina, persona=persona).first()
        if linea and linea.sellada:
            resumen['selladas'] += 1
            continue

        es_nueva = linea is None
        if es_nueva:
            linea = LineaNominaSemanal(nomina=nomina, persona=persona)

        linea.tipo_persona = LineaNominaSemanal.TipoPersona.TERAPEUTA
        linea.concepto = 'Pago a terapeuta'
        if not linea.montos_editados:
            linea.pago_base = subtotal
            linea.vale_gasolina = vale
            linea.extras = extras if extras > 0 else Decimal('0')
        linea.citas_atendidas = corte.get('total_sesiones') or 0
        linea.detalle_json = corte.get('detalles') or []
        linea.referencia_corte = f"consultorioweb:corte:{corte.get('id', '')}"
        linea.ingreso_generado = calcular_ingreso_generado(persona, fecha_inicio, fecha_fin)
        linea.save()
        resumen['nuevas' if es_nueva else 'actualizadas'] += 1

    registrar(
        usuario, nomina, RegistroAuditoria.Accion.IMPORTO,
        detalle=f"Sincronización de nómina semanal: {resumen['nuevas']} nuevas, "
                f"{resumen['actualizadas']} actualizadas, {resumen['selladas']} ya selladas.",
    )
    return nomina, resumen


@transaction.atomic
def sellar_linea(linea, usuario=None):
    """Cierra el pago de una persona y genera sus Egresos, uno por concepto
    con monto mayor a cero. Bloquea sellar dos veces (regla de duplicidad de
    la sección 3.1: "Si el terapeuta ya fue sellado en ese periodo, el
    sistema debe bloquear una segunda generacion de egreso")."""
    if linea.sellada:
        raise NominaError(f'{linea.persona} ya fue sellado en este periodo; corrígelo con un Ajuste.')
    if linea.total <= 0:
        raise NominaError(f'{linea.persona} no tiene montos que sellar.')

    categoria = (
        Egreso.Categoria.NOMINA_TERAPEUTAS
        if linea.tipo_persona == LineaNominaSemanal.TipoPersona.TERAPEUTA
        else Egreso.Categoria.NOMINA_ADMIN
    )
    # "Pendiente" es un método de pago válido al sellar (así se ve en el
    # formato de referencia de la sección 4): significa que el monto ya está
    # autorizado pero todavía no se decide cómo se dispersa. En el Egreso eso
    # se guarda como método vacío.
    metodo = '' if linea.metodo_pago == LineaNominaSemanal.MetodoPago.PENDIENTE else linea.metodo_pago
    estatus = (
        Egreso.Estatus.PAGADO
        if linea.estatus_pago == LineaNominaSemanal.EstatusPago.PAGADO
        else Egreso.Estatus.PENDIENTE
    )
    periodo = f'{linea.nomina.fecha_inicio:%d/%m/%Y} al {linea.nomina.fecha_fin:%d/%m/%Y}'

    creados = []
    for parte, campo, etiqueta in CONCEPTOS_EGRESO:
        monto = getattr(linea, campo)
        if monto <= 0:
            continue
        creados.append(Egreso.objects.create(
            concepto=concepto_egreso(f'{etiqueta} · {linea.persona} · {periodo}'),
            categoria=categoria,
            # La nómina semanal, la quincenal y la administrativa son de la
            # operación clínica; la de la escuela es NominaAcademia.
            unidad=Unidad.INTRA,
            persona=linea.persona,
            monto=monto,
            metodo_pago=metodo,
            estatus=estatus,
            fecha=linea.nomina.fecha_fin,
            referencia_externa=referencia_egreso(linea, parte),
            linea_nomina=linea,
        ))

    linea.sellada = True
    linea.sellada_en = timezone.now()
    linea.save(update_fields=['sellada', 'sellada_en'])

    registrar(
        usuario, linea, RegistroAuditoria.Accion.SELLO,
        campo='total', nuevo=linea.total,
        detalle=f'Sellado de {linea.persona}: {len(creados)} egreso(s) generado(s).',
    )
    return creados


@transaction.atomic
def sellar_periodo(nomina, usuario=None, fecha_pago=None):
    """Sella todas las líneas pendientes de la nómina y cierra el documento.
    Las líneas en cero se omiten (no hay nada que pagar), no se consideran
    error."""
    if nomina.esta_sellada:
        raise NominaError('Esta nómina ya está sellada.')

    lineas = list(nomina.lineas.filter(sellada=False))
    if not lineas:
        raise NominaError('Esta nómina no tiene líneas por sellar.')

    selladas, omitidas = 0, 0
    for linea in lineas:
        if linea.total <= 0:
            omitidas += 1
            continue
        sellar_linea(linea, usuario)
        selladas += 1

    if not selladas:
        raise NominaError('Ninguna línea tiene montos que sellar.')

    nomina.estado = NominaSemanal.Estado.SELLADA
    nomina.sellada_en = timezone.now()
    # El pago se entrega el día que cierra el periodo (el jueves, en la
    # semanal), no el día en que se alcanzó a sellar en el sistema.
    nomina.fecha_pago = fecha_pago or nomina.fecha_pago or nomina.fecha_fin
    if not nomina.usuario_genera_id and getattr(usuario, 'is_authenticated', False):
        nomina.usuario_genera = usuario
    nomina.save(update_fields=['estado', 'sellada_en', 'fecha_pago', 'usuario_genera'])

    registrar(
        usuario, nomina, RegistroAuditoria.Accion.SELLO,
        campo='estado', anterior='borrador', nuevo='sellada',
        detalle=f'Sellado de periodo: {selladas} persona(s) sellada(s), {omitidas} omitida(s) por estar en cero.',
    )
    return {'selladas': selladas, 'omitidas': omitidas}


@transaction.atomic
def reabrir_linea(linea, usuario=None):
    """Deshace el sellado de una sola persona y la regresa a edición, sin
    tocar al resto de la nómina. Borra los Egresos que generó ese sellado —
    se vuelven a crear al volver a sellar; si alguno ya se reconcilió a mano
    fuera del sistema, revisar antes de reabrir.

    Si la nómina estaba sellada por completo, regresa el documento a Borrador:
    ya no todas las personas están selladas, y de otro modo la edición de esta
    persona quedaría bloqueada por el estado del documento."""
    if not linea.sellada:
        raise NominaError(f'{linea.persona} no está sellada; no hay nada que reabrir.')

    egresos_eliminados = linea.egresos.all().delete()[0]
    linea.sellada = False
    linea.sellada_en = None
    linea.save(update_fields=['sellada', 'sellada_en'])

    registrar(
        usuario, linea, RegistroAuditoria.Accion.MODIFICO,
        campo='sellada', anterior=True, nuevo=False,
        detalle=f'Reapertura de {linea.persona}: {egresos_eliminados} egreso(s) eliminado(s).',
    )

    nomina = linea.nomina
    periodo_reabierto = False
    if nomina.esta_sellada:
        nomina.estado = NominaSemanal.Estado.BORRADOR
        nomina.sellada_en = None
        nomina.save(update_fields=['estado', 'sellada_en'])
        periodo_reabierto = True
        registrar(
            usuario, nomina, RegistroAuditoria.Accion.MODIFICO,
            campo='estado', anterior='sellada', nuevo='borrador',
            detalle=f'Reapertura de {linea.persona}: el periodo volvió a Borrador.',
        )

    return {
        'persona': linea.persona,
        'egresos_eliminados': egresos_eliminados,
        'periodo_reabierto': periodo_reabierto,
    }


@transaction.atomic
def reabrir_periodo(nomina, usuario=None):
    """Deshace el sellado de una nómina y la regresa a Borrador para poder
    corregirla con el formulario normal (decisión del usuario 2026-08-28:
    cualquier nómina debe poder modificarse aunque ya esté sellada, en vez de
    pasar siempre por un Ajuste). Borra los Egresos que generó el sellado —
    se vuelven a crear al volver a sellar—; si alguno ya se reconcilió a mano
    fuera del sistema, revisar antes de reabrir."""
    if not nomina.esta_sellada:
        raise NominaError('Esta nómina no está sellada.')

    lineas = list(nomina.lineas.filter(sellada=True))
    egresos_eliminados = 0
    for linea in lineas:
        egresos_eliminados += linea.egresos.all().delete()[0]
        linea.sellada = False
        linea.sellada_en = None
        linea.save(update_fields=['sellada', 'sellada_en'])

    nomina.estado = NominaSemanal.Estado.BORRADOR
    nomina.sellada_en = None
    nomina.save(update_fields=['estado', 'sellada_en'])

    registrar(
        usuario, nomina, RegistroAuditoria.Accion.MODIFICO,
        campo='estado', anterior='sellada', nuevo='borrador',
        detalle=f'Reapertura de periodo: {len(lineas)} línea(s) reabierta(s), '
                f'{egresos_eliminados} egreso(s) eliminado(s).',
    )
    return {'lineas': len(lineas), 'egresos_eliminados': egresos_eliminados}


def marcar_pago(linea, estatus, usuario=None):
    """Marca una línea ya sellada como pagada (o de vuelta a pendiente) y
    arrastra ese cambio a los Egresos que generó, para que el tablero y los
    reportes no queden contando dinero que ya salió — o al revés."""
    if estatus not in LineaNominaSemanal.EstatusPago.values:
        raise NominaError('Estatus de pago inválido.')
    anterior = linea.estatus_pago
    if anterior == estatus:
        return

    linea.estatus_pago = estatus
    linea.save(update_fields=['estatus_pago'])
    linea.egresos.update(
        estatus=Egreso.Estatus.PAGADO if estatus == LineaNominaSemanal.EstatusPago.PAGADO
        else Egreso.Estatus.PENDIENTE
    )
    registrar(
        usuario, linea, RegistroAuditoria.Accion.MODIFICO,
        campo='estatus de pago', anterior=anterior, nuevo=estatus,
    )


def totales_nomina(nomina):
    """Los totales que pide la sección 4 del documento para poder solicitar
    la dispersión del dinero. Lo pendiente por dispersar (total, transferencia
    y efectivo) NO incluye los vales de gasolina: esos se suman aparte en
    `total_vales`. `total_general` sí trae todo (es el costo de la nómina)."""
    lineas = list(nomina.lineas.all())
    pendientes = [l for l in lineas if l.estatus_pago == LineaNominaSemanal.EstatusPago.PENDIENTE]
    return {
        'total_general': sum((l.total for l in lineas), Decimal('0')),
        'pendiente_dispersar': sum((l.a_dispersar for l in pendientes), Decimal('0')),
        'pendiente_transferencia': sum(
            (l.a_dispersar for l in pendientes if l.metodo_pago == LineaNominaSemanal.MetodoPago.TRANSFERENCIA),
            Decimal('0'),
        ),
        'pendiente_efectivo': sum(
            (l.a_dispersar for l in pendientes if l.metodo_pago == LineaNominaSemanal.MetodoPago.EFECTIVO),
            Decimal('0'),
        ),
        'total_vales': sum((l.vale_gasolina for l in lineas), Decimal('0')),
    }
