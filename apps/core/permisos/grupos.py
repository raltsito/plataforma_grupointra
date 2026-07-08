# Lógica de grupos y permisos (RBAC) compartida por todas las apps del portal.


def crear_grupos_sistema_intra(apps, schema_editor):
    """Crea los grupos base del portal. Usada como RunPython en la migración
    inicial de core; se mantiene aquí también como copia reutilizable fuera
    de una migración (por ejemplo desde un management command o los tests)."""
    Group = apps.get_model('auth', 'Group')
    roles = ['Terapeutas', 'Recepción', 'Administración', 'Dirección', 'Sistemas']

    for nombre_rol in roles:
        Group.objects.get_or_create(name=nombre_rol)


def usuario_pertenece_a(user, *nombres_grupo):
    """Verdadero si el usuario es superusuario o pertenece a alguno de los
    grupos indicados. Pensado para reutilizarse en el control de acceso de
    cualquier módulo del portal (ej. apps/finanzas)."""
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=nombres_grupo).exists()
