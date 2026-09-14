from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.core.auditoria.models import RegistroAuditoria
from apps.core.auditoria.registro import registrar

from .models import Ajuste, Egreso, NominaAcademia, Unidad
from .textos import concepto_egreso


class AjusteError(Exception):
    """No se pudo registrar el ajuste."""


def _datos_egreso(registro):
    """Datos del Egreso que genera el ajuste, según de qué tipo de registro
    se trate. La unidad (Intra / Academia) se hereda del registro corregido:
    un ajuste nunca cambia de unidad respecto a lo que está corrigiendo, o
    el tablero filtrado dejaría de cuadrar."""
    if isinstance(registro, NominaAcademia):
        return {
            'persona': registro.maestro.nombre,
            'categoria': Egreso.Categoria.NOMINA_ACADEMIA,
            'unidad': Unidad.ACADEMIA,
            'fecha': registro.fecha_fin,
            'metodo_pago': registro.metodo_pago,
        }
    if isinstance(registro, Egreso):
        return {
            'persona': registro.persona,
            'categoria': registro.categoria,
            'unidad': registro.unidad,
            'fecha': timezone.now().date(),
            'metodo_pago': registro.metodo_pago,
        }
    raise AjusteError('Tipo de registro no soportado para ajustes.')


def _monto_original(registro):
    """Monto contra el que se compara el ajuste. NominaAcademia lo llama
    `total`; Egreso, `monto`."""
    if isinstance(registro, NominaAcademia):
        return registro.total
    if isinstance(registro, Egreso):
        return registro.monto
    raise AjusteError('Tipo de registro no soportado para ajustes.')


@transaction.atomic
def registrar_ajuste(modelo, objeto_id, motivo, diferencia, usuario=None):
    """Registra un ajuste sobre una NominaAcademia o un Egreso ya
    existente, SIN modificar ese registro (queda congelado a propósito).
    Si la diferencia es un monto adicional a favor (> 0), genera un Egreso
    nuevo por ese monto. Una diferencia negativa (a favor de la institución)
    solo queda registrada para trazabilidad — este sistema no modela notas
    de crédito/reembolsos todavía, así que no genera un Egreso en ese caso.

    Guarda quién lo registró y los montos antes/después, y deja constancia
    en la bitácora (sección 9 del documento de requerimientos)."""
    try:
        registro = modelo.objects.get(pk=objeto_id)
    except modelo.DoesNotExist:
        raise AjusteError(f'No se encontró el registro #{objeto_id} de {modelo._meta.verbose_name}.')

    monto_anterior = _monto_original(registro)
    ajuste = Ajuste.objects.create(
        content_type=ContentType.objects.get_for_model(modelo),
        object_id=registro.pk, motivo=motivo, diferencia=diferencia,
        monto_anterior=monto_anterior, monto_nuevo=monto_anterior + diferencia,
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )

    if diferencia > 0:
        egreso = Egreso.objects.create(
            concepto=concepto_egreso(f'Ajuste: {motivo} (ref. {registro})'),
            monto=diferencia,
            estatus=Egreso.Estatus.PENDIENTE,
            **_datos_egreso(registro),
        )
        ajuste.egreso_generado = egreso
        ajuste.save(update_fields=['egreso_generado'])

    registrar(
        usuario, registro, RegistroAuditoria.Accion.AJUSTO,
        campo='monto', anterior=ajuste.monto_anterior, nuevo=ajuste.monto_nuevo,
        detalle=motivo,
    )
    return ajuste
