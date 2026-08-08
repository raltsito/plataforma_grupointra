from apps.portafolio.services_entrevista import CLAVE_ENTREVISTA


CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO = frozenset({CLAVE_ENTREVISTA})


def excluir_instrumentos_de_flujo_interno(queryset):
    return queryset.exclude(
        clave__in=CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO,
    )


def es_instrumento_de_flujo_interno(instrumento):
    return instrumento.clave in CLAVES_INSTRUMENTOS_DE_FLUJO_INTERNO
