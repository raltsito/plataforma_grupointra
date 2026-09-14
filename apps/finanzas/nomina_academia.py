from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.auditoria.models import RegistroAuditoria
from apps.core.auditoria.registro import registrar, registrar_cambio_de_campo

from .duplicados import DuplicadoError, existe_duplicado
from .models import ConceptoNominaAcademia, Egreso, NominaAcademia, Unidad
from .textos import concepto_egreso


class NominaAcademiaError(Exception):
    """No se pudo capturar o sellar la nómina (validación de negocio, no un error técnico)."""


@transaction.atomic
def capturar_nomina_academia(
    maestro, tipo, fecha_inicio, fecha_fin, metodo_pago, cantidades,
    concepto_manual_descripcion='', concepto_manual_monto=None, usuario=None,
):
    """Crea la Nómina Academia de una persona en un periodo de nómina (el
    rango viernes→jueves, igual que la Nómina semanal) con sus conceptos
    (horas clase, supervisión, mesa de trabajo — calculados por tabulador —
    más un concepto manual autorizado opcional) y la deja en **Borrador**.

    `tipo` distingue el ciclo de pago (Mensual / Quincenal). Las fechas del
    periodo SON las mismas para ambos tipos; una persona aparece únicamente
    bajo el tipo con el que se capturó. Si estás viendo "Quincenal" y agregas
    una persona, queda como quincenal; si cambias a "Mensual" y agregas otra,
    queda como mensual — exactamente como en la Nómina semanal.

    Los Egresos no se generan aquí: nacen al sellar (ver
    `sellar_nomina_academia`), igual que en la nómina semanal. Así se puede
    revisar y corregir antes de que el movimiento sea definitivo, que es lo
    que pide la sección 7 del documento.

    `cantidades` es un dict {concepto: Decimal}. Bloquea duplicar nómina para
    el mismo maestro/tipo/periodo (sección 6.1 del documento); una corrección
    posterior al sellado se registra como Ajuste (ver ajustes.py)."""
    if existe_duplicado(
        NominaAcademia, maestro=maestro, tipo=tipo,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
    ):
        raise DuplicadoError(
            f'Ya existe una nómina de Academia para {maestro} ({tipo}) '
            f'de {fecha_inicio:%d/%m/%Y} al {fecha_fin:%d/%m/%Y}.'
        )

    nomina = NominaAcademia.objects.create(
        maestro=maestro, tipo=tipo,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        metodo_pago=metodo_pago,
        usuario_genera=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )

    for concepto, cantidad in cantidades.items():
        if cantidad:
            linea = ConceptoNominaAcademia(nomina=nomina, concepto=concepto, cantidad=cantidad)
            linea.save()
            if linea.tabulador is None:
                # Sin esto, la línea se guardaba con tarifa/subtotal $0 sin
                # ningún aviso, y como el sellado solo genera Egreso para
                # subtotal > 0, ese concepto simplemente desaparecía del pago
                # sin que nadie se enterara.
                raise NominaAcademiaError(
                    f'No hay un tabulador vigente para "{linea.get_concepto_display()}" en '
                    f'el periodo del {fecha_inicio:%d/%m/%Y}. Registra un tabulador de Academia '
                    'con "Vigente desde" en o antes de esa fecha antes de capturar esta nómina.'
                )

    if concepto_manual_descripcion and concepto_manual_monto:
        ConceptoNominaAcademia(
            nomina=nomina, concepto=ConceptoNominaAcademia.Concepto.MANUAL,
            descripcion=concepto_manual_descripcion,
            cantidad=Decimal('1'), tarifa=concepto_manual_monto,
        ).save()

    nomina.total = sum((linea.subtotal for linea in nomina.conceptos.all()), Decimal('0'))
    nomina.save(update_fields=['total'])

    registrar(usuario, nomina, RegistroAuditoria.Accion.CREO, campo='total', nuevo=nomina.total)
    return nomina


