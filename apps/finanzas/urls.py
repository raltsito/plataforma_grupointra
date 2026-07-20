from django.urls import path
from . import views

app_name = 'finanzas'

urlpatterns = [
    path('', views.tablero_view, name='tablero'),
    path('ingresos/', views.ingresos_view, name='ingresos'),
    path('honorarios/', views.honorarios_view, name='honorarios'),
    path('nomina/', views.nomina_view, name='nomina'),
    path('donativos/', views.donativos_view, name='donativos'),
    path('reportes/', views.reportes_view, name='reportes'),
]
