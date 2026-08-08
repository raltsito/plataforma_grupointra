"""Reglas reutilizables de calificacion para instrumentos de Portafolio.

Las calculadoras no conocen procesos, participantes ni modelos consumidores.
Cada modulo les entrega respuestas ordenadas y, cuando es necesario, contexto
demografico. El modulo consumidor decide como persistir el resultado.
"""

from datetime import date
from decimal import Decimal

from .models import CalculadoraInstrumento, Instrumento


ADVERTENCIA_RESULTADO_ORIENTATIVO = (
    'Resultado orientativo: La calificación fue generada automáticamente '
    'conforme a la configuración actual del instrumento. Debe ser revisada '
    'y validada por personal autorizado antes de utilizarse para decisiones '
    'de seguimiento. No debe interpretarse de manera aislada ni sustituye la '
    'valoración profesional.'
)
ADVERTENCIA_CORTA_RESULTADO_ORIENTATIVO = (
    'Resultado generado automáticamente. Requiere revisión profesional '
    'antes de considerarse definitivo.'
)
ADVERTENCIA_SCID2_ADOLESCENTES = (
    'Resultado orientativo para población adolescente. La calificación se generó '
    'con base en el protocolo disponible para la adaptación de 12 a 17 años. '
    'Requiere revisión profesional para confirmar la aplicación de criterios por '
    'edad, omisiones permitidas, alertas especiales e interpretación. No constituye '
    'un diagnóstico.'
)
ADVERTENCIA_CORTA_SCID2_ADOLESCENTES = (
    'Resultado orientativo. Requiere revisión profesional y validación de criterios '
    'específicos para adolescentes.'
)
ADVERTENCIA_PLUTCHIK_ADOLESCENTES = (
    'Resultado orientativo de tamizaje. Requiere revisión profesional y no debe '
    'interpretarse como diagnóstico ni como predicción de conducta suicida.'
)
ADVERTENCIA_PLUTCHIK_PRIORITARIA = (
    'Se identificó una respuesta crítica que requiere revisión clínica prioritaria '
    'y aplicación del protocolo institucional correspondiente.'
)


_ALIAS_CLAVES = {
    'scid-ii': 'scid2',
    'scid_ii': 'scid2',
    'scid ii': 'scid2',
    'scid': 'scid2',
    'scl': 'scl90',
    'scl-90': 'scl90',
    'scl-90-r': 'scl90',
    'dass21': 'dass-21',
    'dass_21': 'dass-21',
    'raven-spm': 'raven',
}

_CONTEXTOS_REQUERIDOS = {
    'dass-21-adolescentes': {'fecha_nacimiento'},
    'rse-autoestima': {'fecha_nacimiento'},
    'scid-ii-adolescentes': {'fecha_nacimiento'},
    'ersp-plutchik-adolescentes': {'fecha_nacimiento'},
    'raven': {
        'fecha_nacimiento',
    },
    'isra': {
        'sexo',
    },
}

_VARIANTE_POR_CLAVE_EXACTA = {
    'dass-21-adolescentes': 'adolescente',
    'rse-autoestima': 'adolescente',
    'scid-ii-adolescentes': 'adolescente',
    'ersp-plutchik-adolescentes': 'adolescente',
    'dass-21': 'adulta',
    'scid2': 'adulta',
}


def clave_calculadora(clave):
    return _ALIAS_CLAVES.get(
        (clave or '').strip().lower(),
        (clave or '').strip().lower(),
    )


def campos_contexto_requeridos(instrumento_o_clave):
    """Obtiene el contexto declarado en la importación del instrumento.

    La clave conserva el comportamiento heredado para instrumentos anteriores
    a la importación estructurada; los consumidores actuales entregan el
    instrumento para no decidir requisitos por nombre.
    """
    if hasattr(instrumento_o_clave, 'clave'):
        try:
            metadatos = instrumento_o_clave.importacion.metadatos or {}
        except Instrumento.importacion.RelatedObjectDoesNotExist:
            metadatos = {}
        campos = metadatos.get('campos_contexto_requeridos') or []
        campos = {
            campo
            for campo in campos
            if campo in {'sexo', 'fecha_nacimiento', 'edad'}
        }
        if campos:
            return campos
        clave = instrumento_o_clave.clave
    else:
        clave = instrumento_o_clave
    return _CONTEXTOS_REQUERIDOS.get(
        clave_calculadora(clave),
        set(),
    )


