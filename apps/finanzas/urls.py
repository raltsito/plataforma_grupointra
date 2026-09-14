from django.urls import path
from . import views

app_name = 'finanzas'

urlpatterns = [
    path('', views.tablero_view, name='tablero'),
    path('ingresos/', views.ingresos_view, name='ingresos'),
    path('egresos/', views.egresos_view, name='egresos'),
    path('nomina/', views.nomina_view, name='nomina'),
    path('nomina/linea/<int:linea_id>/', views.nomina_linea_view, name='nomina_linea'),
    path('nomina/<int:nomina_id>/descargar/', views.nomina_descargar_view, name='nomina_descargar'),
    path('reporte-recepcion/', views.reporte_recepcion_view, name='reporte_recepcion'),
    path('nomina-academia/', views.nomina_academia_view, name='nomina_academia'),
    path('nomina-academia/<int:nomina_id>/descargar/', views.nomina_academia_descargar_view, name='nomina_academia_descargar'),
    path('nomina-academia/periodo/<str:inicio>/<str:fin>/descargar/', views.nomina_academia_periodo_descargar_view, name='nomina_academia_periodo_descargar'),
    path('ajustes/', views.ajustes_view, name='ajustes'),
    path('bitacora/', views.bitacora_view, name='bitacora'),
    path('configuracion/', views.configuracion_view, name='configuracion'),
    path('donativos/', views.donativos_view, name='donativos'),
    path('reportes/', views.reportes_view, name='reportes'),
    path('reportes/estado-resultados/', views.reporte_estado_resultados_view, name='reporte_estado_resultados'),
    path('reportes/flujo-efectivo/', views.reporte_flujo_efectivo_view, name='reporte_flujo_efectivo'),
    path('reportes/donativos/', views.reporte_donativos_view, name='reporte_donativos'),
    path('exportar/', views.exportar_view, name='exportar'),
]
