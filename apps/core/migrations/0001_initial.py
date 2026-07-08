from django.db import migrations

from apps.core.permisos.grupos import crear_grupos_sistema_intra


class Migration(migrations.Migration):

    dependencies = [

    ]

    operations = [
        migrations.RunPython(crear_grupos_sistema_intra),
    ]