def _metadatos_estado_revision(estado):
    orientativa = estado == CalculadoraInstrumento.Estado.ORIENTATIVA

    return {
        'puede_ejecutarse': estado in {
            CalculadoraInstrumento.Estado.ACTIVA,
            CalculadoraInstrumento.Estado.ORIENTATIVA,
            CalculadoraInstrumento.Estado.NO_DIAGNOSTICA,
        },
        'requiere_revision_profesional': orientativa,
        'estado_revision': (
            'pendiente_revision_profesional'
            if orientativa
            else 'validada'
            if estado == CalculadoraInstrumento.Estado.ACTIVA
            else estado
        ),
        'advertencia_larga': (
            ADVERTENCIA_RESULTADO_ORIENTATIVO
            if orientativa
            else ''
        ),
        'advertencia_corta': (
            ADVERTENCIA_CORTA_RESULTADO_ORIENTATIVO
            if orientativa
            else ''
        ),
    }


def obtener_revision_calculadora(instrumento):
    """Obtiene una calculadora sin elegir versiones ambiguas arbitrariamente."""

    calculadoras = list(
        CalculadoraInstrumento.objects.filter(
            instrumento=instrumento,
            version_regla=instrumento.version,
        ).order_by('clave')
    )

    if len(calculadoras) != 1:
        return {
            'calculadora_encontrada': False,
            'seleccion': (
                'ausente'
                if not calculadoras
                else 'ambigua'
            ),
            'puede_ejecutarse': False,
            'requiere_revision_profesional': False,
            'estado_revision': 'sin_calculadora',
            'advertencia_larga': '',
            'advertencia_corta': '',
            'snapshot': None,
        }

    calculadora = calculadoras[0]
    metadatos = _metadatos_estado_revision(calculadora.estado)
    metadatos.update(
        {
            'calculadora_encontrada': True,
            'seleccion': 'exacta',
            'snapshot': {
                'clave': calculadora.clave,
                'version_regla': calculadora.version_regla,
                'estado': calculadora.estado,
                'clave_instrumento_normalizada': clave_calculadora(
                    instrumento.clave
                ),
            },
        }
    )
    return metadatos


def obtener_revision_resultado(snapshot):
    """Reconstruye la presentaciÃ³n desde el snapshot histÃ³rico del resultado."""

    if not snapshot:
        return {
            'requiere_revision_profesional': False,
            'estado_revision': 'sin_snapshot',
            'advertencia_larga': '',
            'advertencia_corta': '',
        }

    metadatos = _metadatos_estado_revision(snapshot.get('estado'))
    if snapshot.get('requiere_revision_profesional'):
        metadatos.update(
            {
                'requiere_revision_profesional': True,
                'estado_revision': snapshot.get(
                    'estado_revision',
                    'pendiente_revision_profesional',
                ),
                'advertencia_larga': snapshot.get('advertencia_larga', ''),
                'advertencia_corta': snapshot.get('advertencia_corta', ''),
            }
        )
    return metadatos


_SCID2_TRASTORNOS = (
    (
        'Evitacion',
        range(1, 8),
        4,
    ),
    (
        'Dependencia',
        range(8, 16),
        5,
    ),
    (
        'Obsesivo-Compulsivo',
        range(16, 25),
        4,
    ),
    (
        'Pasivo-Agresivo',
        range(25, 33),
        4,
    ),
    (
        'Depresivo',
        range(33, 41),
        5,
    ),
    (
        'Paranoide',
        range(41, 49),
        4,
    ),
    (
        'Esquizotipico',
        range(49, 60),
        5,
    ),
    (
        'Esquizoide',
        range(60, 66),
        5,
    ),
    (
        'Histrionico',
        range(66, 73),
        5,
    ),
    (
        'Narcisista',
        range(73, 90),
        5,
    ),
    (
        'Limite',
        range(90, 105),
        5,
    ),
    (
        'Antisocial',
        range(105, 120),
        5,
    ),
)


