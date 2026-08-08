from django.utils import timezone

from .models import (
    AplicacionPublica,
    BitacoraProceso,
)


def proceso_es_editable(proceso):
    """Centraliza el modo consulta de los procesos cerrados."""

    return proceso.estado != proceso.Estado.CERRADO


def cerrar_proceso(proceso, usuario):
    """Finaliza el proceso sin eliminar ni invalidar su información histórica."""

    if not proceso_es_editable(proceso):
        return False
    proceso.estado = proceso.Estado.CERRADO
    proceso.fecha_cierre = timezone.localdate()
    proceso.full_clean()
    proceso.save(
        update_fields=['estado', 'fecha_cierre', 'actualizado_en'],
    )
    BitacoraProceso.objects.create(
        proceso=proceso,
        evento='Cierre de proceso',
        descripcion='El proceso dejó de recibir participantes y respuestas.',
        usuario=usuario,
    )
    return True


def obtener_aplicacion_publica(
    configuracion,
    usuario=None,
):
    """Obtiene el enlace publico unico de una configuracion y lo repara si falta."""

    aplicacion_publica, creada = (
        AplicacionPublica.objects.get_or_create(
            configuracion=configuracion
        )
    )

    if creada:
        BitacoraProceso.objects.create(
            proceso=configuracion.proceso,
            evento='Aplicacion publica generada',
            descripcion=configuracion.instrumento.nombre,
            usuario=(
                usuario
                if getattr(usuario, 'is_authenticated', False)
                else None
            ),
        )

    return aplicacion_publica, creada


def obtener_aplicacion_publica_proceso(
    proceso,
    usuario=None,
):
    """Obtiene el único enlace público general de la batería de un proceso."""

    aplicacion_publica, creada = (
        AplicacionPublica.objects.get_or_create(
            proceso=proceso
        )
    )

    if creada:
        BitacoraProceso.objects.create(
            proceso=proceso,
            evento='Aplicación pública general generada',
            descripcion='Enlace de batería pública creado.',
            usuario=(
                usuario
                if getattr(usuario, 'is_authenticated', False)
                else None
            ),
        )

    return aplicacion_publica, creada
