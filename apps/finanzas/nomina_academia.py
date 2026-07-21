from datetime import date
from decimal import Decimal

from django.db import transaction

from .duplicados import DuplicadoError, existe_duplicado
from .models import ConceptoNominaAcademia, Egreso, NominaAcademia


@transaction.atomic
def capturar_nomina_academia(
    maestro, periodo_mes, periodo_anio, metodo_pago, cantidades,
    concepto_manual_descripcion='', concepto_manual_monto=None,
):
    """Crea la Nómina Academia de un maestro/periodo con sus conceptos
    (horas clase, supervisión, mesa de trabajo — calculados por tabulador —
    más un concepto manual autorizado opcional), y genera un Egreso separado
    por cada concepto con monto > 0 (mismo patrón que la nómina semanal de
    terapeutas, ver integraciones/importador_nomina.py). `cantidades` es un
    dict {concepto: Decimal}. Bloquea duplicar nómina para el mismo
    maestro/periodo (sección 6.1 del documento); una corrección posterior se
    registra como Ajuste (ver ajustes.py), sin reescribir esta nómina."""
    if existe_duplicado(NominaAcademia, maestro=maestro, periodo_mes=periodo_mes, periodo_anio=periodo_anio):
        raise DuplicadoError(
            f'Ya existe una nómina de Academia para {maestro} en {periodo_mes}/{periodo_anio}.'
        )

    nomina = NominaAcademia.objects.create(
        maestro=maestro, periodo_mes=periodo_mes, periodo_anio=periodo_anio,
        metodo_pago=metodo_pago,
    )

    for concepto, cantidad in cantidades.items():
        if cantidad:
            ConceptoNominaAcademia(nomina=nomina, concepto=concepto, cantidad=cantidad).save()

    if concepto_manual_descripcion and concepto_manual_monto:
        ConceptoNominaAcademia(
            nomina=nomina, concepto=ConceptoNominaAcademia.Concepto.MANUAL,
            descripcion=concepto_manual_descripcion,
            cantidad=Decimal('1'), tarifa=concepto_manual_monto,
        ).save()

    nomina.total = sum((linea.subtotal for linea in nomina.conceptos.all()), Decimal('0'))
    nomina.save(update_fields=['total'])

    periodo_fecha = date(periodo_anio, periodo_mes, 1)
    for linea in nomina.conceptos.all():
        if linea.subtotal <= 0:
            continue
        etiqueta = linea.get_concepto_display()
        if linea.descripcion:
            etiqueta = f'{etiqueta} · {linea.descripcion}'
        Egreso.objects.create(
            concepto=f'{etiqueta} · {maestro} · {periodo_mes}/{periodo_anio}',
            categoria=Egreso.Categoria.NOMINA_ACADEMIA,
            persona=maestro.nombre,
            monto=linea.subtotal,
            metodo_pago=metodo_pago,
            estatus=Egreso.Estatus.PENDIENTE,
            fecha=periodo_fecha,
            referencia_externa=f'academia:nomina:{nomina.id}:linea:{linea.id}',
        )

    return nomina