def _calcular_scid2(respuestas, contexto=None):
    por_orden = {
        r.pregunta.orden: r.valor_numerico or Decimal('0')
        for r in respuestas
    }

    detalle = {}
    significativos = []

    for nombre, items, umbral in _SCID2_TRASTORNOS:
        suma = int(
            sum(
                por_orden.get(
                    item + 3,
                    Decimal('0'),
                )
                for item in items
                if item < 117
            )
        )

        significativo = suma >= umbral

        detalle[f'TP {nombre}'] = {
            'puntaje': suma,
            'reactivos': len(items),
            'umbral': umbral,
            'resultado': (
                'Significativo'
                if significativo
                else 'No significativo'
            ),
        }

        if significativo:
            significativos.append(nombre)

    total = len(significativos)

    if not total:
        interpretacion = (
            'No se identificaron trastornos de personalidad clinicamente '
            'significativos en las 12 escalas evaluadas.'
        )
    elif total == 1:
        interpretacion = (
            'Puntuacion significativa en trastorno de personalidad por '
            f'{significativos[0]}. Se recomienda revision clinica detallada.'
        )
    else:
        interpretacion = (
            f'Puntuaciones significativas en {total} escalas: '
            f'{", ".join(significativos)}. Se recomienda evaluacion '
            'clinica integral.'
        )

    return {
        'puntaje_total': Decimal(str(total)),
        'interpretacion': interpretacion,
        'detalle': detalle,
    }


_CALCULADORAS = {
    'scid2': _calcular_scid2,
}


def _mapa(respuestas):
    return {
        r.pregunta.orden: r.valor_numerico or Decimal('0')
        for r in respuestas
    }


def _sumar_subescalas(mapa, grupos):
    """Suma grupos de reactivos sin asignar cortes ni interpretaciones."""
    return {
        nombre: sum(
            mapa.get(reactivo, Decimal('0'))
            for reactivo in reactivos
        )
        for nombre, reactivos in grupos.items()
    }


def _numero_para_detalle(valor):
    """Convierte Decimal a un valor apto para el JSON de resultados."""
    return (
        int(valor)
        if valor == valor.to_integral_value()
        else float(valor)
    )


_SCID2_ADOLESCENTES_BLOQUES = {
    'Evitación': range(1, 8),
    'Dependencia': range(8, 16),
    'Obsesivo-compulsivo': range(16, 25),
    'Pasivo-agresivo': range(25, 33),
    'Depresivo': range(33, 41),
    'Paranoide': range(41, 49),
    'Esquizotípico': range(49, 60),
    'Esquizoide': range(60, 66),
    'Histriónico': range(66, 73),
    'Narcisista': range(73, 90),
    'Límite': range(90, 105),
    'Conductas problemáticas': range(105, 120),
}


def edad_cumplida(fecha_nacimiento, fecha_aplicacion):
    """Edad cumplida en la fecha histórica de aplicación, sin aproximaciones."""
    if not fecha_nacimiento or not fecha_aplicacion:
        return None
    return fecha_aplicacion.year - fecha_nacimiento.year - (
        (fecha_aplicacion.month, fecha_aplicacion.day)
        < (fecha_nacimiento.month, fecha_nacimiento.day)
    )


def validar_variante_por_edad(instrumento, contexto=None):
    contexto = contexto or {}
    fecha_nacimiento = contexto.get('fecha_nacimiento')
    fecha_aplicacion = contexto.get('fecha_aplicacion')
    edad = edad_cumplida(fecha_nacimiento, fecha_aplicacion)
    variante = _VARIANTE_POR_CLAVE_EXACTA.get(instrumento.clave)
    base = {
        'fecha_nacimiento': fecha_nacimiento.isoformat() if fecha_nacimiento else None,
        'fecha_aplicacion': fecha_aplicacion.isoformat() if fecha_aplicacion else None,
        'edad_cumplida': edad,
        'variante': variante,
        'clave_variante': instrumento.clave,
        'version_instrumento': instrumento.version,
    }
    if not fecha_nacimiento:
        return {**base, 'aplicable': False, 'motivo': 'fecha_nacimiento_requerida'}
    if not fecha_aplicacion:
        return {**base, 'aplicable': False, 'motivo': 'fecha_aplicacion_requerida'}
    if edad < 12:
        return {**base, 'aplicable': False, 'motivo': 'menor_de_12_sin_variante_autorizada'}
    grupo = 'adolescente' if edad <= 18 else 'adulto'
    if variante != grupo:
        return {**base, 'aplicable': False, 'grupo_edad': grupo, 'motivo': 'variante_no_aplicable'}
    return {**base, 'aplicable': True, 'grupo_edad': grupo, 'motivo': 'variante_validada'}


