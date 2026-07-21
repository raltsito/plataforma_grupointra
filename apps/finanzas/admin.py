from django.contrib import admin

from .models import (
    CitaRecepcion, ConceptoNominaAcademia, Donativo, Egreso, Honorario,
    Ingreso, Maestro, NominaAcademia, Tabulador, TabuladorAcademia,
)


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
    list_display = ('concepto', 'categoria', 'persona', 'monto', 'estatus', 'metodo_pago', 'fecha')
    list_filter = ('categoria', 'estatus', 'fecha')
    search_fields = ('concepto', 'persona', 'referencia_externa')
    readonly_fields = ('referencia_externa',)


@admin.register(Honorario)
class HonorarioAdmin(admin.ModelAdmin):
    list_display = ('terapeuta', 'tabulador', 'periodo_mes', 'periodo_anio', 'num_pacientes', 'bono', 'total', 'estatus')
    list_filter = ('estatus', 'periodo_anio', 'periodo_mes')
    readonly_fields = ('bono', 'total')


@admin.register(CitaRecepcion)
class CitaRecepcionAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'hora', 'paciente', 'terapeuta', 'servicio', 'estatus', 'metodo_pago', 'costo', 'ingreso')
    list_filter = ('estatus', 'metodo_pago', 'division', 'fecha')
    search_fields = ('paciente', 'terapeuta')
    readonly_fields = ('ingreso',)


@admin.register(Donativo)
class DonativoAdmin(admin.ModelAdmin):
    list_display = ('donante_nombre', 'tipo', 'monto', 'folio_cfdi', 'estatus_cfdi', 'fecha')
    list_filter = ('tipo', 'estatus_cfdi', 'fecha')
    search_fields = ('donante_nombre', 'donante_rfc', 'folio_cfdi')


@admin.register(Maestro)
class MaestroAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo')
    list_filter = ('activo',)
    search_fields = ('nombre',)


@admin.register(TabuladorAcademia)
class TabuladorAcademiaAdmin(admin.ModelAdmin):
    list_display = ('concepto', 'monto_unidad', 'vigente_desde')
    list_filter = ('concepto',)
    ordering = ('-vigente_desde',)


class ConceptoNominaAcademiaInline(admin.TabularInline):
    model = ConceptoNominaAcademia
    extra = 0
    readonly_fields = ('tabulador', 'tarifa', 'subtotal')


@admin.register(NominaAcademia)
class NominaAcademiaAdmin(admin.ModelAdmin):
    list_display = ('maestro', 'periodo_mes', 'periodo_anio', 'metodo_pago', 'estatus', 'total')
    list_filter = ('estatus', 'periodo_anio', 'periodo_mes')
    readonly_fields = ('total',)
    inlines = [ConceptoNominaAcademiaInline]
