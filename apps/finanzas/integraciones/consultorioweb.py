import requests
from django.conf import settings


class ConsultorioWebError(Exception):
    """Error de comunicación con la API de ConsultorioWeb (red, timeout,
    autenticación o respuesta inesperada)."""


def _get(ruta, params, timeout):
    url = f'{settings.CONSULTORIOWEB_API_URL.rstrip("/")}{ruta}'
    try:
        respuesta = requests.get(
            url, params=params, timeout=timeout,
            headers={'X-API-Key': settings.CONSULTORIOWEB_API_KEY},
        )
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        raise ConsultorioWebError(f'No se pudo conectar con ConsultorioWeb: {exc}') from exc
    return respuesta.json()


def obtener_cortes_semanales(fecha_inicio=None, fecha_fin=None, timeout=10):
    """Llama a GET /api/nomina-semanal/ de ConsultorioWeb y regresa la lista
    de cortes tal cual la entrega la API (sin filtrar por estatus: eso es
    responsabilidad de la capa de negocio, ver integraciones/importador_nomina.py)."""
    params = {}
    if fecha_inicio:
        params['fecha_inicio'] = fecha_inicio
    if fecha_fin:
        params['fecha_fin'] = fecha_fin
    return _get('/api/nomina-semanal/', params, timeout)


def obtener_citas_recepcion(fecha_inicio=None, fecha_fin=None, timeout=10):
    """Llama a GET /api/reporte-general/ de ConsultorioWeb y regresa la lista
    de citas del rango tal cual la entrega la API (sin aplicar la regla de
    qué cuenta como ingreso: eso es responsabilidad de
    integraciones/importador_recepcion.py). Mismo formato de dict que espera
    esa capa (ver integraciones/reporte_recepcion.py::leer_reporte_excel),
    excepto que fecha/hora vienen como strings ISO en vez de objetos date/time."""
    params = {}
    if fecha_inicio:
        params['fecha_inicio'] = fecha_inicio
    if fecha_fin:
        params['fecha_fin'] = fecha_fin
    return _get('/api/reporte-general/', params, timeout)