def _calcular_scid2_adolescentes(respuestas, contexto=None):
    """Cuenta bloques del protocolo adolescente sin aplicar umbrales adultos."""
    contexto = contexto or {}
    respuestas_por_orden = _mapa(respuestas)
    respondidos = set(respuestas_por_orden)
    omisiones = [orden for orden in range(1, 120) if orden not in respondidos]
    edad = edad_cumplida(
        contexto.get('fecha_nacimiento'),
        contexto.get('fecha_aplicacion'),
    )
    edad_valida = edad is not None and 12 <= edad <= 18
    bloques = {
        nombre: {
            'respuestas_afirmativas': _numero_para_detalle(
                sum(respuestas_por_orden.get(orden, Decimal('0')) for orden in reactivos)
            ),
            'reactivos_evaluados': len(reactivos),
            'estado': (
                'Requiere revisión profesional'
                if nombre == 'Conductas problemáticas'
                else 'Conteo administrativo para revisión'
            ),
        }
        for nombre, reactivos in _SCID2_ADOLESCENTES_BLOQUES.items()
    }
    limitaciones = [
        'Verificar omisiones y condiciones específicas por edad.',
        'Verificar alertas y revisiones especiales del protocolo.',
        'Confirmar manualmente los reactivos administrativos.',
        'Confirmar la interpretación conforme al protocolo adolescente.',
    ]
    if edad is None:
        limitaciones.append('No fue posible validar la edad de 12 a 17 años.')
    elif edad == 18:
        limitaciones.append(
            'La persona tiene 18 años. INTERA la incluye en el flujo adolescente, '
            'pero la fuente disponible para esta adaptación documenta el rango de 12 '
            'a 17 años. El resultado requiere revisión profesional antes de su interpretación.'
        )
    elif not edad_valida:
        limitaciones.append('La edad registrada está fuera del rango de 12 a 18 años.')

    return {
        'puntaje_total': sum(
            Decimal(str(bloque['respuestas_afirmativas']))
            for bloque in bloques.values()
        ),
        'interpretacion': (
            'Conteos administrativos del protocolo SCID-II adolescente; requieren '
            'revisión profesional y no constituyen un diagnóstico.'
            if edad_valida
            else 'Resultado no aplicable para interpretación automática; requiere revisión profesional.'
        ),
        'detalle': {
            'bloques': bloques,
            'omisiones_encontradas': omisiones,
            'revision_manual_requerida': True,
            'limitaciones': limitaciones,
            'reglas_automatizadas': [
                'Conteo de respuestas afirmativas por bloque.',
                'Validación del rango de edad con fecha de nacimiento disponible.',
                'Identificación del bloque de conductas problemáticas como no interpretable automáticamente.',
            ],
            'reglas_pendientes': [
                'Omitir_menor_16 y condiciones específicas por reactivo.',
                'Alertas y revisiones especiales por reactivo.',
                'Condiciones administrativas y reglas de interpretación del protocolo.',
            ],
            'poblacion': 'Adolescentes de 12 a 17 años',
            'edad_calculada': edad,
            'validacion_edad': 'válida' if edad_valida else 'pendiente o no aplicable',
            'protocolo_utilizado': 'SCID-II adolescentes v1.0 (provisional)',
            'fecha_calculo': date.today().isoformat(),
        },
    }


def _calcular_plutchik_adolescentes(respuestas, contexto=None):
    """Calcula el tamizaje adolescente y marca reactivos críticos sin alertar fuera del sistema."""
    valores = _mapa(respuestas)
    afirmativos = [
        orden
        for orden in range(1, 16)
        if valores.get(orden, Decimal('0')) == Decimal('1')
    ]
    criticos = [orden for orden in (13, 14, 15) if orden in afirmativos]
    revision_prioritaria = bool(criticos)
    return {
        'puntaje_total': Decimal(str(len(afirmativos))),
        'interpretacion': (
            'Tamizaje orientativo de Plutchik adolescentes. No constituye un diagnóstico '
            'ni una predicción de conducta suicida.'
        ),
        'detalle': {
            'puntaje_total': len(afirmativos),
            'respuestas_afirmativas': len(afirmativos),
            'reactivos_criticos_afirmativos': criticos,
            'existe_respuesta_critica': revision_prioritaria,
            'revision_prioritaria': revision_prioritaria,
            'tipo_instrumento': 'Tamizaje',
            'no_diagnostico': True,
            'advertencia_prioritaria': (
                ADVERTENCIA_PLUTCHIK_PRIORITARIA if revision_prioritaria else ''
            ),
        },
    }


