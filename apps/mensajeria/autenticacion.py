from functools import wraps

from django.views.decorators.csrf import csrf_exempt

from .errores import (
    AUTENTICACION_INVALIDA,
    VERSION_NO_SOPORTADA,
    request_id_de,
    respuesta_de_error,
)
from .models import SistemaSuscrito

VERSION_SOPORTADA = '1'


def _api_key_de(request):
    valor = request.headers.get('Authorization', '')
    if valor.startswith('ApiKey '):
        return valor[len('ApiKey '):].strip()
    return ''


def requiere_sistema_autenticado(vista):
    """Valida `Authorization: ApiKey` y `X-Contract-Version: 1`, igual que
    el contrato v1 de Consultorio Web (D2). Deja el `SistemaSuscrito` en
    `request.sistema_mensajeria` para que la vista sepa quién llama sin
    volver a leer cabeceras."""

    @csrf_exempt
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        request_id = request_id_de(request)

        if request.headers.get('X-Contract-Version') != VERSION_SOPORTADA:
            return respuesta_de_error(request_id, VERSION_NO_SOPORTADA)

        api_key = _api_key_de(request)
        sistema = (
            SistemaSuscrito.objects.filter(api_key=api_key, activo=True).first()
            if api_key else None
        )
        if sistema is None:
            return respuesta_de_error(request_id, AUTENTICACION_INVALIDA)

        request.sistema_mensajeria = sistema
        request.request_id_mensajeria = request_id
        return vista(request, *args, **kwargs)

    return _envuelta
