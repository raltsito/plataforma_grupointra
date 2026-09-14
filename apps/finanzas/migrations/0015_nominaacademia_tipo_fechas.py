import calendar
from datetime import date

from django.db import migrations, models


def backfill_fechas(apps, schema_editor):
    NominaAcademia = apps.get_model('finanzas', 'NominaAcademia')
    for nomina in NominaAcademia.objects.all():
        ultimo = calendar.monthrange(nomina.periodo_anio, nomina.periodo_mes)[1]
        nomina.fecha_inicio = date(nomina.periodo_anio, nomina.periodo_mes, 1)
        nomina.fecha_fin = date(nomina.periodo_anio, nomina.periodo_mes, ultimo)
        nomina.save(update_fields=['fecha_inicio', 'fecha_fin'])


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0014_alter_maestro_options_maestro_tipo'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='nominaacademia',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='nominaacademia',
            name='tipo',
            field=models.CharField(choices=[('mensual', 'Mensual'), ('quincenal', 'Quincenal')], default='mensual', max_length=20),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='nominaacademia',
            name='fecha_inicio',
            field=models.DateField(default=date(2000, 1, 1)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='nominaacademia',
            name='fecha_fin',
            field=models.DateField(default=date(2000, 1, 1)),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_fechas, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name='nominaacademia',
            unique_together={('maestro', 'tipo', 'periodo_mes', 'periodo_anio')},
        ),
    ]
