from django.contrib import admin

from .models import Donativo, Egreso, Honorario, Ingreso, Tabulador


@admin.register(Tabulador)
class TabuladorAdmin(admin.ModelAdmin):
    list_display = ('categoria', 'pago_base', 'umbral_pacientes_semana', 'monto_bono', 'vigente_desde')
    list_filter = ('categoria',)
    ordering = ('-vigente_desde',)


@admin.register(Ingreso)
class IngresoAdmin(admin.ModelAdmin):
    list_display = ('concepto', 'terapeuta', 'persona', 'monto', 'estatus', 'fecha')
    list_filter = ('concepto', 'estatus', 'fecha')
    search_fields = ('persona',)


@admin.register(Egreso)
class EgresoAdmin(admin.ModelAdmin):
    list_display = ('concepto', 'categoria', 'monto', 'fecha')
    list_filter = ('categoria', 'fecha')
    search_fields = ('concepto',)


@admin.register(Honorario)
class HonorarioAdmin(admin.ModelAdmin):
    list_display = ('terapeuta', 'tabulador', 'periodo_mes', 'periodo_anio', 'num_pacientes', 'bono', 'total', 'estatus')
    list_filter = ('estatus', 'periodo_anio', 'periodo_mes')
    readonly_fields = ('bono', 'total')


@admin.register(Donativo)
class DonativoAdmin(admin.ModelAdmin):
    list_display = ('donante_nombre', 'tipo', 'monto', 'folio_cfdi', 'estatus_cfdi', 'fecha')
    list_filter = ('tipo', 'estatus_cfdi', 'fecha')
    search_fields = ('donante_nombre', 'donante_rfc', 'folio_cfdi')
