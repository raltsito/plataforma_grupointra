import requests
from django.conf import settings


class ConsultorioWebError(Exception):
    """Error de comunicación con la API de ConsultorioWeb (red, timeout,
    autenticación o respuesta inesperada)."""


def obtener_cortes_semanales(fecha_inicio=None, fecha_fin=None, timeout=10):
    """Llama a GET /api/nomina-semanal/ de ConsultorioWeb y regresa la lista
    de cortes tal cual la entrega la API (sin filtrar por estatus: eso es
    responsabilidad de la capa de negocio, ver integraciones/importador_nomina.py)."""
    params = {}
    if fecha_inicio:
        params['fecha_inicio'] = fecha_inicio
    if fecha_fin:
        params['fecha_fin'] = fecha_fin
    url = f'{settings.CONSULTORIOWEB_API_URL.rstrip("/")}/api/nomina-semanal/'
    try:
        respuesta = requests.get(
            url, params=params, timeout=timeout,
            headers={'X-API-Key': settings.CONSULTORIOWEB_API_KEY},
        )
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        raise ConsultorioWebError(f'No se pudo conectar con ConsultorioWeb: {exc}') from exc
    return respuesta.json()
