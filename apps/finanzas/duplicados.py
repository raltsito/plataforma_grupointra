class DuplicadoError(Exception):
    """Ya existe un registro para esta combinación de periodo/persona/concepto
    y el flujo que llama debe bloquear la captura (a diferencia de un
    import/sincronización, que debe actualizar el registro existente en vez
    de rechazarlo — ver CitaRecepcion e importador_nomina.py, que
    deliberadamente usan update_or_create/get_or_create en lugar de este
    helper)."""


def existe_duplicado(modelo, **filtros):
    """Verifica si ya existe un registro con esta combinación de campos.
    No decide qué hacer con el resultado: los flujos de captura manual
    (Honorario, NominaAcademia) lo usan para bloquear con DuplicadoError;
    los flujos de sincronización externa (Egreso.referencia_externa,
    CitaRecepcion) usan su propio update_or_create/get_or_create porque ahí
    sí se debe actualizar, no rechazar."""
    return modelo.objects.filter(**filtros).exists()