def _calcular_dass21_adolescentes(respuestas, contexto=None):
    """Califica DASS-21 adolescente sin reutilizar los cortes adultos."""
    grupos = {
        'Depresión': (3, 5, 10, 13, 16, 17, 21),
        'Ansiedad': (2, 4, 7, 9, 15, 19, 20),
        'Estrés': (1, 6, 8, 11, 12, 14, 18),
    }
    puntajes_brutos = _sumar_subescalas(_mapa(respuestas), grupos)
    detalle = {
        nombre: {
            'puntaje_bruto': _numero_para_detalle(puntaje),
            'puntaje_multiplicado': _numero_para_detalle(puntaje * 2),
        }
        for nombre, puntaje in puntajes_brutos.items()
    }

    return {
        'puntaje_total': sum(puntajes_brutos.values()) * 2,
        'interpretacion': (
            'DASS-21 adolescentes: se muestran puntajes por subescala '
            'como orientación. Los rangos disponibles son referencias de '
            'la versión adulta y no constituyen baremos adolescentes validados.'
        ),
        'detalle': detalle,
    }


def _limites_opciones_numericas(pregunta):
    valores = []
    for opcion in pregunta.opciones or []:
        try:
            valores.append(Decimal(str(opcion['valor'])))
        except (KeyError, TypeError, ValueError):
            continue
    if not valores:
        raise ValueError(
            'Rosenberg requiere opciones numéricas para invertir reactivos.'
        )
    return min(valores), max(valores)


def _calcular_rosenberg_orientativa(respuestas, contexto=None):
    """Califica Rosenberg con la codificación importada, sin baremo adolescente."""
    directos = {1, 3, 4, 6, 7}
    inversos = {2, 5, 8, 9, 10}
    detalle_directos = {}
    detalle_inversos = {}

    for respuesta in respuestas:
        orden = respuesta.pregunta.orden
        if orden not in directos | inversos:
            continue
        valor = respuesta.valor_numerico
        if valor is None:
            continue
        valor = Decimal(str(valor))
        if orden in directos:
            detalle_directos[orden] = valor
            continue
        minimo, maximo = _limites_opciones_numericas(respuesta.pregunta)
        detalle_inversos[orden] = {
            'valor_original': _numero_para_detalle(valor),
            'valor_invertido': _numero_para_detalle(minimo + maximo - valor),
            'rango_opciones': [
                _numero_para_detalle(minimo),
                _numero_para_detalle(maximo),
            ],
        }

    total_directos = sum(detalle_directos.values(), Decimal('0'))
    total_inversos = sum(
        (detalle['valor_invertido'] for detalle in detalle_inversos.values()),
        Decimal('0'),
    )
    total = total_directos + total_inversos
    return {
        'puntaje_total': total,
        'interpretacion': (
            'Rosenberg: resultado orientativo para la población utilizada '
            'en INTERA; no constituye un baremo adolescente validado ni un diagnóstico.'
        ),
        'detalle': {
            'reactivos_directos': {
                orden: _numero_para_detalle(valor)
                for orden, valor in detalle_directos.items()
            },
            'reactivos_inversos': detalle_inversos,
            'puntaje_directos': _numero_para_detalle(total_directos),
            'puntaje_inversos': _numero_para_detalle(total_inversos),
            'puntaje_total': _numero_para_detalle(total),
        },
    }


