from django.urls import path
from . import views

app_name = 'finanzas'

urlpatterns = [
    path('', views.tablero_view, name='tablero'),
    path('ingresos/', views.ingresos_view, name='ingresos'),
    path('honorarios/', views.honorarios_view, name='honorarios'),
    path('nomina/', views.nomina_view, name='nomina'),
    path('nomina/descargar/', views.nomina_descargar_view, name='nomina_descargar'),
    path('reporte-recepcion/', views.reporte_recepcion_view, name='reporte_recepcion'),
    path('nomina-academia/', views.nomina_academia_view, name='nomina_academia'),
    path('nomina-academia/<int:nomina_id>/descargar/', views.nomina_academia_descargar_view, name='nomina_academia_descargar'),
    path('donativos/', views.donativos_view, name='donativos'),
    path('reportes/', views.reportes_view, name='reportes'),
    path('exportar/', views.exportar_view, name='exportar'),
]
