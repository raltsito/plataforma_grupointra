from django.urls import path

from . import views


app_name = 'portafolio'

urlpatterns = [
    path(
        '',
        views.dashboard_view,
        name='dashboard',
    ),
    path(
        'instrumentos/',
        views.instrumentos_view,
        name='instrumentos',
    ),
    path(
        'instrumentos/<int:instrumento_id>/importar-preguntas/',
        views.importar_preguntas_view,
        name='importar_preguntas',
    ),
    path(
        'instrumentos/<int:instrumento_id>/preguntas/',
        views.preguntas_view,
        name='preguntas',
    ),
    path(
        'preguntas/<int:pregunta_id>/editar/',
        views.pregunta_editar_view,
        name='pregunta_editar',
    ),
    path(
        'preguntas/<int:pregunta_id>/eliminar/',
        views.pregunta_eliminar_view,
        name='pregunta_eliminar',
    ),
    path(
        'documentos/',
        views.documentos_view,
        name='documentos',
    ),
    path(
        'documentos/<int:documento_id>/descargar/',
        views.documento_descargar_view,
        name='documento_descargar',
    ),
    path(
        'plantillas-pdf/',
        views.plantillas_view,
        name='plantillas',
    ),
    path(
        'reportes/',
        views.reportes_view,
        name='reportes',
    ),
    path(
        'recursos/',
        views.recursos_view,
        name='recursos',
    ),
    path(
        '<str:tipo>/<int:item_id>/editar/',
        views.editar_view,
        name='editar',
    ),
    path(
        '<str:tipo>/<int:item_id>/eliminar/',
        views.eliminar_view,
        name='eliminar',
    ),
]