def _calcular_scl90(respuestas, contexto=None):
    escalas = [
        (
            'Somatización',
            [
                1,
                4,
                12,
                27,
                40,
                42,
                48,
                49,
                52,
                53,
                56,
                58,
            ],
            .36,
            .42,
        ),
        (
            'Obsesivo-Compulsivo',
            [
                3,
                9,
                10,
                28,
                38,
                45,
                46,
                51,
                55,
                65,
            ],
            .39,
            .45,
        ),
        (
            'Susceptibilidad interpersonal',
            [
                6,
                21,
                34,
                36,
                37,
                41,
                61,
                69,
                73,
            ],
            .29,
            .39,
        ),
        (
            'Depresión',
            [
                5,
                14,
                15,
                20,
                22,
                26,
                29,
                30,
                31,
                32,
                54,
                71,
                79,
            ],
            .36,
            .44,
        ),
        (
            'Ansiedad',
            [
                2,
                17,
                23,
                33,
                39,
                57,
                72,
                78,
                80,
                86,
            ],
            .30,
            .37,
        ),
        (
            'Hostilidad',
            [
                11,
                24,
                63,
                67,
                74,
                81,
            ],
            .30,
            .40,
        ),
        (
            'Ansiedad fóbica',
            [
                13,
                25,
                47,
                50,
                70,
                75,
                82,
            ],
            .13,
            .31,
        ),
        (
            'Ideación paranoide',
            [
                8,
                18,
                43,
                68,
                76,
                83,
            ],
            .34,
            .44,
        ),
        (
            'Psicoticismo',
            [
                7,
                16,
                35,
                62,
                77,
                84,
                85,
                87,
                88,
                90,
            ],
            .14,
            .25,
        ),
    ]

    mapa = _mapa(respuestas)
    detalle = {}
    elevadas = []

    for nombre, items, media, ds in escalas:
        valor = (
            float(
                sum(
                    mapa.get(i, 0)
                    for i in items
                )
            )
            / len(items)
        )

        nivel = (
            'Elevado'
            if valor >= media + ds
            else (
                'Leve'
                if valor >= media
                else 'Normal'
            )
        )

        detalle[nombre] = {
            'media': round(valor, 2),
            'nivel': nivel,
            'corte': round(media + ds, 2),
        }

        if nivel == 'Elevado':
            elevadas.append(nombre)

    isg = (
        float(
            sum(
                mapa.get(i, 0)
                for i in range(1, 91)
            )
        )
        / 90
    )

    nivel = (
        'Elevado'
        if isg >= .62
        else (
            'Leve'
            if isg >= .31
            else 'Normal'
        )
    )

    detalle['ISG'] = {
        'puntaje': round(isg, 3),
        'nivel': nivel,
    }

    texto = (
        ', '.join(elevadas)
        if elevadas
        else 'ninguna escala elevada'
    )

    return {
        'puntaje_total': Decimal(str(round(isg, 3))),
        'interpretacion': (
            f'Índice de Severidad Global: {isg:.3f} '
            f'({nivel}); {texto}.'
        ),
        'detalle': detalle,
    }


def _calcular_dass21(respuestas, contexto=None):
    mapa = _mapa(respuestas)

    escalas = [
        (
            'Depresión',
            [
                3,
                5,
                10,
                13,
                16,
                17,
                21,
            ],
            [
                4,
                6,
                10,
                13,
            ],
        ),
        (
            'Ansiedad',
            [
                2,
                4,
                7,
                9,
                15,
                19,
                20,
            ],
            [
                3,
                4,
                7,
                9,
            ],
        ),
        (
            'Estrés',
            [
                1,
                6,
                8,
                11,
                12,
                14,
                18,
            ],
            [
                7,
                9,
                12,
                16,
            ],
        ),
    ]

    nombres = [
        'Normal',
        'Leve',
        'Moderada',
        'Severa',
        'Extremadamente severa',
    ]

    detalle = {}
    total = Decimal('0')

    for nombre, items, cortes in escalas:
        suma = sum(
            mapa.get(i, 0)
            for i in items
        )

        nivel = next(
            (
                nombres[i]
                for i, corte in enumerate(cortes)
                if suma <= corte
            ),
            nombres[-1],
        )

        detalle[nombre] = {
            'puntaje': int(suma),
            'nivel': nivel,
        }

        total += suma

    return {
        'puntaje_total': total,
        'interpretacion': ' · '.join(
            f'{n}: {d["puntaje"]} ({d["nivel"]})'
            for n, d in detalle.items()
        ),
        'detalle': detalle,
    }


