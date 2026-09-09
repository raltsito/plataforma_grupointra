from django.urls import path

from . import views

app_name = 'mensajeria'

urlpatterns = [
    path('envios/', views.envios_view, name='envios'),
    path('envios/<str:envio_id>/', views.envio_detalle_view, name='envio_detalle'),
    path('bajas/', views.bajas_view, name='bajas'),
    path('webhook-meta/', views.webhook_meta_view, name='webhook_meta'),
]
