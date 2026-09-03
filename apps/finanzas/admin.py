from django.contrib import admin

from .models import (
    CategoriaEgreso, CitaRecepcion, ConceptoIngreso, ConceptoNominaAcademia,
    Donativo, Egreso, Ingreso, LineaNominaSemanal, Maestro, NominaAcademia,
    NominaSemanal, TabuladorAcademia,
)


@admin.register(Ingreso)
class IngresoAdmin(admin.ModelAdmin):
    list_display = ('concepto', 'unidad', 'terapeuta', 'persona', 'monto', 'estatus', 'fecha')
    list_filter = ('unidad', 'concepto', 'estatus', 'fecha')
    search_fields = ('persona',)


@admin.register(Egreso)
class EgresoAdmin(admin.ModelAdmin):
    list_display = ('concepto', 'categoria', 'unidad', 'persona', 'monto', 'estatus', 'metodo_pago', 'fecha')
    list_filter = ('unidad', 'categoria', 'estatus', 'fecha')
    search_fields = ('concepto', 'persona', 'referencia_externa')
    readonly_fields = ('referencia_externa',)


class LineaNominaSemanalInline(admin.TabularInline):
    model = LineaNominaSemanal
    extra = 0
    fields = (
        'persona', 'tipo_persona', 'concepto', 'citas_atendidas', 'pago_base',
        'vale_gasolina', 'extras', 'metodo_pago', 'estatus_pago', 'sellada',
    )
    readonly_fields = ('sellada',)


@admin.register(NominaSemanal)
class NominaSemanalAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'fecha_inicio', 'fecha_fin', 'estado', 'fecha_pago', 'usuario_genera')
    list_filter = ('tipo', 'estado', 'fecha_fin')
    readonly_fields = ('sellada_en', 'creado_en')
    inlines = [LineaNominaSemanalInline]


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
    list_display = ('nombre', 'tipo', 'activo')
    list_filter = ('activo', 'tipo')
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


@admin.register(ConceptoIngreso)
class ConceptoIngresoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo')
    list_filter = ('activo',)


@admin.register(CategoriaEgreso)
class CategoriaEgresoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo')
    list_filter = ('activo',)