@transaction.atomic
def sellar_nomina_academia(nomina, usuario=None, fecha_pago=None):
    """Cierra la nómina de un docente y genera **un Egreso por concepto**,
    con el desglose que pide la sección 6.1 del documento. Bloquea sellar dos
    veces: eso evita generar el pago por duplicado."""
    if nomina.esta_sellada:
        raise NominaAcademiaError(
            f'La nómina de {nomina.maestro} de {nomina.fecha_inicio:%d/%m/%Y} al '
            f'{nomina.fecha_fin:%d/%m/%Y} ya está sellada; corrígela con un Ajuste.'
        )

    conceptos = [c for c in nomina.conceptos.all() if c.subtotal > 0]
    if not conceptos:
        raise NominaAcademiaError('Esta nómina no tiene conceptos con monto que sellar.')

    # Seguridad: si quedaron egresos huérfanos de un sellado anterior que no
    # se borró correctamente (por ejemplo, edits manuales en admin), se
    # eliminan aquí para evitar un IntegrityError por la|unique de
    # referencia_externa.
    egresos_previos = Egreso.objects.filter(
        referencia_externa__startswith=f'academia:nomina:{nomina.id}:',
    )
    if egresos_previos.exists():
        egresos_previos.delete()

    for linea in conceptos:
        etiqueta = linea.get_concepto_display()
        if linea.descripcion:
            etiqueta = f'{etiqueta} · {linea.descripcion}'
        Egreso.objects.create(
            concepto=concepto_egreso(
                f'{etiqueta} · {nomina.maestro} · {nomina.fecha_inicio:%d/%m/%Y} al {nomina.fecha_fin:%d/%m/%Y}'
            ),
            categoria=Egreso.Categoria.NOMINA_ACADEMIA,
            unidad=Unidad.ACADEMIA,
            persona=nomina.maestro.nombre,
            monto=linea.subtotal,
            metodo_pago=nomina.metodo_pago,
            estatus=(
                Egreso.Estatus.PAGADO if nomina.estatus == NominaAcademia.Estatus.PAGADO
                else Egreso.Estatus.PENDIENTE
            ),
            fecha=nomina.fecha_fin,
            referencia_externa=f'academia:nomina:{nomina.id}:linea:{linea.id}',
        )

    nomina.estado = NominaAcademia.Estado.SELLADA
    nomina.sellada_en = timezone.now()
    nomina.fecha_pago = fecha_pago or nomina.fecha_pago or timezone.now().date()
    nomina.save(update_fields=['estado', 'sellada_en', 'fecha_pago'])

    registrar(
        usuario, nomina, RegistroAuditoria.Accion.SELLO,
        campo='estado', anterior='borrador', nuevo='sellada',
        detalle=f'{len(conceptos)} egreso(s) de Academia generado(s) por {nomina.total}.',
    )
    return nomina


@transaction.atomic
def reabrir_nomina_academia(nomina, usuario=None):
    """Deshace el sellado de la nómina de un docente y la regresa a Borrador
    (decisión del usuario 2026-08-28: cualquier nómina debe poder
    modificarse aunque ya esté sellada). Borra los Egresos que generó el
    sellado — se vuelven a crear al volver a sellar."""
    if not nomina.esta_sellada:
        raise NominaAcademiaError(
            f'La nómina de {nomina.maestro} de {nomina.fecha_inicio:%d/%m/%Y} al '
            f'{nomina.fecha_fin:%d/%m/%Y} no está sellada.'
        )

    borrados, _ = Egreso.objects.filter(
        referencia_externa__startswith=f'academia:nomina:{nomina.id}:',
    ).delete()

    nomina.estado = NominaAcademia.Estado.BORRADOR
    nomina.sellada_en = None
    nomina.save(update_fields=['estado', 'sellada_en'])

    registrar(
        usuario, nomina, RegistroAuditoria.Accion.MODIFICO,
        campo='estado', anterior='sellada', nuevo='borrador',
        detalle=f'Reapertura de nómina de Academia: {borrados} egreso(s) eliminado(s).',
    )
    return borrados


@transaction.atomic
def editar_montos_nomina_academia(nomina, montos, usuario=None):
    """Edita los montos (subtotal) de los conceptos de una nómina de Academia
    que está en Borrador (original o reabierta). `montos` es {id_concepto:
    Decimal}. Recorre los conceptos de la nómina y actualiza el subtotal de
    los indicados, recalculando el total de la cabecera. Los egresos no se
    tocan aquí: al volver a sellarla se regeneran con los montos nuevos."""
    if nomina.esta_sellada:
        raise NominaAcademiaError(
            f'La nómina de {nomina.maestro} de {nomina.fecha_inicio:%d/%m/%Y} al '
            f'{nomina.fecha_fin:%d/%m/%Y} está sellada; corrígela con un Ajuste.'
        )

    cambiado = False
    for concepto in nomina.conceptos.all():
        clave = str(concepto.id)
        if clave not in montos or montos[clave] is None:
            continue
        nuevo = Decimal(montos[clave])
        if nuevo < 0:
            nuevo = Decimal('0')
        anterior = concepto.subtotal
        if nuevo == anterior:
            continue
        concepto.subtotal = nuevo
        concepto.save(update_fields=['subtotal'])
        registrar_cambio_de_campo(
            usuario, concepto, 'subtotal', anterior, nuevo, etiqueta='subtotal',
        )
        cambiado = True

    if cambiado:
        _recalcular_total_academia(nomina)


