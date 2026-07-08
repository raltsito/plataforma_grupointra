from django.db import migrations


def crear_grupo_finanzas(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name='Finanzas')


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_grupo_finanzas),
    ]