def _calcular_tds(respuestas, contexto=None):
    factores = [
        (
            'Somnolencia excesiva diurna',
            [
                1,
                2,
                3,
                4,
                5,
            ],
        ),
        (
            'Insomnio inicial',
            [
                10,
                11,
                12,
            ],
        ),
        (
            'Insomnio intermedio',
            [
                9,
                13,
            ],
        ),
        (
            'Insomnio terminal',
            [
                6,
                7,
            ],
        ),
        (
            'Apnea obstructiva',
            [
                14,
                15,
                16,
            ],
        ),
        (
            'Parálisis del dormir',
            [
                17,
                30,
            ],
        ),
        (
            'Enuresis',
            [
                18,
            ],
        ),
        (
            'Bruxismo',
            [
                19,
            ],
        ),
        (
            'Sonambulismo',
            [
                20,
                21,
            ],
        ),
        (
            'Somniloquio',
            [
                22,
            ],
        ),
        (
            'Ronquido',
            [
                23,
                24,
            ],
        ),
        (
            'Piernas inquietas',
            [
                25,
                26,
            ],
        ),
        (
            'Pesadillas',
            [
                27,
            ],
        ),
        (
            'Uso de medicamentos hipnóticos',
            [
                28,
            ],
        ),
        (
            'Uso de medicamentos estimulantes',
            [
                29,
            ],
        ),
    ]

    mapa = _mapa(respuestas)
    detalle = {}
    altos = []

    for nombre, items in factores:
        suma = sum(
            mapa.get(i, 0)
            for i in items
        )

        p = float(suma) / (4 * len(items))

        nivel = (
            'Nulo'
            if not p
            else (
                'Bajo'
                if p <= .25
                else (
                    'Medio'
                    if p <= .5
                    else (
                        'Alto'
                        if p <= .75
                        else 'Muy alto'
                    )
                )
            )
        )

        detalle[nombre] = {
            'puntaje': int(suma),
            'nivel': nivel,
        }

        if nivel in (
            'Alto',
            'Muy alto',
        ):
            altos.append(nombre)

    return {
        'puntaje_total': sum(
            mapa.get(i, 0)
            for i in range(1, 31)
        ),
        'interpretacion': (
            'Factores altos: ' + ', '.join(altos)
            if altos
            else 'Sin factores de alteración del sueño altos.'
        ),
        'detalle': detalle,
    }


def _calcular_tci(respuestas, contexto=None):
    invertidos = [
        [
            31,
            41,
            61,
            91,
        ],
        [
            22,
            32,
            52,
            92,
        ],
        [
            43,
            83,
            93,
        ],
        [
            4,
            14,
            44,
            54,
            64,
            74,
            94,
        ],
        [
            5,
            15,
            25,
            35,
            45,
            65,
            85,
            95,
        ],
        [
            16,
            36,
            56,
            86,
        ],
        [
            17,
            37,
            57,
            77,
            87,
            97,
        ],
        [
            48,
            58,
            68,
            88,
            98,
        ],
        [
            29,
            39,
            59,
            99,
        ],
        [
            20,
            30,
            40,
            60,
        ],
    ]

    mapa = {
        k: int(v)
        for k, v in _mapa(respuestas).items()
    }

    detalle = {}
    total = 0

    for indice, invertidos_idea in enumerate(
        invertidos,
        1,
    ):
        suma = sum(
            (
                1 - mapa.get(
                    indice + 10 * j,
                    0,
                )
                if indice + 10 * j in invertidos_idea
                else mapa.get(
                    indice + 10 * j,
                    0,
                )
            )
            for j in range(10)
        )

        nivel = (
            'Limitante en muchas áreas'
            if suma >= 7
            else (
                'Limitante en determinadas circunstancias'
                if suma >= 5
                else 'No significativa'
            )
        )

        detalle[f'Idea {indice}'] = {
            'puntaje': suma,
            'nivel': nivel,
        }

        total += suma

    return {
        'puntaje_total': Decimal(total),
        'interpretacion': (
            'Ideas autolimitadoras evaluadas; '
            'revise el detalle por escala.'
        ),
        'detalle': detalle,
    }


def _calcular_raven(respuestas, contexto=None):
    contexto = contexto or {}
    fecha = contexto.get('fecha_nacimiento')
    hoy = __import__('datetime').date.today()
    edad = (hoy - fecha).days // 365 if fecha else 25

    total = sum(
        1
        for r in respuestas
        if any(
            str(o.get('valor')) == str(r.valor)
            and o.get('correcta')
            for o in (r.pregunta.opciones or [])
        )
    )

    grado = (
        'I'
        if total >= 56
        else (
            'II'
            if total >= 50
            else (
                'III'
                if total >= 39
                else (
                    'IV'
                    if total >= 30
                    else 'V'
                )
            )
        )
    )

    return {
        'puntaje_total': Decimal(total),
        'interpretacion': (
            f'Raven: {total}/60; '
            f'edad {edad}; grado {grado}.'
        ),
        'detalle': {
            'Puntaje bruto': total,
            'Edad utilizada': edad,
            'Grado': grado,
        },
    }


