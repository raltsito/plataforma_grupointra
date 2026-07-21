from django.db import transaction

from apps.finanzas.models import CitaRecepcion, Ingreso

# Regla de negocio confirmada con Administración INTRA (2026-07-21): solo
# 'Sí asistió' cuenta como ingreso real. Confirmada/Sin confirmar/Reagendó/
# Canceló/No asistió/Incidencia no generan ingreso. Además, sin importar el
# estatus, un método de pago 'Pase' o un costo de $0 tampoco cuentan (sección
# 5.1 del documento), porque no representan una entrada de dinero real.


def cuenta_como_ingreso(fila_o_cita):
    return (
        fila_o_cita['estatus'] == CitaRecepcion.Estatus.SI_ASISTIO
        and fila_o_cita['metodo_pago'] != CitaRecepcion.MetodoPago.PASE
        and fila_o_cita['costo'] > 0
    )


@transaction.atomic
def importar_cita(fila):
    """Crea o actualiza la CitaRecepcion (dedupe por fecha/hora/paciente/
    terapeuta/servicio) y sincroniza el Ingreso asociado: lo crea si la cita
    ahora cuenta como ingreso y no lo tenía, lo actualiza si el costo/estatus
    cambiaron, y lo elimina si un ajuste de estatus hace que ya no cuente
    (ej. una cita se corrige de 'Sí asistió' a 'Canceló'). Así se cumple la
    regla de 'permitir recalcular reportes si se corrige el estatus'."""
    cita, creada = CitaRecepcion.objects.select_related('ingreso').update_or_create(
        fecha=fila['fecha'], hora=fila['hora'], paciente=fila['paciente'],
        terapeuta=fila['terapeuta'], servicio=fila['servicio'],
        defaults={
            'tipo_cita': fila['tipo_cita'],
            'division': fila['division'],
            'consultorio': fila['consultorio'],
            'estatus': fila['estatus'],
            'metodo_pago': fila['metodo_pago'],
            'costo': fila['costo'],
        },
    )

    debe_contar = cuenta_como_ingreso(fila)
    if debe_contar:
        if cita.ingreso_id:
            ingreso = cita.ingreso
            ingreso.persona = cita.paciente
            ingreso.monto = cita.costo
            ingreso.fecha = cita.fecha
            ingreso.estatus = Ingreso.Estatus.PAGADO
            ingreso.save()
        else:
            ingreso = Ingreso.objects.create(
                concepto=Ingreso.Concepto.CONSULTA,
                persona=cita.paciente,
                monto=cita.costo,
                estatus=Ingreso.Estatus.PAGADO,
                fecha=cita.fecha,
            )
            cita.ingreso = ingreso
            cita.save(update_fields=['ingreso'])
    elif cita.ingreso_id:
        ingreso = cita.ingreso
        cita.ingreso = None
        cita.save(update_fields=['ingreso'])
        ingreso.delete()

    return cita, creada


def importar_citas(filas):
    resumen = {'creadas': 0, 'actualizadas': 0, 'con_ingreso': 0}
    for fila in filas:
        cita, creada = importar_cita(fila)
        resumen['creadas' if creada else 'actualizadas'] += 1
        if cita.ingreso_id:
            resumen['con_ingreso'] += 1
    return resumen
