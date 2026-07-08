# Catálogo de módulos del portal (RF-20: catálogos administrables).
# Por ahora es una lista en código, no editable desde /admin/ todavía —
# cuando se necesite administrarlo sin tocar código, este es el lugar
# natural para convertirlo en modelo.
#
# IMPORTANTE: el orden y las claves ('key') deben coincidir con el arreglo
# JS de apps/core/static/core/js/login.js (MODULOS_LOGIN), porque la
# animación de login mide la posición real del sidebar del dashboard para
# "aterrizar" ahí — ambos deben listar los mismos módulos en el mismo orden.

MODULOS = [
    {
        'key': 'agenda', 'nombre': 'Agenda Intra',
        'descripcion': 'Gestión de citas y disponibilidad.',
        'accent': '#2D5F8B', 'tint': '#E9F0F7',
        'construido': False, 'grupos': (),
    },
    {
        'key': 'finanzas', 'nombre': 'Sistema de Finanzas',
        'descripcion': 'Pagos, cobros y reportes financieros.',
        'accent': '#C9A24B', 'tint': '#F6EFDD',
        'construido': True, 'grupos': ('Finanzas', 'Dirección', 'Sistemas'),
        'url_name': 'finanzas:tablero',
    },
    {
        'key': 'orbitaedu', 'nombre': 'OrbitaEdu',
        'descripcion': 'Plataforma educativa institucional.',
        'accent': '#2A9D9D', 'tint': '#E2F1F1',
        'construido': False, 'grupos': (),
    },
    {
        'key': 'orbitacontrol', 'nombre': 'OrbitaControl',
        'descripcion': 'Administración y gestión escolar.',
        'accent': '#1B2C4F', 'tint': '#E8EBF2',
        'construido': False, 'grupos': (),
    },
    {
        'key': 'rh', 'nombre': 'Recursos Humanos',
        'descripcion': 'Expedientes, incidencias y nómina.',
        'accent': '#2D5F8B', 'tint': '#E9F0F7',
        'construido': False, 'grupos': (),
    },
    {
        'key': 'capacitacion', 'nombre': 'Capacitación y Cumplimiento',
        'descripcion': 'Seguimiento NOM-035 y cursos obligatorios.',
        'accent': '#C9A24B', 'tint': '#F6EFDD',
        'construido': False, 'grupos': (),
    },
    {
        'key': 'soporte', 'nombre': 'Mesa de Ayuda',
        'descripcion': 'Soporte técnico y reporte de incidencias.',
        'accent': '#2A9D9D', 'tint': '#E2F1F1',
        'construido': False, 'grupos': (),
    },
    {
        'key': 'comunicados', 'nombre': 'Comunicados Internos',
        'descripcion': 'Avisos, circulares y documentos.',
        'accent': '#1B2C4F', 'tint': '#E8EBF2',
        'construido': False, 'grupos': (),
    },
]


def modulos_para(user):
    """Arma la lista de módulos con su disponibilidad real para `user`:
    construido=False -> 'proximamente' (nadie lo tiene, no existe todavía).
    construido=True pero sin pertenecer a los grupos requeridos -> 'sin_permiso'.
    """
    from django.urls import reverse

    from apps.core.permisos.grupos import usuario_pertenece_a

    resultado = []
    for m in MODULOS:
        disponible = m['construido'] and (not m['grupos'] or usuario_pertenece_a(user, *m['grupos']))
        if not m['construido']:
            motivo_bloqueo = 'proximamente'
        elif not disponible:
            motivo_bloqueo = 'sin_permiso'
        else:
            motivo_bloqueo = None
        resultado.append({
            **m,
            'disponible': disponible,
            'motivo_bloqueo': motivo_bloqueo,
            'url': reverse(m['url_name']) if disponible and m.get('url_name') else '',
        })
    return resultado
