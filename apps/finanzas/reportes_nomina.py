from collections import defaultdict
from decimal import Decimal

from .models import Egreso

# El importador de ConsultorioWeb (integraciones/importador_nomina.py) crea
# hasta 3 Egresos por corte, con referencia_externa
# 'consultorioweb:corte:{id}:{parte}'. Para reconstruir una fila por persona
# (como pide la sección 4.1 del documento) usamos ese sufijo para saber a
# qué columna corresponde cada Egreso, sin necesidad de un campo nuevo.
PARTE_A_COLUMNA = {
    'base': 'pago_base',
    'bono': 'vale',
    'extra': 'bono',
}


def _parte_de(egreso):
    if not egreso.referencia_externa:
        return None
    return egreso.referencia_externa.rsplit(':', 1)[-1]


def resumen_nomina_semanal(fecha_inicio, fecha_fin):
    """Agrupa los Egresos de nómina de terapeutas (ya importados de
    ConsultorioWeb) por persona, para la descarga de nómina en PDF.
    Reconstruye pago base / vale de gasolina / bono a partir de los Egresos
    separados que genera el importador."""
    egresos = Egreso.objects.filter(
        categoria=Egreso.Categoria.NOMINA_TERAPEUTAS,
        fecha__gte=fecha_inicio,
        fecha__lte=fecha_fin,
    ).order_by('persona', 'fecha')

    por_persona = defaultdict(lambda: {
        'persona': '',
        'pago_base': Decimal('0'), 'vale': Decimal('0'), 'bono': Decimal('0'),
        'metodo_pago': '', 'metodo_pago_display': '', 'estatus': Egreso.Estatus.PAGADO,
        'pendiente': Decimal('0'), 'vale_pendiente': Decimal('0'), 'vale_entregado': Decimal('0'),
    })

    for egreso in egresos:
        fila = por_persona[egreso.persona]
        fila['persona'] = egreso.persona
        columna = PARTE_A_COLUMNA.get(_parte_de(egreso))
        if columna:
            fila[columna] += egreso.monto
        if egreso.metodo_pago and not fila['metodo_pago']:
            fila['metodo_pago'] = egreso.metodo_pago
        if egreso.estatus == Egreso.Estatus.PENDIENTE:
            fila['estatus'] = Egreso.Estatus.PENDIENTE
            fila['pendiente'] += egreso.monto
            if columna == 'vale':
                fila['vale_pendiente'] += egreso.monto
        elif columna == 'vale':
            fila['vale_entregado'] += egreso.monto

    metodos_display = dict(Egreso.MetodoPago.choices)
    filas = sorted(por_persona.values(), key=lambda f: f['persona'])
    for fila in filas:
        fila['total'] = fila['pago_base'] + fila['vale'] + fila['bono']
        if fila['metodo_pago']:
            fila['metodo_pago_display'] = metodos_display[fila['metodo_pago']]

    totales = {
        'pendiente_dispersar': sum((f['pendiente'] for f in filas), Decimal('0')),
        'pendiente_transferencia': sum(
            (f['pendiente'] for f in filas if f['metodo_pago'] == Egreso.MetodoPago.TRANSFERENCIA),
            Decimal('0'),
        ),
        'pendiente_efectivo': sum(
            (f['pendiente'] for f in filas if f['metodo_pago'] == Egreso.MetodoPago.EFECTIVO),
            Decimal('0'),
        ),
        'vales_pendientes': sum((f['vale_pendiente'] for f in filas), Decimal('0')),
    }

    return filas, totales
