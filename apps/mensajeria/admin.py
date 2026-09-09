from django.contrib import admin

from .models import Baja, Envio, SistemaSuscrito, UltimaInteraccion


@admin.register(Envio)
class EnvioAdmin(admin.ModelAdmin):
    list_display = (
        'envio_id', 'destinatario', 'plantilla', 'estado',
        'origen_sistema', 'origen_entidad', 'origen_id', 'creado_en',
    )
    list_filter = ('estado', 'origen_sistema', 'plantilla')
    search_fields = ('envio_id', 'destinatario', 'wa_message_id', 'idempotency_key')
    readonly_fields = [field.name for field in Envio._meta.fields]


@admin.register(Baja)
class BajaAdmin(admin.ModelAdmin):
    list_display = ('destinatario', 'origen_sistema', 'creado_en')
    search_fields = ('destinatario',)


@admin.register(UltimaInteraccion)
class UltimaInteraccionAdmin(admin.ModelAdmin):
    list_display = ('destinatario', 'ultimo_mensaje_entrante_en')
    search_fields = ('destinatario',)


@admin.register(SistemaSuscrito)
class SistemaSuscritoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo', 'webhook_url')
    search_fields = ('nombre',)