def _calcular_isra(respuestas, contexto=None):
    mapa = _mapa(respuestas)

    c = sum(
        mapa.get(i, 0)
        for i in range(1, 65)
    )

    f = (
        sum(
            mapa.get(i, 0)
            for i in range(65, 188)
        )
        / 2
    )

    m = sum(
        mapa.get(i, 0)
        for i in range(188, 252)
    )

    total = c + f + m
    sexo = (contexto or {}).get('sexo', '')

    return {
        'puntaje_total': total,
        'interpretacion': (
            f'ISRA: ansiedad total PD {total}; '
            f'baremo pendiente de sexo: '
            f'{sexo or "no especificado"}.'
        ),
        'detalle': {
            'Cognitiva': c,
            'Fisiológica': f,
            'Motora': m,
            'Total': total,
            'Sexo': sexo,
        },
    }


def _calcular_allport(respuestas, contexto=None):
    """Conserva el puntaje y ranking de valores para cuestionarios Allport cargados.

    Los ítems deben usar opciones numéricas; la definición del instrumento incluye
    la codificación de cada escala, por lo que el detalle queda disponible para
    revisión y futuras normas específicas de cada plantilla.
    """

    mapa = _mapa(respuestas)
    total = sum(mapa.values())
    respondidas = len(mapa)

    return {
        'puntaje_total': total,
        'interpretacion': (
            f'Allport: {respondidas} reactivos calificados. '
            'La interpretación se presenta conforme a la '
            'plantilla de valores configurada.'
        ),
        'detalle': {
            'Puntaje acumulado': total,
            'Reactivos respondidos': respondidas,
        },
    }


_CALCULADORAS.update(
    {
        'scl90': _calcular_scl90,
        'allport': _calcular_allport,
        'dass-21': _calcular_dass21,
        'dass-21-adolescentes': _calcular_dass21_adolescentes,
        'rse-autoestima': _calcular_rosenberg_orientativa,
        'scid-ii-adolescentes': _calcular_scid2_adolescentes,
        'ersp-plutchik-adolescentes': _calcular_plutchik_adolescentes,
        'tds': _calcular_tds,
        'tci': _calcular_tci,
        'raven': _calcular_raven,
        'isra': _calcular_isra,
    }
)


def calcular_resultado(
    instrumento,
    respuestas,
    contexto=None,
):
    """Calcula sin conocer ni persistir modelos del modulo consumidor."""

    contexto = contexto or {}
    revision = obtener_revision_calculadora(instrumento)
    if not revision['puede_ejecutarse']:
        return None
    validacion_edad = validar_variante_por_edad(instrumento, contexto)
    if instrumento.clave in _VARIANTE_POR_CLAVE_EXACTA and not validacion_edad['aplicable']:
        return None

    calculadora = _CALCULADORAS.get(
        clave_calculadora(
            instrumento.clave
        )
    )

    resultado = (
        calculadora(
            respuestas,
            contexto,
        )
        if calculadora
        else None
    )

    if resultado is None:
        return None

    if instrumento.clave == 'scid-ii-adolescentes':
        revision.update(
            {
                'requiere_revision_profesional': True,
                'estado_revision': 'pendiente_revision_profesional',
                'advertencia_larga': ADVERTENCIA_SCID2_ADOLESCENTES,
                'advertencia_corta': ADVERTENCIA_CORTA_SCID2_ADOLESCENTES,
            }
        )
    elif instrumento.clave == 'ersp-plutchik-adolescentes':
        revision.update(
            {
                'requiere_revision_profesional': True,
                'estado_revision': 'pendiente_revision_profesional',
                'advertencia_larga': ADVERTENCIA_PLUTCHIK_ADOLESCENTES,
                'advertencia_corta': ADVERTENCIA_PLUTCHIK_ADOLESCENTES,
            }
        )
    if revision['snapshot']:
        revision['snapshot'].update(
            {
                'requiere_revision_profesional': revision[
                    'requiere_revision_profesional'
                ],
                'estado_revision': revision['estado_revision'],
                'advertencia_larga': revision['advertencia_larga'],
                'advertencia_corta': revision['advertencia_corta'],
            }
        )
    resultado['detalle']['trazabilidad_calculadora'] = {
        **(revision['snapshot'] or {}),
        'clave_instrumento': instrumento.clave,
        'version_instrumento': instrumento.version,
        'estado_revision': revision['estado_revision'],
        'validacion_edad': validacion_edad,
    }
    resultado.update(
        {
            'revision_calculadora': revision['snapshot'],
            'estado_revision': revision['estado_revision'],
            'requiere_revision_profesional': revision[
                'requiere_revision_profesional'
            ],
            'advertencia_larga': revision['advertencia_larga'],
            'advertencia_corta': revision['advertencia_corta'],
        }
    )
    return resultado
