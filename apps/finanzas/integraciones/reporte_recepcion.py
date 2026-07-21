from datetime import date, datetime, time
from decimal import Decimal

import openpyxl

from apps.finanzas.models import CitaRecepcion

# Este módulo es el punto de entrada de datos: hoy lee el Excel exportado
# manualmente desde agenda.intra.org.mx/reporte-general/. Si esa plataforma
# expone en el futuro un endpoint de API (como ya existe para nómina
# semanal, ver integraciones/consultorioweb.py), basta con reemplazar
# `leer_reporte_excel` por un cliente que devuelva la misma forma de datos
# (lista de dicts con estas claves) — el resto del flujo (importador_recepcion.py)
# no necesita cambiar.

COLUMNAS_ESPERADAS = [
    'Fecha', 'Hora', 'Tipo', 'Paciente', 'Terapeuta', 'Servicio',
    'División', 'Consultorio', 'Estatus', 'Método de Pago', 'Costo ($)',
]

_ESTATUS_A_CHOICE = {
    'confirmada': CitaRecepcion.Estatus.CONFIRMADA,
    'sin confirmar': CitaRecepcion.Estatus.SIN_CONFIRMAR,
    'reagendo': CitaRecepcion.Estatus.REAGENDO,
    'cancelo': CitaRecepcion.Estatus.CANCELO,
    'si asistio': CitaRecepcion.Estatus.SI_ASISTIO,
    'no asistio': CitaRecepcion.Estatus.NO_ASISTIO,
    'incidencia': CitaRecepcion.Estatus.INCIDENCIA,
}

_METODO_A_CHOICE = {
    'transferencia': CitaRecepcion.MetodoPago.TRANSFERENCIA,
    'efectivo': CitaRecepcion.MetodoPago.EFECTIVO,
    'pase': CitaRecepcion.MetodoPago.PASE,
    'debito': CitaRecepcion.MetodoPago.DEBITO,
    'credito': CitaRecepcion.MetodoPago.CREDITO,
}


class ReporteRecepcionError(Exception):
    """El archivo subido no tiene el formato esperado del Reporte General."""


def _texto(valor):
    return str(valor).strip() if valor is not None else ''


def _estatus(valor):
    # El Excel trae la etiqueta con espacios ('Si asistio'); la API de
    # ConsultorioWeb trae el código interno con guión bajo ('si_asistio').
    # Normalizamos a espacios para que ambas fuentes usen el mismo mapeo.
    clave = _texto(valor).lower().replace('_', ' ')
    if clave not in _ESTATUS_A_CHOICE:
        raise ReporteRecepcionError(f"Estatus desconocido en el reporte: '{valor}'.")
    return _ESTATUS_A_CHOICE[clave]


def _metodo_pago(valor):
    clave = _texto(valor).lower()
    return _METODO_A_CHOICE.get(clave, '')


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    if '/' in texto:
        return datetime.strptime(texto, '%d/%m/%Y').date()
    return date.fromisoformat(texto)  # formato ISO 'YYYY-MM-DD', como lo entrega la API


def _hora(valor):
    if isinstance(valor, datetime):
        return valor.time()
    if isinstance(valor, time):
        return valor
    return datetime.strptime(_texto(valor), '%H:%M').time()


def _costo(valor):
    if valor in (None, ''):
        return Decimal('0')
    return Decimal(str(valor))


def leer_reporte_api(fecha_inicio=None, fecha_fin=None):
    """Igual que leer_reporte_excel, pero jala las citas directo de
    GET /api/reporte-general/ en ConsultorioWeb (ver
    integraciones/consultorioweb.py::obtener_citas_recepcion) en vez de
    depender de un archivo exportado a mano. Se agregó cuando se confirmó que
    ese endpoint sí existe (2026-07-21) — el Excel se conserva como respaldo
    manual en leer_reporte_excel."""
    from .consultorioweb import obtener_citas_recepcion

    citas_raw = obtener_citas_recepcion(fecha_inicio, fecha_fin)
    citas = []
    for cita in citas_raw:
        citas.append({
            'fecha': _fecha(cita['fecha']),
            'hora': _hora(cita['hora']),
            'tipo_cita': _texto(cita.get('tipo_cita')),
            'paciente': _texto(cita.get('paciente')),
            'terapeuta': _texto(cita.get('terapeuta')),
            'servicio': _texto(cita.get('servicio')),
            'division': _texto(cita.get('division')),
            'consultorio': _texto(cita.get('consultorio')),
            'estatus': _estatus(cita.get('estatus')),
            'metodo_pago': _metodo_pago(cita.get('metodo_pago')),
            'costo': _costo(cita.get('costo')),
        })
    return citas


def leer_reporte_excel(archivo):
    """Lee el archivo .xlsx del Reporte General de Recepción y regresa una
    lista de dicts normalizados, uno por cita. `archivo` es cualquier objeto
    tipo-archivo (ej. UploadedFile de Django)."""
    try:
        libro = openpyxl.load_workbook(archivo, data_only=True, read_only=True)
    except Exception as exc:
        raise ReporteRecepcionError(f'No se pudo leer el archivo: {exc}') from exc

    hoja = libro.worksheets[0]
    filas = hoja.iter_rows(values_only=True)
    encabezado = [_texto(c) for c in next(filas, [])]
    if encabezado != COLUMNAS_ESPERADAS:
        raise ReporteRecepcionError(
            'El archivo no tiene las columnas esperadas del Reporte General '
            f'(se encontró: {encabezado}).'
        )

    citas = []
    for num_fila, fila in enumerate(filas, start=2):
        if fila is None or all(c is None for c in fila):
            continue
        try:
            citas.append({
                'fecha': _fecha(fila[0]),
                'hora': _hora(fila[1]),
                'tipo_cita': _texto(fila[2]),
                'paciente': _texto(fila[3]),
                'terapeuta': _texto(fila[4]),
                'servicio': _texto(fila[5]),
                'division': _texto(fila[6]),
                'consultorio': _texto(fila[7]),
                'estatus': _estatus(fila[8]),
                'metodo_pago': _metodo_pago(fila[9]),
                'costo': _costo(fila[10]),
            })
        except (ReporteRecepcionError, ValueError, IndexError) as exc:
            raise ReporteRecepcionError(f'Fila {num_fila} del Excel inválida: {exc}') from exc
    return citas
