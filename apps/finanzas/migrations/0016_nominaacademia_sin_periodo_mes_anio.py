from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finanzas', '0015_nominaacademia_tipo_fechas'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='nominaacademia',
            unique_together={('maestro', 'tipo', 'fecha_inicio', 'fecha_fin')},
        ),
        migrations.RemoveField(
            model_name='nominaacademia',
            name='periodo_anio',
        ),
        migrations.RemoveField(
            model_name='nominaacademia',
            name='periodo_mes',
        ),
        migrations.AlterModelOptions(
            name='nominaacademia',
            options={'ordering': ['-fecha_fin', 'tipo'], 'verbose_name': 'Nómina Academia', 'verbose_name_plural': 'Nóminas Academia'},
        ),
    ]