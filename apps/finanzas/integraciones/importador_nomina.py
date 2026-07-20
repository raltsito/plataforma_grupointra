from decimal import Decimal

from django.db import transaction

from apps.finanzas.models import Egreso

# Un corte solo se importa una vez sellado del lado de ConsultorioWeb. La API
# de origen no filtra por estatus, así que ese filtro vive aquí: nunca se
# importa un corte en 'borrador', porque todavía puede recalcularse.
ESTATUS_IMPORTABLES = {'aprobado', 'pagado'}


def cortes_importables(cortes_raw):
    return [c for c in cortes_raw if c.get('estatus') in ESTATUS_IMPORTABLES]


def _referencia(corte_id, parte):
    return f'consultorioweb:corte:{corte_id}:{parte}'


def ya_importado(corte_id):
    return Egreso.objects.filter(referencia_externa__startswith=_referencia(corte_id, '')).exists()


@transaction.atomic
def importar_corte(corte):
    """Convierte un corte semanal (dict de la API de ConsultorioWeb) en hasta
    3 Egresos: pago base, vale de gasolina/bono y bono extra — separados,
    como pide la sección 3.1 del documento de requerimientos. Idempotente vía
    referencia_externa + get_or_create: volver a llamar con el mismo corte
    nunca duplica filas."""
    terapeuta = corte['terapeuta']
    fecha = corte['fecha_fin']
    semana = f"{corte['fecha_inicio']} – {corte['fecha_fin']}"
    subtotal = Decimal(str(corte['subtotal_sesiones']))
    bono = Decimal(str(corte['total_bonos']))
    extra = Decimal(str(corte['total_pago'])) - subtotal - bono

    filas = [('base', 'Pago a terapeuta', subtotal)]
    if bono > 0:
        filas.append(('bono', 'Vale de gasolina / bono', bono))
    if extra > 0:
        filas.append(('extra', 'Bono extra', extra))

    creados = []
    for parte, etiqueta, monto in filas:
        egreso, fue_creado = Egreso.objects.get_or_create(
            referencia_externa=_referencia(corte['id'], parte),
            defaults=dict(
                concepto=f'{etiqueta} · {terapeuta} · semana {semana}',
                categoria=Egreso.Categoria.NOMINA_TERAPEUTAS,
                persona=terapeuta,
                monto=monto,
                fecha=fecha,
                estatus=Egreso.Estatus.PENDIENTE,
            ),
        )
        if fue_creado:
            creados.append(egreso)
    return creados


def importar_cortes(cortes):
    resumen = {'creados': 0, 'omitidos': 0}
    for corte in cortes:
        nuevas = importar_corte(corte)
        resumen['creados'] += len(nuevas)
        if not nuevas:
            resumen['omitidos'] += 1
    return resumen