def _recalcular_total_academia(nomina):
    nomina.total = sum(
        (c.subtotal or Decimal('0') for c in nomina.conceptos.all()),
        Decimal('0'),
    )
    nomina.save(update_fields=['total'])


@transaction.atomic
def reabrir_periodo_academia(fecha_inicio, fecha_fin, usuario=None):
    """Reabre a Borrador todas las nóminas de Academia selladas del periodo,
    de una sola vez (el botón "Reabrir periodo", reverso del sellado por
    periodo). Elimina los Egresos que generó el sellado de cada una — se
    vuelven a crear al volver a sellarla."""
    selladas = list(NominaAcademia.objects.filter(
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        estado=NominaAcademia.Estado.SELLADA,
    ))
    if not selladas:
        raise NominaAcademiaError('No hay nóminas de Academia selladas para ese periodo.')

    reabiertas, egresos_eliminados = 0, 0
    for nomina in selladas:
        egresos_eliminados += reabrir_nomina_academia(nomina, usuario)
        reabiertas += 1
    return {'reabiertas': reabiertas, 'egresos_eliminados': egresos_eliminados}


def sellar_periodo_academia(fecha_inicio, fecha_fin, usuario=None, fecha_pago=None):
    """Sella de un golpe todas las nóminas en borrador del periodo — el botón
    "Sellar periodo" de la sección 7."""
    pendientes = NominaAcademia.objects.filter(
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, estado=NominaAcademia.Estado.BORRADOR,
    )
    if not pendientes.exists():
        raise NominaAcademiaError('No hay nóminas de Academia en borrador para ese periodo.')

    selladas, omitidas = 0, 0
    for nomina in pendientes:
        try:
            sellar_nomina_academia(nomina, usuario, fecha_pago)
            selladas += 1
        except NominaAcademiaError:
            # Una nómina sin conceptos con monto no debe impedir sellar las
            # demás del periodo; se reporta al final.
            omitidas += 1
    return {'selladas': selladas, 'omitidas': omitidas}


def totales_periodo_academia(fecha_inicio, fecha_fin):
    """Totales del consolidado del periodo (sección 6.1, "Totales"): por
    docente, por método de pago, pendiente y total general."""
    nominas = list(
        NominaAcademia.objects.filter(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
        .select_related('maestro').prefetch_related('conceptos')
    )
    return nominas, {
        'total_general': sum((n.total for n in nominas), Decimal('0')),
        'total_transferencia': sum(
            (n.total for n in nominas if n.metodo_pago == NominaAcademia.MetodoPago.TRANSFERENCIA),
            Decimal('0'),
        ),
        'total_efectivo': sum(
            (n.total for n in nominas if n.metodo_pago == NominaAcademia.MetodoPago.EFECTIVO),
            Decimal('0'),
        ),
        'total_pendiente': sum(
            (n.total for n in nominas if n.estatus == NominaAcademia.Estatus.PENDIENTE),
            Decimal('0'),
        ),
        'docentes': len(nominas),
        'conceptos': ConceptoNominaAcademia.objects.filter(
            nomina__fecha_inicio=fecha_inicio, nomina__fecha_fin=fecha_fin,
        ).aggregate(total=Sum('subtotal'))['total'] or Decimal('0'),
    }


def totales_academia(nominas):
    """Los cinco totales que se muestran como KPIs en la pantalla de Nómina
    Academia, con la misma semántica que `totales_nomina` de la Nómina
    semanal. El equivalente de "vales/extras" en Academia es el concepto
    manual autorizado, así que se suma el importe pendiente de esos
    conceptos."""
    nominas = list(nominas)
    pendientes = [
        n for n in nominas if n.estatus == NominaAcademia.Estatus.PENDIENTE
    ]
    ids_pendientes = [n.id for n in pendientes]
    extras_pendientes = Decimal('0')
    if ids_pendientes:
        extras_pendientes = ConceptoNominaAcademia.objects.filter(
            nomina_id__in=ids_pendientes,
            concepto=ConceptoNominaAcademia.Concepto.MANUAL,
        ).aggregate(total=Sum('subtotal'))['total'] or Decimal('0')
    return {
        'total_general': sum((n.total for n in nominas), Decimal('0')),
        'pendiente_dispersar': sum((n.total for n in pendientes), Decimal('0')),
        'pendiente_transferencia': sum(
            (n.total for n in pendientes if n.metodo_pago == NominaAcademia.MetodoPago.TRANSFERENCIA),
            Decimal('0'),
        ),
        'pendiente_efectivo': sum(
            (n.total for n in pendientes if n.metodo_pago == NominaAcademia.MetodoPago.EFECTIVO),
            Decimal('0'),
        ),
        'vales_pendientes': extras_pendientes,
    }
