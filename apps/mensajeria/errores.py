import uuid

from django.http import JsonResponse


class ErrorPasarela(Exception):
    """Error de negocio de la pasarela. `codigo` es estable (ver tabla de la
    sección 7 del contrato); `mensaje` es seguro para mostrar en pantalla."""

    def __init__(self, codigo, mensaje, status=422, field_errors=None):
        self.codigo = codigo
        self.mensaje = mensaje
        self.status = status
        self.field_errors = field_errors
        super().__init__(mensaje)


# Códigos de la sección 7 del contrato, más los de autenticación/transporte
# que ese contrato da por hechos (mismo formato que
# docs/CONTRATO_API_INTERA_CONSULTORIO_V1.md, sección 6).
AUTENTICACION_INVALIDA = ErrorPasarela(
    'autenticacion_invalida', 'Credencial ausente, vencida o inválida.', status=401,
)
VERSION_NO_SOPORTADA = ErrorPasarela(
    'version_no_soportada', 'X-Contract-Version no coincide con una versión soportada.', status=400,
)
JSON_INVALIDO = ErrorPasarela(
    'json_invalido', 'El cuerpo de la solicitud no es JSON válido.', status=400,
)
PLANTILLA_DESCONOCIDA = 'plantilla_desconocida'
VARIABLES_INCOMPLETAS = 'variables_incompletas'
DESTINATARIO_INVALIDO = 'destinatario_invalido'
DESTINATARIO_DADO_DE_BAJA = 'destinatario_dado_de_baja'
FUERA_DE_VENTANA = 'fuera_de_ventana'
PROVEEDOR_NO_DISPONIBLE = 'proveedor_no_disponible'
IDEMPOTENCIA_EN_CONFLICTO = 'idempotencia_en_conflicto'
ENVIO_NO_ENCONTRADO = 'envio_no_encontrado'


def respuesta_de_error(request_id, error):
    cuerpo = {
        'code': error.codigo,
        'message': error.mensaje,
        'request_id': request_id,
    }
    if error.field_errors:
        cuerpo['field_errors'] = error.field_errors
    return JsonResponse(cuerpo, status=error.status)


def request_id_de(request):
    return request.headers.get('X-Request-ID') or str(uuid.uuid4())
