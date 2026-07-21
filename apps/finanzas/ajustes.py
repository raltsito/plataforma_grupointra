from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .models import Ajuste, Egreso, Honorario, NominaAcademia


class AjusteError(Exception):
    """No se pudo registrar el ajuste."""


def _datos_egreso(registro):
    """Persona, categoría, fecha y método de pago a usar en el Egreso que
    genera el ajuste, según de qué tipo de registro se trate."""
    if isinstance(registro, Honorario):
        fecha = date(registro.periodo_anio, registro.periodo_mes, 1)
        return str(registro.terapeuta), Egreso.Categoria.NOMINA_ADMIN, fecha, ''
    if isinstance(registro, NominaAcademia):
        fecha = date(registro.periodo_anio, registro.periodo_mes, 1)
        return registro.maestro.nombre, Egreso.Categoria.NOMINA_ACADEMIA, fecha, registro.metodo_pago
    if isinstance(registro, Egreso):
        return registro.persona, registro.categoria, timezone.now().date(), registro.metodo_pago
    raise AjusteError('Tipo de registro no soportado para ajustes.')


@transaction.atomic
def registrar_ajuste(modelo, objeto_id, motivo, diferencia):
    """Registra un ajuste sobre un Honorario, NominaAcademia o Egreso ya
    existente, SIN modificar ese registro (queda congelado a propósito).
    Si la diferencia es un monto adicional a favor (> 0), genera un Egreso
    nuevo por ese monto. Una diferencia negativa (a favor de la institución)
    solo queda registrada para trazabilidad — este sistema no modela notas
    de crédito/reembolsos todavía, así que no genera un Egreso en ese caso."""
    try:
        registro = modelo.objects.get(pk=objeto_id)
    except modelo.DoesNotExist:
        raise AjusteError(f'No se encontró el registro #{objeto_id} de {modelo._meta.verbose_name}.')

    ajuste = Ajuste.objects.create(
        content_type=ContentType.objects.get_for_model(modelo),
        object_id=registro.pk, motivo=motivo, diferencia=diferencia,
    )

    if diferencia > 0:
        persona, categoria, fecha, metodo_pago = _datos_egreso(registro)
        egreso = Egreso.objects.create(
            concepto=f'Ajuste: {motivo} (ref. {registro})',
            categoria=categoria,
            persona=persona,
            monto=diferencia,
            metodo_pago=metodo_pago,
            estatus=Egreso.Estatus.PENDIENTE,
            fecha=fecha,
        )
        ajuste.egreso_generado = egreso
        ajuste.save(update_fields=['egreso_generado'])

    return ajuste
