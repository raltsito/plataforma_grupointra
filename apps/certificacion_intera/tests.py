from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from datetime import date, timedelta
from io import BytesIO
import re
from unittest.mock import patch
from urllib import error
from .models import Escuela
from .models import (
    AplicacionInstrumento,
    AplicacionPublica,
    Canalizacion,
    Consejeria,
    ConfiguracionInstrumento,
    Participante,
    ProcesoCertificacion,
    RespuestaInstrumento,
    ResultadoInstrumento,
    EntrevistaSeguimiento,
    BitacoraProceso,
    SolicitudAtencion,
    EntrevistaUnoAUno,
    RespuestaEntrevistaUnoAUno,
)
from apps.portafolio.models import (
    CalculadoraInstrumento,
    CategoriaDocumento,
    Documento,
    ImportacionInstrumento,
    Instrumento,
    PreguntaInstrumento,
    RevisionInstrumento,
)
from apps.portafolio.services_entrevista import CLAVE_ENTREVISTA
from apps.portafolio.services_calificacion import (
    ADVERTENCIA_RESULTADO_ORIENTATIVO,
)
from . import consultorio_web

class FakeHttpResponse:

    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body

def crear_instrumento_bateria(
    clave,
    nombre,
    reactivos,
    estado_calculadora,
    variante='Adolescentes',
):
    categoria, _ = CategoriaDocumento.objects.get_or_create(nombre='Pruebas de batería')
    documento = Documento.objects.create(
        nombre=f'Fuente {clave}',
        categoria=categoria,
        archivo=f'portafolio/documentos/{clave}.xlsx',
    )
    instrumento = Instrumento.objects.create(
        nombre=nombre,
        clave=clave,
        version='1.0',
    )
    PreguntaInstrumento.objects.bulk_create(
        [
            PreguntaInstrumento(
                instrumento=instrumento,
                orden=orden,
                texto=f'Reactivo {orden}',
                opciones=[{'valor': '1', 'etiqueta': 'Sí'}],
            )
            for orden in range(1, reactivos + 1)
        ],
    )
    CalculadoraInstrumento.objects.create(
        instrumento=instrumento,
        clave=f'calc-{clave}',
        version_regla='1.0',
        estado=estado_calculadora,
        definicion={},
        huella_contenido=(clave * 64)[:64],
    )
    ImportacionInstrumento.objects.create(
        instrumento=instrumento,
        documento=documento,
        huella_contenido=(clave * 64)[:64],
        metadatos={
            'Variante': variante,
            'Número de reactivos': reactivos,
        },
    )
    return instrumento

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class EscuelaRevisionYFichaTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='escuelas-prueba',
            password='prueba',
        )
        self.user.groups.add(
            Group.objects.get_or_create(name='Certificación')[0],
        )
        self.client.force_login(self.user)
        self.escuela = Escuela.objects.create(
            nombre='Colegio Central',
            director='Directora de prueba',
            cantidad_total_alumnos=80,
            estado='Coahuila',
            municipio='Saltillo',
            correo='contacto@colegio.test',
            telefono='844-111-2222',
        )

    def _post_coincidencia(self):
        return self.client.post(
            reverse('certificacion_intera:escuela_crear'),
            {
                'nombre': '  colegio   central ',
                'director': 'Otra dirección',
                'cantidad_total_alumnos': 20,
                'estado': 'Coahuila',
                'municipio': 'Saltillo',
                'correo': 'CONTACTO@COLEGIO.TEST',
                'telefono': '(844) 111 2222',
            },
        )

    def test_revision_temporal_no_crea_y_confirmacion_es_unica(self):
        response = self._post_coincidencia()
        self.assertEqual(Escuela.objects.count(), 1)
        self.assertContains(
            response,
            'Encontramos escuelas que podrían coincidir',
        )
        token = response.context['revision_token']
        clave = f'intera_revision_escuela_{token}'
        self.assertIn(clave, self.client.session)
        confirmado = self.client.post(
            reverse('certificacion_intera:escuela_confirmar'),
            {'revision_token': token},
        )
        self.assertEqual(Escuela.objects.count(), 2)
        self.assertNotIn(clave, self.client.session)
        self.assertEqual(confirmado.status_code, 302)
        self.client.post(
            reverse('certificacion_intera:escuela_confirmar'),
            {'revision_token': token},
        )
        self.assertEqual(Escuela.objects.count(), 2)

    def test_revision_ajena_o_expirada_no_crea(self):
        response = self._post_coincidencia()
        token = response.context['revision_token']
        other = Client()
        other.force_login(self.user)
        other.post(
            reverse('certificacion_intera:escuela_confirmar'),
            {'revision_token': token},
        )
        self.assertEqual(Escuela.objects.count(), 1)
        session = self.client.session
        session[f'intera_revision_escuela_{token}']['creado_en'] = 0
        session.save()
        self.client.post(
            reverse('certificacion_intera:escuela_confirmar'),
            {'revision_token': token},
        )
        self.assertEqual(Escuela.objects.count(), 1)

    def test_ficha_tabs_director_y_retorno(self):
        retorno = '/certificacion-intera/escuelas/?q=colegio&page=2'
        for tab in (
            'resumen',
            'datos',
            'contactos',
            'procesos',
            'historial',
        ):
            response = self.client.get(
                reverse(
                    'certificacion_intera:escuela_detalle',
                    args=[self.escuela.id],
                ),
                {'tab': tab, 'return_url': retorno},
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'return_url=')
        resumen = self.client.get(
            reverse(
                'certificacion_intera:escuela_detalle',
                args=[self.escuela.id],
            ),
        )
        self.assertContains(resumen, 'Ficha de la escuela')
        self.assertContains(resumen, 'Directora de prueba')
        self.assertContains(resumen, 'Capacidad estimada')
        self.assertContains(resumen, 'Participantes registrados')

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class DashboardCertificacionInteraTests(TestCase):

    def test_usuario_autorizado_puede_ver_el_dashboard(self):
        usuario = User.objects.create_user(username='certificacion', password='secreto')
        grupo, _ = Group.objects.get_or_create(name='Certificación')
        usuario.groups.add(grupo)
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse('certificacion_intera:dashboard'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(
            respuesta,
            'certificacion_intera/dashboard.html',
        )
        self.assertContains(respuesta, 'Procesos activos')
        self.assertContains(respuesta, 'Trabajo pendiente')

    def test_usuario_sin_grupo_recibe_error_de_permiso(self):
        usuario = User.objects.create_user(username='sin_permiso', password='secreto')
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse('certificacion_intera:dashboard'))
        self.assertEqual(respuesta.status_code, 403)

    def test_usuario_autorizado_puede_registrar_una_escuela(self):
        usuario = User.objects.create_user(username='captura', password='secreto')
        grupo, _ = Group.objects.get_or_create(name='Certificación')
        usuario.groups.add(grupo)
        self.client.force_login(usuario)
        respuesta = self.client.post(
            reverse('certificacion_intera:escuela_crear'),
            {
                'nombre': 'Escuela Ejemplo',
                'director': 'Ana Pérez',
                'cantidad_total_alumnos': 120,
                'estado': 'Ciudad de México',
                'municipio': 'Coyoacán',
            },
        )
        escuela = Escuela.objects.get(nombre='Escuela Ejemplo')
        self.assertRedirects(
            respuesta,
            reverse('certificacion_intera:escuela_detalle', args=[escuela.id]),
        )

    def test_usuario_autorizado_puede_listar_consultar_y_editar_una_escuela(self):
        usuario = User.objects.create_user(username='gestion', password='secreto')
        grupo, _ = Group.objects.get_or_create(name='Certificación')
        usuario.groups.add(grupo)
        escuela = Escuela.objects.create(
            nombre='Instituto Inicial',
            director='Luis Díaz',
            cantidad_total_alumnos=80,
            estado='México',
            municipio='Toluca',
        )
        self.client.force_login(usuario)
        listado = self.client.get(reverse('certificacion_intera:escuelas'))
        expediente = self.client.get(
            reverse('certificacion_intera:escuela_detalle', args=[escuela.id]),
        )
        respuesta = self.client.post(
            reverse('certificacion_intera:escuela_editar', args=[escuela.id]),
            {
                'nombre': 'Instituto Actualizado',
                'director': 'Luis Díaz',
                'cantidad_total_alumnos': 95,
                'estado': 'México',
                'municipio': 'Toluca',
            },
        )
        self.assertContains(listado, 'Instituto Inicial')
        self.assertContains(expediente, 'Luis Díaz')
        self.assertRedirects(
            respuesta,
            reverse('certificacion_intera:escuela_detalle', args=[escuela.id]),
        )
        escuela.refresh_from_db()
        self.assertEqual(escuela.nombre, 'Instituto Actualizado')

    def test_proceso_permite_fecha_de_cierre_vacia_y_no_cierra_antes_de_tiempo(self):
        usuario = User.objects.create_user(username='proceso', password='secreto')
        grupo, _ = Group.objects.get_or_create(name='Certificación')
        usuario.groups.add(grupo)
        escuela = Escuela.objects.create(
            nombre='Escuela proceso',
            director='Dirección',
            cantidad_total_alumnos=30,
            estado='Estado',
            municipio='Municipio',
        )
        instrumento = crear_instrumento_bateria(
            'dass-21-adolescentes',
            'DASS-21',
            21,
            CalculadoraInstrumento.Estado.ORIENTATIVA,
        )
        self.client.force_login(usuario)
        abierto = self.client.post(
            reverse('certificacion_intera:proceso_crear', args=[escuela.id]),
            {
                'ciclo_escolar': '2026-2027',
                'nombre': 'Proceso abierto',
                'fecha_inicio': date.today().isoformat(),
                'fecha_cierre': '',
                'observaciones': '',
                'instrumentos': [instrumento.id],
                f'orden_{instrumento.id}': 1,
            },
        )
        proceso = ProcesoCertificacion.objects.get(nombre='Proceso abierto')
        self.assertRedirects(
            abierto,
            reverse('certificacion_intera:proceso_detalle', args=[proceso.id]),
        )
        self.assertIsNone(proceso.fecha_cierre)
        cerrado = self.client.post(
            reverse('certificacion_intera:proceso_crear', args=[escuela.id]),
            {
                'ciclo_escolar': '2027-2028',
                'nombre': 'Proceso futuro',
                'fecha_inicio': date.today().isoformat(),
                'fecha_cierre': (date.today() + timedelta(days=2)).isoformat(),
                'observaciones': '',
                'instrumentos': [instrumento.id],
                f'orden_{instrumento.id}': 1,
            },
        )
        self.assertEqual(cerrado.status_code, 200)
        self.assertFalse(
            ProcesoCertificacion.objects.filter(nombre='Proceso futuro').exists(),
        )

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class FlujoInteraConPortafolioTests(TestCase):

    def test_el_proceso_consume_instrumentos_y_preguntas_de_portafolio(self):
        escuela = Escuela.objects.create(
            nombre='Escuela',
            director='Dirección',
            cantidad_total_alumnos=1,
            estado='Estado',
            municipio='Municipio',
        )
        proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            fecha_inicio='2026-08-02',
        )
        categoria, _ = CategoriaDocumento.objects.get_or_create(nombre='Instrumento')
        documento = Documento.objects.create(
            nombre='Origen',
            categoria=categoria,
            archivo='portafolio/documentos/origen.xlsx',
        )
        instrumento = Instrumento.objects.create(
            nombre='Instrumento compartido',
            clave='compartido',
            documento_origen=documento,
        )
        pregunta = PreguntaInstrumento.objects.create(
            instrumento=instrumento,
            orden=1,
            texto='Pregunta',
        )
        configuracion = ConfiguracionInstrumento.objects.create(
            proceso=proceso,
            instrumento=instrumento,
        )
        participante = Participante.objects.create(
            proceso=proceso,
            nombre='Participante',
            numero_alumno='001',
        )
        aplicacion = AplicacionInstrumento.objects.create(
            proceso=proceso,
            participante=participante,
            instrumento=instrumento,
        )
        respuesta = RespuestaInstrumento.objects.create(
            aplicacion=aplicacion,
            pregunta=pregunta,
            valor='Sí',
        )
        self.assertEqual(configuracion.instrumento, instrumento)
        self.assertEqual(instrumento.documento_origen, documento)
        self.assertEqual(aplicacion.instrumento, instrumento)
        self.assertEqual(respuesta.pregunta, pregunta)

    def test_panel_del_proceso_expone_operaciones_y_aplicaciones_publicas(self):
        usuario = User.objects.create_user(username='coordinador', password='secreto')
        grupo, _ = Group.objects.get_or_create(name='Certificación')
        usuario.groups.add(grupo)
        escuela = Escuela.objects.create(
            nombre='Escuela panel',
            director='DirecciÃ³n',
            cantidad_total_alumnos=1,
            estado='Estado',
            municipio='Municipio',
        )
        proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='2026-2027',
            fecha_inicio='2026-08-02',
        )
        instrumento = Instrumento.objects.create(nombre='Instrumento panel', clave='panel')
        ConfiguracionInstrumento.objects.create(
            proceso=proceso,
            instrumento=instrumento,
        )
        self.client.force_login(usuario)
        panel = self.client.get(
            reverse('certificacion_intera:proceso_detalle', args=[proceso.id]),
            {'tab': 'bateria'},
        )
        publicas = self.client.get(
            reverse(
                'certificacion_intera:proceso_aplicaciones_publicas',
                args=[proceso.id],
            ),
        )
        bitacora = self.client.get(
            reverse('certificacion_intera:proceso_detalle', args=[proceso.id]),
            {'tab': 'bitacora'},
        )
        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, 'Batería y aplicación')
        self.assertContains(panel, 'Instrumento panel')
        self.assertContains(publicas, 'Abrir enlace')
        self.assertEqual(bitacora.status_code, 200)
        self.assertContains(bitacora, 'Bitácora')
        self.assertContains(bitacora, 'Consultar bitácora')

    def test_enlace_publico_usa_portafolio_y_persiste_una_respuesta(self):
        usuario = User.objects.create_user(
            username='coordinadora-publica',
            password='secreto',
        )
        grupo, _ = Group.objects.get_or_create(name='Certificación')
        usuario.groups.add(grupo)
        categoria = CategoriaDocumento.objects.create(nombre='Instrumentos públicos')
        documento = Documento.objects.create(
            nombre='Cuestionario origen',
            categoria=categoria,
            archivo='portafolio/documentos/cuestionario.xlsx',
        )
        instrumento = Instrumento.objects.create(
            nombre='Bienestar escolar',
            clave='bienestar-escolar',
            documento_origen=documento,
        )
        pregunta = PreguntaInstrumento.objects.create(
            instrumento=instrumento,
            orden=1,
            texto='¿Te sientes bien?',
            opciones=[
                {'valor': 'si', 'etiqueta': 'Sí'},
                {'valor': 'no', 'etiqueta': 'No'},
            ],
        )
        escuela = Escuela.objects.create(
            nombre='Escuela pública',
            director='Dirección',
            cantidad_total_alumnos=20,
            estado='Estado',
            municipio='Municipio',
        )
        proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='2026-2027',
            fecha_inicio='2026-08-02',
        )
        self.client.force_login(usuario)
        configuracion = ConfiguracionInstrumento.objects.create(
            proceso=proceso,
            instrumento=instrumento,
            orden=1,
        )
        publica = AplicacionPublica.objects.create(configuracion=configuracion)
        self.assertEqual(
            AplicacionPublica.objects.filter(configuracion=publica.configuracion).count(),
            1,
        )
        self.client.logout()
        pagina = self.client.get(publica.url_publica)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, pregunta.texto)
        enviada = self.client.post(
            publica.url_publica,
            {
                'nombre': 'Alumno Uno',
                'numero_alumno': 'A-001',
                'grupo': '1A',
                f'pregunta_{pregunta.id}': 'si',
            },
        )
        self.assertEqual(enviada.status_code, 200)
        self.assertContains(enviada, 'Gracias por responder')
        participante = Participante.objects.get(proceso=proceso, numero_alumno='A-001')
        aplicacion = AplicacionInstrumento.objects.get(
            proceso=proceso,
            participante=participante,
            instrumento=instrumento,
        )
        self.assertEqual(aplicacion.aplicacion_publica, publica)
        self.assertEqual(
            RespuestaInstrumento.objects.filter(aplicacion=aplicacion).count(),
            1,
        )
        self.assertTrue(
            ResultadoInstrumento.objects.filter(
                aplicacion=aplicacion,
                estado=ResultadoInstrumento.Estado.PENDIENTE,
            ).exists(),
        )
        repetida = self.client.post(
            publica.url_publica,
            {
                'nombre': 'Alumno Uno',
                'numero_alumno': 'A-001',
                'grupo': '1A',
                f'pregunta_{pregunta.id}': 'si',
            },
        )
        self.assertContains(repetida, 'ya fue respondido')
        self.assertEqual(
            RespuestaInstrumento.objects.filter(aplicacion=aplicacion).count(),
            1,
        )
        self.client.force_login(usuario)
        panel = self.client.get(
            reverse('certificacion_intera:proceso_detalle', args=[proceso.id]),
            {'tab': 'bateria'},
        )
        self.assertContains(panel, 'Batería y aplicación')
        self.assertContains(panel, publica.url_publica)

    def test_aplicacion_publica_guarda_un_instrumento_largo_completo(self):
        escuela = Escuela.objects.create(
            nombre='Escuela cuestionario largo',
            director='Dirección',
            cantidad_total_alumnos=120,
            estado='Estado',
            municipio='Municipio',
        )
        proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='2028-2029',
            fecha_inicio='2026-08-02',
        )
        instrumento = Instrumento.objects.create(
            nombre='Cuestionario largo',
            clave='cuestionario-largo',
        )
        preguntas = [
            PreguntaInstrumento(
                instrumento=instrumento,
                orden=orden,
                texto=f'Pregunta {orden}',
                opciones=[
                    {'valor': '1', 'etiqueta': 'Sí'},
                    {'valor': '0', 'etiqueta': 'No'},
                ],
            )
            for orden in range(1, 120)
        ]
        PreguntaInstrumento.objects.bulk_create(preguntas)
        configuracion = ConfiguracionInstrumento.objects.create(
            proceso=proceso,
            instrumento=instrumento,
        )
        publica = AplicacionPublica.objects.create(configuracion=configuracion)
        datos_incompletos = {
            'nombre': 'Alumno largo',
            'numero_alumno': 'L-001',
            'grupo': '1A',
            f'pregunta_{instrumento.preguntas.first().id}': '1',
        }
        incompleta = self.client.post(publica.url_publica, datos_incompletos)
        self.assertContains(incompleta, 'Faltan 118 preguntas obligatorias')
        self.assertFalse(
            Participante.objects.filter(proceso=proceso, numero_alumno='L-001').exists(),
        )
        datos_completos = {
            'nombre': 'Alumno largo',
            'numero_alumno': 'L-001',
            'grupo': '1A',
        }
        datos_completos.update(
            {f'pregunta_{pregunta.id}': '1' for pregunta in instrumento.preguntas.all()},
        )
        enviada = self.client.post(publica.url_publica, datos_completos)
        aplicacion = AplicacionInstrumento.objects.get(
            proceso=proceso,
            participante__numero_alumno='L-001',
        )
        self.assertContains(enviada, 'Gracias por responder')
        self.assertEqual(
            aplicacion.estado,
            AplicacionInstrumento.Estado.RESPONDIDA,
        )
        self.assertEqual(aplicacion.respuestas.count(), 119)

class CanalizacionTests(TestCase):

    def setUp(self):
        self.escuela = Escuela.objects.create(
            nombre='Escuela canalización',
            director='Dirección',
            cantidad_total_alumnos=1,
            estado='Estado',
            municipio='Municipio',
        )
        self.proceso = ProcesoCertificacion.objects.create(
            escuela=self.escuela,
            fecha_inicio=date.today(),
        )
        self.participante = Participante.objects.create(
            proceso=self.proceso,
            nombre='Alumno',
            numero_alumno='C-1',
        )

    def test_voluntaria_y_emergencia_no_requieren_consejerias_y_crean_bitacora(self):
        voluntaria = Canalizacion.objects.create(
            participante=self.participante,
            tipo=Canalizacion.Tipo.VOLUNTARIA,
            motivo='Solicita atención',
        )
        self.assertEqual(
            voluntaria.estado,
            Canalizacion.Estado.PENDIENTE_ENVIO,
        )
        self.assertEqual(
            voluntaria.estado_envio,
            Canalizacion.EstadoEnvio.PENDIENTE,
        )
        self.assertTrue(
            BitacoraProceso.objects.filter(
                proceso=self.proceso,
                evento='Canalización creada',
            ).exists(),
        )
        voluntaria.estado = Canalizacion.Estado.CERRADA
        voluntaria.save()
        emergencia = Canalizacion.objects.create(
            participante=self.participante,
            tipo=Canalizacion.Tipo.EMERGENCIA,
            motivo='Riesgo inmediato',
            observaciones='Atención urgente',
            prioridad=Canalizacion.Prioridad.URGENTE,
        )
        self.assertEqual(emergencia.prioridad, Canalizacion.Prioridad.URGENTE)

    def test_solicitud_pertenece_a_una_canalizacion_y_registra_bitacora(self):
        canalizacion = Canalizacion.objects.create(
            participante=self.participante,
            tipo=Canalizacion.Tipo.VOLUNTARIA,
            motivo='Atención solicitada',
        )
        solicitud = SolicitudAtencion.objects.create(canalizacion=canalizacion)
        self.assertEqual(
            solicitud.estado,
            SolicitudAtencion.Estado.PENDIENTE_ENVIO,
        )
        self.assertEqual(canalizacion.solicitud_atencion, solicitud)
        self.assertTrue(
            BitacoraProceso.objects.filter(
                proceso=self.proceso,
                evento='Solicitud de Atención creada',
            ).exists(),
        )
        with self.assertRaises(Exception):
            SolicitudAtencion.objects.create(canalizacion=canalizacion)

    def test_ordinaria_requiere_entrevista_tres_sesiones_y_no_duplica_activas(self):
        with self.assertRaises(Exception):
            Canalizacion.objects.create(
                participante=self.participante,
                tipo=Canalizacion.Tipo.ORDINARIA,
                motivo='Seguimiento',
            )
        EntrevistaSeguimiento.objects.create(
            participante=self.participante,
            nombre_confirmado='Alumno',
            numero_alumno_confirmado='C-1',
            fecha=date.today(),
            decision=EntrevistaSeguimiento.Decision.CONSEJERIA,
        )
        for _ in range(3):
            Consejeria.objects.create(
                participante=self.participante,
                fecha=date.today(),
                observaciones='Sesión',
                estado=Consejeria.Estado.REALIZADA,
            )
        canalizacion = Canalizacion.objects.create(
            participante=self.participante,
            tipo=Canalizacion.Tipo.ORDINARIA,
            motivo='Seguimiento concluido',
        )
        self.assertEqual(
            canalizacion.estado,
            Canalizacion.Estado.PENDIENTE_ENVIO,
        )
        with self.assertRaises(Exception):
            Canalizacion.objects.create(
                participante=self.participante,
                tipo=Canalizacion.Tipo.VOLUNTARIA,
                motivo='Duplicada',
            )

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
    CONSULTORIOWEB_INTEGRATION_ENABLED=True,
    CONSULTORIOWEB_API_BASE_URL='https://consultorio.example',
    CONSULTORIOWEB_API_KEY='clave-de-prueba',
    CONSULTORIOWEB_API_TIMEOUT=17,
)
class ConsultorioWebClientTests(TestCase):

    def setUp(self):
        escuela = Escuela.objects.create(
            nombre='Escuela API',
            director='Dirección',
            cantidad_total_alumnos=1,
            estado='Estado',
            municipio='Municipio',
        )
        proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='2026-2027',
            fecha_inicio=date.today(),
        )
        participante = Participante.objects.create(
            proceso=proceso,
            nombre='Persona administrativa',
            numero_alumno='A-1',
            telefono='5551234567',
        )
        canalizacion = Canalizacion.objects.create(
            participante=participante,
            tipo=Canalizacion.Tipo.VOLUNTARIA,
            motivo='Solicita orientación',
            prioridad=Canalizacion.Prioridad.MEDIA,
        )
        self.solicitud = SolicitudAtencion.objects.create(canalizacion=canalizacion)

    def test_payload_es_administrativo_y_omite_opcionales_vacios(self):
        payload = consultorio_web.payload_for(self.solicitud)
        self.assertEqual(payload['source'], 'certificacion_intera')
        self.assertEqual(payload['priority'], 'normal')
        self.assertNotIn('email', payload['participant'])
        serialized = str(payload).lower()
        for forbidden in (
            'resultado',
            'puntaje',
            'entrevista',
            'consejeria',
            'diagnostico',
            'api_key',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_payload_reporta_los_campos_obligatorios_faltantes(self):
        self.solicitud.canalizacion.participante.telefono = ''
        self.solicitud.canalizacion.participante.save()
        with self.assertRaises(consultorio_web.ConsultorioWebError) as captured:
            consultorio_web.payload_for(self.solicitud)
        self.assertEqual(captured.exception.code, 'validation_error')
        self.assertIn('teléfono de contacto', captured.exception.message)

    @override_settings(CONSULTORIOWEB_INTEGRATION_ENABLED=False)
    def test_integracion_deshabilitada(self):
        with self.assertRaises(consultorio_web.ConsultorioWebError) as captured:
            consultorio_web.enviar_solicitud(self.solicitud)
        self.assertEqual(captured.exception.code, 'integration_disabled')

    @override_settings(CONSULTORIOWEB_API_BASE_URL='')
    def test_url_ausente(self):
        with self.assertRaises(consultorio_web.ConsultorioWebError) as captured:
            consultorio_web.enviar_solicitud(self.solicitud)
        self.assertEqual(captured.exception.code, 'configuration_error')

    @override_settings(CONSULTORIOWEB_API_KEY='')
    def test_api_key_ausente(self):
        with self.assertRaises(consultorio_web.ConsultorioWebError) as captured:
            consultorio_web.enviar_solicitud(self.solicitud)
        self.assertEqual(captured.exception.code, 'configuration_error')

    @patch('apps.certificacion_intera.consultorio_web.request.urlopen')
    def test_headers_timeout_ids_y_post_201(self, urlopen):
        urlopen.return_value = FakeHttpResponse(201, b'{"status":"recibida","message":"Aceptada"}')
        status, body = consultorio_web.enviar_solicitud(self.solicitud)
        http_request = urlopen.call_args.args[0]
        self.assertEqual(status, 201)
        self.assertEqual(body['status'], 'recibida')
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 17)
        self.assertEqual(
            http_request.get_header('Authorization'),
            'ApiKey clave-de-prueba',
        )
        self.assertEqual(http_request.get_header('X-contract-version'), '1')
        self.assertEqual(
            http_request.get_header('Idempotency-key'),
            str(self.solicitud.idempotency_key),
        )
        self.assertNotIn(
            'clave-de-prueba',
            str(consultorio_web.payload_for(self.solicitud)),
        )

    @patch('apps.certificacion_intera.consultorio_web.request.urlopen')
    def test_request_id_cambia_e_idempotency_key_permanece(self, urlopen):
        urlopen.return_value = FakeHttpResponse(200, b'{"status":"recibida"}')
        consultorio_web.enviar_solicitud(self.solicitud)
        first = urlopen.call_args.args[0]
        consultorio_web.enviar_solicitud(self.solicitud)
        second = urlopen.call_args.args[0]
        self.assertNotEqual(
            first.get_header('X-request-id'),
            second.get_header('X-request-id'),
        )
        self.assertEqual(
            first.get_header('Idempotency-key'),
            second.get_header('Idempotency-key'),
        )

    def _http_error(self, status, body=b'{"message":"Error administrativo"}'):
        return error.HTTPError(
            'https://consultorio.example',
            status,
            'error',
            {},
            BytesIO(body),
        )

    @patch('apps.certificacion_intera.consultorio_web.request.urlopen')
    def test_post_error_codes_y_respuesta_no_json(self, urlopen):
        for status in (
            400,
            401,
            403,
            409,
            422,
            429,
            500,
        ):
            urlopen.side_effect = self._http_error(status)
            self.assertEqual(
                consultorio_web.enviar_solicitud(self.solicitud)[0],
                status,
            )
        urlopen.side_effect = None
        urlopen.return_value = FakeHttpResponse(201, b'no-json')
        with self.assertRaises(consultorio_web.ConsultorioWebError) as captured:
            consultorio_web.enviar_solicitud(self.solicitud)
        self.assertEqual(captured.exception.code, 'contract_error')

    @patch('apps.certificacion_intera.consultorio_web.request.urlopen')
    def test_timeout_conexion_rechazada_y_get(self, urlopen):
        urlopen.side_effect = TimeoutError()
        with self.assertRaises(consultorio_web.ConsultorioWebError) as captured:
            consultorio_web.enviar_solicitud(self.solicitud)
        self.assertEqual(captured.exception.code, 'communication_error')
        urlopen.side_effect = error.URLError('rechazada')
        with self.assertRaises(consultorio_web.ConsultorioWebError):
            consultorio_web.enviar_solicitud(self.solicitud)
        urlopen.side_effect = None
        urlopen.return_value = FakeHttpResponse(200, b'{"status":"finalizada"}')
        self.assertEqual(
            consultorio_web.consultar_estado(self.solicitud),
            (200, {'status': 'finalizada'}),
        )

    @patch('apps.certificacion_intera.consultorio_web.request.urlopen')
    def test_get_404_y_500(self, urlopen):
        for status in (404, 500):
            urlopen.side_effect = self._http_error(status)
            self.assertEqual(
                consultorio_web.consultar_estado(self.solicitud)[0],
                status,
            )

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
    CONSULTORIOWEB_INTEGRATION_ENABLED=True,
    CONSULTORIOWEB_API_BASE_URL='https://consultorio.example',
    CONSULTORIOWEB_API_KEY='clave-de-prueba',
)
class SolicitudAtencionViewsTests(TestCase):

    def setUp(self):
        self.usuario = User.objects.create_user(username='intera-api', password='secreto')
        group, _ = Group.objects.get_or_create(name='Certificación')
        self.usuario.groups.add(group)
        escuela = Escuela.objects.create(
            nombre='Escuela vistas',
            director='Dirección',
            cantidad_total_alumnos=1,
            estado='Estado',
            municipio='Municipio',
        )
        proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='2026-2027',
            fecha_inicio=date.today(),
        )
        participante = Participante.objects.create(
            proceso=proceso,
            nombre='Participante vistas',
            numero_alumno='V-1',
            telefono='5559876543',
            correo='persona@example.com',
        )
        canalizacion = Canalizacion.objects.create(
            participante=participante,
            tipo=Canalizacion.Tipo.VOLUNTARIA,
            motivo='Orientación',
        )
        self.solicitud = SolicitudAtencion.objects.create(
            canalizacion=canalizacion,
            creada_por=self.usuario,
        )
        self.canalizacion = canalizacion

    def _url(self, name):
        return reverse(f'certificacion_intera:{name}', args=[self.canalizacion.id])

    def test_autorizado_ve_panel_y_no_autorizado_no_ejecuta_acciones(self):
        self.client.force_login(self.usuario)
        self.assertContains(
            self.client.get(self._url('canalizacion_detalle')),
            'Seguimiento en Consultorio Web',
        )
        externo = User.objects.create_user(username='sin-intera', password='secreto')
        self.client.force_login(externo)
        self.assertEqual(
            self.client.post(self._url('solicitud_enviar')).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(self._url('solicitud_actualizar_estado')).status_code,
            403,
        )

    @patch('apps.certificacion_intera.views_extra.enviar_solicitud')
    def test_get_y_post_sin_confirmacion_no_envian(self, enviar):
        self.client.force_login(self.usuario)
        self.assertEqual(
            self.client.get(self._url('solicitud_enviar')).status_code,
            405,
        )
        self.client.post(self._url('solicitud_enviar'))
        enviar.assert_not_called()
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.send_attempts, 0)

    @patch('apps.certificacion_intera.views_extra.enviar_solicitud')
    def test_post_201_y_200_son_exitosos_y_no_duplican(self, enviar):
        self.client.force_login(self.usuario)
        enviar.return_value = (201, {'status': 'recibida'})
        self.client.post(
            self._url('solicitud_enviar'),
            {'confirmar_envio': 'si'},
        )
        self.solicitud.refresh_from_db()
        self.assertEqual(
            self.solicitud.integration_status,
            SolicitudAtencion.EstadoIntegracion.ENVIADA,
        )
        self.assertEqual(self.solicitud.send_attempts, 1)
        self.assertTrue(
            BitacoraProceso.objects.filter(evento='Envío exitoso 201').exists(),
        )
        self.client.post(
            self._url('solicitud_enviar'),
            {'confirmar_envio': 'si'},
        )
        self.assertEqual(enviar.call_count, 1)
        self.assertEqual(
            SolicitudAtencion.objects.filter(canalizacion=self.canalizacion).count(),
            1,
        )

    @patch('apps.certificacion_intera.views_extra.enviar_solicitud')
    def test_error_reintento_y_conflicto_conservan_uuid(self, enviar):
        self.client.force_login(self.usuario)
        external, key = (
            self.solicitud.external_request_id,
            self.solicitud.idempotency_key,
        )
        enviar.side_effect = consultorio_web.ConsultorioWebError(
            'communication_error',
            'Sin conexión',
        )
        self.client.post(
            self._url('solicitud_enviar'),
            {'confirmar_envio': 'si'},
        )
        self.solicitud.refresh_from_db()
        self.assertEqual(
            self.solicitud.integration_status,
            SolicitudAtencion.EstadoIntegracion.ERROR,
        )
        enviar.side_effect = None
        enviar.return_value = (409, {'message': 'Conflicto'})
        self.client.post(
            self._url('solicitud_enviar'),
            {'confirmar_envio': 'si'},
        )
        self.solicitud.refresh_from_db()
        self.assertEqual(
            (
                self.solicitud.external_request_id,
                self.solicitud.idempotency_key,
            ),
            (external, key),
        )
        self.assertTrue(
            BitacoraProceso.objects.filter(evento='Conflicto de idempotencia').exists(),
        )

    @patch('apps.certificacion_intera.views_extra.consultar_estado')
    def test_actualizar_estado_y_sin_cambio_no_duplica_cambio(self, consultar):
        self.client.force_login(self.usuario)
        self.solicitud.integration_status = SolicitudAtencion.EstadoIntegracion.ENVIADA
        self.solicitud.remote_status = 'recibida'
        self.solicitud.save()
        consultar.return_value = (
            200,
            {
                'status': 'finalizada',
                'message': 'Atención finalizada',
                'updated_at': '2026-08-03T12:00:00-06:00',
            },
        )
        self.client.post(self._url('solicitud_actualizar_estado'))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.remote_status, 'finalizada')
        changes = BitacoraProceso.objects.filter(evento='Cambio de estado remoto').count()
        consultar.return_value = (
            200,
            {'status': 'finalizada', 'message': 'Sin cambio'},
        )
        self.client.post(self._url('solicitud_actualizar_estado'))
        self.assertEqual(
            BitacoraProceso.objects.filter(evento='Cambio de estado remoto').count(),
            changes,
        )
        self.assertTrue(
            BitacoraProceso.objects.filter(evento='Estado remoto sin cambios').exists(),
        )

    def test_csrf_es_requerido_para_envio(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.usuario)
        self.assertEqual(
            client.post(self._url('solicitud_enviar'), {'confirmar_envio': 'si'}).status_code,
            403,
        )

class EntrevistaUnoAUnoPermissionsTests(TestCase):

    def test_acceso_no_hereda_el_permiso_general_de_certificacion(self):
        usuario = User.objects.create_user(
            username='sin-permiso-1a1',
            password='secreto',
        )
        grupo, _ = Group.objects.get_or_create(name='CertificaciÃ³n')
        usuario.groups.add(grupo)
        escuela = Escuela.objects.create(
            nombre='Escuela 1a1',
            director='DirecciÃ³n',
            cantidad_total_alumnos=1,
            estado='Estado',
            municipio='Municipio',
        )
        proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='1a1',
            fecha_inicio=date.today(),
        )
        participante = Participante.objects.create(
            proceso=proceso,
            nombre='Persona Uno',
            numero_alumno='1A1',
        )
        self.client.force_login(usuario)
        respuesta = self.client.get(
            reverse(
                'certificacion_intera:entrevista_1a1_acceso',
                args=[participante.id],
            ),
        )
        self.assertEqual(respuesta.status_code, 403)

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class EntrevistaUnoAUnoCapturaTests(TestCase):

    def setUp(self):
        self.usuario = User.objects.create_user(
            username='entrevista-1a1',
            password='secreto',
            is_superuser=True,
        )
        escuela = Escuela.objects.create(
            nombre='Escuela captura',
            director='Dirección',
            cantidad_total_alumnos=1,
            estado='Estado',
            municipio='Municipio',
        )
        self.proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='captura',
            fecha_inicio=date.today(),
        )
        self.participante = Participante.objects.create(
            proceso=self.proceso,
            nombre='Persona Captura',
            numero_alumno='C-1',
        )
        instrumento = Instrumento.objects.get(clave=CLAVE_ENTREVISTA)
        revision = RevisionInstrumento.objects.get(
            instrumento=instrumento,
            version=instrumento.version,
        )
        self.entrevista = EntrevistaUnoAUno.objects.create(
            participante=self.participante,
            proceso=self.proceso,
            instrumento=instrumento,
            revision_plantilla=revision,
            responsable=self.usuario,
            iniciada_por=self.usuario,
        )
        self.client.force_login(self.usuario)

    def _url(self):
        return reverse(
            'certificacion_intera:entrevista_1a1',
            args=[self.participante.id],
        )

    def _datos(self, **cambios):
        datos = {'accion': 'borrador'}
        for pregunta in self.entrevista.revision_plantilla.estructura['preguntas']:
            if pregunta['tipo_respuesta'] == 'si_no':
                datos['pregunta_' + pregunta['clave']] = 'no'
            elif pregunta['clave'] == 'MOT-04':
                datos['pregunta_' + pregunta['clave']] = '5'
            elif pregunta['tipo_respuesta'] == 'texto_libre':
                datos['pregunta_' + pregunta['clave']] = 'texto abierto'
            else:
                datos['pregunta_' + pregunta['clave']] = 'texto corto'
        datos.update(
            {
                (
                    'pregunta_' + clave[len('pregunta_'):].replace('_', '-')
                    if clave.startswith('pregunta_')
                    else clave
                ): valor
                for (clave, valor) in cambios.items()
            },
        )
        return datos

    def test_widgets_abiertos_si_no_y_numero_se_renderizan_correctamente(self):
        respuesta = self.client.get(self._url())
        html = respuesta.content.decode()
        self.assertEqual(respuesta.status_code, 200)
        self.assertRegex(html, r'<textarea\b[^>]*\bid="id_pregunta_MOT-01"[^>]*>')
        self.assertRegex(html, r'<input\b(?=[^>]*\btype="radio")(?=[^>]*\bname="pregunta_MOT-02")[^>]*>')
        self.assertRegex(html, r'<input\b(?=[^>]*\btype="number")(?=[^>]*\bname="pregunta_MOT-04")(?=[^>]*\bmin="1")(?=[^>]*\bmax="10")(?=[^>]*\bstep="1")[^>]*>')
        for clave in (
            'DES-07',
            'DES-08',
            'DES-09',
            'RES-03',
            'MOD-05',
            'MOD-08',
        ):
            self.assertRegex(html, rf'<textarea\b[^>]*\bid="id_pregunta_{re.escape(clave)}"[^>]*>')

    def test_borrador_guarda_texto_abierto_y_limpia_dependiente_inactiva(self):
        self.client.post(
            self._url(),
            self._datos(
                pregunta_MOT_02='si',
                pregunta_MOT_03='Plan personal',
                pregunta_MOT_01='Respuesta libre',
            ),
        )
        mot03 = PreguntaInstrumento.objects.get(
            instrumento=self.entrevista.instrumento,
            clave='MOT-03',
        )
        self.assertEqual(
            RespuestaEntrevistaUnoAUno.objects.get(
                entrevista=self.entrevista,
                pregunta=mot03,
                revision=1,
            ).valor,
            'Plan personal',
        )
        self.client.post(self._url(), self._datos(pregunta_MOT_02='no'))
        self.assertFalse(
            RespuestaEntrevistaUnoAUno.objects.filter(
                entrevista=self.entrevista,
                pregunta=mot03,
                revision=1,
            ).exists(),
        )

    def test_finalizar_exige_solo_visibles_y_rango_entero(self):
        datos = self._datos(accion='finalizar', pregunta_MOT_04='11')
        respuesta = self.client.post(self._url(), datos)
        self.entrevista.refresh_from_db()
        self.assertEqual(
            self.entrevista.estado,
            EntrevistaUnoAUno.Estado.EN_CURSO,
        )
        self.assertContains(
            respuesta,
            'Completa las preguntas obligatorias visibles',
        )
        datos = self._datos(
            accion='finalizar',
            pregunta_MOT_02='no',
            pregunta_DES_01='no',
            pregunta_DES_04='no',
            pregunta_MOD_04='no',
            pregunta_MOD_07='no',
        )
        self.client.post(self._url(), datos)
        self.entrevista.refresh_from_db()
        self.assertEqual(
            self.entrevista.estado,
            EntrevistaUnoAUno.Estado.FINALIZADA,
        )

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class CrearProcesoConBateriaTests(TestCase):

    def setUp(self):
        self.usuario = User.objects.create_user(username='crear-proceso', password='secreto')
        self.usuario.groups.add(
            Group.objects.get_or_create(name='Certificación')[0],
        )
        self.client.force_login(self.usuario)
        self.escuela = Escuela.objects.create(
            nombre='Escuela para proceso',
            director='Dirección',
            cantidad_total_alumnos=20,
            estado='Estado',
            municipio='Municipio',
        )
        self.orientativo = crear_instrumento_bateria(
            'dass-21-adolescentes',
            'DASS-21',
            21,
            CalculadoraInstrumento.Estado.ORIENTATIVA,
        )
        self.rosenberg = crear_instrumento_bateria(
            'rse-autoestima',
            'Escala de Autoestima de Rosenberg',
            10,
            CalculadoraInstrumento.Estado.ORIENTATIVA,
        )
        crear_instrumento_bateria(
            'scid-ii-adolescentes',
            'SCID-II PQ',
            119,
            CalculadoraInstrumento.Estado.NO_DIAGNOSTICA,
        )
        self.plutchik = crear_instrumento_bateria(
            'ersp-plutchik-adolescentes',
            'Escala de Riesgo Suicida de Plutchik',
            15,
            CalculadoraInstrumento.Estado.ORIENTATIVA,
        )
        Instrumento.objects.create(
            nombre='SCID-II',
            clave='scid-ii-incompleto',
        )
        scid_sin_trazabilidad = Instrumento.objects.create(nombre='SCID-II', clave='scid-ii-antiguo')
        PreguntaInstrumento.objects.create(
            instrumento=scid_sin_trazabilidad,
            orden=1,
            texto='Registro antiguo',
        )

    def _datos(self, **cambios):
        datos = {
            'escuela': self.escuela.id,
            'nombre': 'Proceso de prueba',
            'ciclo_escolar': '2026-2027',
            'fecha_inicio': date.today().isoformat(),
            'instrumentos': [str(self.orientativo.id)],
            f'orden_{self.orientativo.id}': '1',
        }
        datos.update(cambios)
        return datos

    def test_panel_abre_formulario_directo_y_crea_proceso_con_bateria(self):
        panel = self.client.get(reverse('certificacion_intera:dashboard'))
        self.assertContains(
            panel,
            reverse('certificacion_intera:proceso_crear_general'),
        )
        pagina = self.client.get(reverse('certificacion_intera:proceso_crear_general'))
        self.assertContains(pagina, 'Batería de evaluación')
        self.assertContains(pagina, 'DASS-21')
        self.assertContains(pagina, '21 reactivos')
        self.assertContains(
            pagina,
            'Escala de Autoestima de Rosenberg',
        )
        self.assertContains(pagina, '10 reactivos')
        self.assertContains(
            pagina,
            'SCID-II PQ',
            count=1,
        )
        self.assertContains(pagina, '119 reactivos')
        self.assertContains(pagina, 'Calculadora no diagnóstica')
        self.assertContains(
            pagina,
            'Escala de Riesgo Suicida de Plutchik',
        )
        entrevista = Instrumento.objects.get(clave=CLAVE_ENTREVISTA)
        self.assertTrue(entrevista.activo)
        self.assertEqual(entrevista.preguntas.count(), 24)
        self.assertNotContains(pagina, entrevista.nombre)
        self.assertContains(pagina, 'Calculadora orientativa')
        respuesta = self.client.post(
            reverse('certificacion_intera:proceso_crear_general'),
            self._datos(),
        )
        self.assertEqual(respuesta.status_code, 302)
        proceso = ProcesoCertificacion.objects.get(nombre='Proceso de prueba')
        self.assertEqual(proceso.escuela, self.escuela)
        self.assertEqual(
            proceso.estado,
            ProcesoCertificacion.Estado.CONFIGURACION,
        )
        self.assertIsNone(proceso.fecha_cierre)
        self.assertEqual(
            list(
                proceso.configuraciones_instrumento.values_list(
                    'instrumento_id',
                    'orden',
                ),
            ),
            [(self.orientativo.id, 1)],
        )

    def test_post_manipulado_no_agrega_entrevista_a_la_bateria(self):
        entrevista = Instrumento.objects.get(clave=CLAVE_ENTREVISTA)
        respuesta = self.client.post(
            reverse('certificacion_intera:proceso_crear_general'),
            self._datos(
                instrumentos=[str(entrevista.id)],
                **{f'orden_{entrevista.id}': '1'},
            ),
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            'Este instrumento no está disponible para esta batería.',
        )
        self.assertFalse(ProcesoCertificacion.objects.exists())

    def test_entrevista_preexistente_no_entra_al_flujo_publico_ni_al_expediente(self):
        proceso = ProcesoCertificacion.objects.create(
            escuela=self.escuela,
            nombre='Proceso con configuración histórica',
            ciclo_escolar='histórico',
            fecha_inicio=date.today(),
        )
        entrevista = Instrumento.objects.get(clave=CLAVE_ENTREVISTA)
        ConfiguracionInstrumento.objects.bulk_create(
            [
                ConfiguracionInstrumento(
                    proceso=proceso,
                    instrumento=self.orientativo,
                    orden=1,
                ),
                ConfiguracionInstrumento(
                    proceso=proceso,
                    instrumento=entrevista,
                    orden=2,
                ),
            ],
        )
        participante = Participante.objects.create(
            proceso=proceso,
            nombre='Participante histórico',
            numero_alumno='H-1',
        )
        AplicacionInstrumento.objects.create(
            proceso=proceso,
            participante=participante,
            instrumento=entrevista,
        )
        publica = AplicacionPublica.objects.create(proceso=proceso)

        expediente = self.client.get(
            reverse(
                'certificacion_intera:participante_detalle',
                args=[participante.id],
            ),
        )
        self.assertContains(expediente, 'Entrevista 1:1', count=1)

        cliente_publico = Client()
        respuesta = cliente_publico.post(
            publica.url_publica,
            {
                'nombre': 'Participante público',
                'numero_alumno': 'PUB-1',
                'fecha_nacimiento': '2008-01-01',
                'grupo': 'A',
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        nuevo = Participante.objects.get(numero_alumno='PUB-1', proceso=proceso)
        self.assertEqual(
            list(nuevo.aplicaciones.values_list('instrumento__clave', flat=True)),
            [self.orientativo.clave],
        )
        bateria = cliente_publico.get(publica.url_publica)
        self.assertContains(bateria, self.orientativo.nombre)
        self.assertNotContains(bateria, entrevista.nombre)

    def test_instrumento_orientativo_y_orden_invalido_no_dejan_proceso_parcial(self):
        datos = self._datos(
            instrumentos=[str(self.orientativo.id), str(self.rosenberg.id)],
            **{f'orden_{self.rosenberg.id}': '1'},
        )
        respuesta = self.client.post(
            reverse('certificacion_intera:proceso_crear_general'),
            datos,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(ProcesoCertificacion.objects.count(), 0)

    def test_instrumento_orientativo_puede_integrarse_a_la_bateria(self):
        datos = self._datos(
            instrumentos=[str(self.orientativo.id), str(self.rosenberg.id)],
            **{f'orden_{self.rosenberg.id}': '2'},
        )
        respuesta = self.client.post(
            reverse('certificacion_intera:proceso_crear_general'),
            datos,
        )

        self.assertEqual(respuesta.status_code, 302)
        proceso = ProcesoCertificacion.objects.get(nombre='Proceso de prueba')
        self.assertEqual(
            list(
                proceso.configuraciones_instrumento.values_list(
                    'instrumento_id',
                    'orden',
                ),
            ),
            [(self.orientativo.id, 1), (self.rosenberg.id, 2)],
        )

    def test_instrumento_inactivo_no_aparece_en_la_bateria(self):
        inactivo = Instrumento.objects.create(
            nombre='Instrumento inactivo',
            clave='instrumento-inactivo',
            activo=False,
        )
        pagina = self.client.get(
            reverse('certificacion_intera:proceso_crear_general'),
        )
        self.assertNotContains(pagina, inactivo.nombre)

    def test_plutchik_orientativo_puede_integrarse_a_la_bateria(self):
        datos = self._datos(
            instrumentos=[str(self.plutchik.id)],
            **{f'orden_{self.plutchik.id}': '1'},
        )
        respuesta = self.client.post(
            reverse('certificacion_intera:proceso_crear_general'),
            datos,
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            ProcesoCertificacion.objects.get().configuraciones_instrumento.get().instrumento,
            self.plutchik,
        )

@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class AplicacionPublicaGeneralTests(TestCase):

    def setUp(self):
        self.usuario = User.objects.create_user(
            username='publica-general',
            password='secreto',
        )
        self.usuario.groups.add(
            Group.objects.get_or_create(name='Certificación')[0],
        )
        self.client.force_login(self.usuario)
        escuela = Escuela.objects.create(
            nombre='Escuela pública general',
            director='Dirección',
            cantidad_total_alumnos=20,
            estado='Estado',
            municipio='Municipio',
        )
        self.proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='general',
            fecha_inicio=date.today(),
        )
        self.instrumento = Instrumento.objects.create(
            nombre='Instrumento general',
            clave='general-publico',
        )
        PreguntaInstrumento.objects.create(
            instrumento=self.instrumento,
            orden=1,
            texto='Pregunta pública',
            opciones=[{'valor': 'si', 'etiqueta': 'Sí'}],
        )
        ConfiguracionInstrumento.objects.create(
            proceso=self.proceso,
            instrumento=self.instrumento,
            orden=1,
        )

    def test_generar_es_idempotente_y_la_ficha_tiene_pestanas(self):
        detalle = self.client.get(
            reverse(
                'certificacion_intera:proceso_detalle',
                args=[self.proceso.id],
            ),
            {'tab': 'bateria'},
        )
        self.assertContains(detalle, 'Aplicación pública')
        self.assertContains(detalle, 'Generar enlace')
        for tab in (
            'resumen',
            'participantes',
            'bateria',
            'entrevistas',
            'seguimiento',
            'configuracion',
            'bitacora',
        ):
            self.assertContains(detalle, '?tab=' + tab)
        url = reverse(
            'certificacion_intera:aplicacion_publica_proceso_generar',
            args=[self.proceso.id],
        )
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(
            AplicacionPublica.objects.filter(proceso=self.proceso).count(),
            1,
        )

    def test_procesos_distintos_tienen_accesos_y_qr_distintos(self):
        otra_escuela = Escuela.objects.create(
            nombre='Otra escuela',
            director='Dirección',
            cantidad_total_alumnos=10,
            estado='Estado',
            municipio='Municipio',
        )
        otro_proceso = ProcesoCertificacion.objects.create(
            escuela=otra_escuela,
            ciclo_escolar='otro',
            fecha_inicio=date.today(),
        )
        primera = AplicacionPublica.objects.create(proceso=self.proceso)
        segunda = AplicacionPublica.objects.create(proceso=otro_proceso)

        self.assertNotEqual(primera.token, segunda.token)
        self.assertNotEqual(primera.url_publica, segunda.url_publica)
        self.assertNotEqual(
            reverse(
                'certificacion_intera:aplicacion_publica_proceso_qr',
                args=[self.proceso.id],
            ),
            reverse(
                'certificacion_intera:aplicacion_publica_proceso_qr',
                args=[otro_proceso.id],
            ),
        )

    @patch('apps.certificacion_intera.views.qrcode.make')
    def test_enlace_mostrado_y_qr_reciben_exactamente_la_misma_url(self, crear_qr):
        class ImagenFalsa:
            def save(self, destino):
                destino.write(b'<svg></svg>')

        crear_qr.return_value = ImagenFalsa()
        publica = AplicacionPublica.objects.create(proceso=self.proceso)
        detalle = self.client.get(
            reverse('certificacion_intera:proceso_detalle', args=[self.proceso.id]),
            {'tab': 'bateria'},
        )
        url_absoluta = f'http://testserver{publica.url_publica}'
        self.assertContains(detalle, url_absoluta, count=2)

        respuesta_qr = self.client.get(
            reverse(
                'certificacion_intera:aplicacion_publica_proceso_qr',
                args=[self.proceso.id],
            ),
        )

        self.assertEqual(respuesta_qr.status_code, 200)
        self.assertEqual(crear_qr.call_args.args[0], url_absoluta)

    def test_qr_no_tiene_token_separado_y_cambiar_bateria_no_cambia_acceso(self):
        publica = AplicacionPublica.objects.create(proceso=self.proceso)
        token = publica.token
        campos = {campo.name for campo in AplicacionPublica._meta.get_fields()}
        self.assertNotIn('token_qr', campos)
        self.assertNotIn('qr_token', campos)

        self.proceso.configuraciones_instrumento.all().delete()
        nuevo = Instrumento.objects.create(nombre='Instrumento nuevo', clave='nuevo-qr')
        ConfiguracionInstrumento.objects.create(
            proceso=self.proceso,
            instrumento=nuevo,
            orden=1,
        )
        publica.refresh_from_db()

        self.assertEqual(publica.token, token)

    def test_proceso_sin_instrumentos_conserva_acceso_y_muestra_mensaje(self):
        self.proceso.configuraciones_instrumento.all().delete()
        generar = reverse(
            'certificacion_intera:aplicacion_publica_proceso_generar',
            args=[self.proceso.id],
        )
        self.assertEqual(self.client.post(generar).status_code, 302)
        publica = AplicacionPublica.objects.get(proceso=self.proceso)
        self.client.logout()

        respuesta = self.client.get(publica.url_publica)

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            'Este proceso aún no tiene instrumentos disponibles.',
        )

    def test_participantes_del_mismo_acceso_no_mezclan_aplicaciones(self):
        publica = AplicacionPublica.objects.create(proceso=self.proceso)
        url = publica.url_publica
        primero = Client()
        segundo = Client()
        datos_base = {
            'fecha_nacimiento': '2008-01-01',
            'grupo': 'A',
        }
        primero.post(
            url,
            {**datos_base, 'nombre': 'Participante uno', 'numero_alumno': 'UNO'},
        )
        segundo.post(
            url,
            {**datos_base, 'nombre': 'Participante dos', 'numero_alumno': 'DOS'},
        )

        participantes = Participante.objects.filter(proceso=self.proceso)
        self.assertEqual(participantes.count(), 2)
        aplicaciones = AplicacionInstrumento.objects.filter(aplicacion_publica=publica)
        self.assertEqual(aplicaciones.count(), 2)
        self.assertEqual(aplicaciones.values('participante_id').distinct().count(), 2)

    def test_enlace_general_inicia_con_datos_y_reutiliza_participante(self):
        publica, _ = AplicacionPublica.objects.get_or_create(proceso=self.proceso)
        self.client.logout()
        url = reverse(
            'certificacion_intera:aplicacion_publica',
            args=[publica.token],
        )
        pagina = self.client.get(url)
        self.assertContains(pagina, 'Datos generales')
        datos = {
            'nombre': 'Persona Pública',
            'numero_alumno': 'PG-1',
            'sexo': 'femenino',
            'fecha_nacimiento': '2008-01-01',
            'grupo': 'A',
        }
        self.assertNotContains(pagina, 'Sexo')
        respuesta = self.client.post(url, datos)
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            Participante.objects.filter(
                proceso=self.proceso,
                numero_alumno='PG-1',
            ).count(),
            1,
        )
        self.assertEqual(
            Participante.objects.get(proceso=self.proceso, numero_alumno='PG-1').sexo,
            '',
        )
        self.client.post(url, datos)
        self.assertEqual(
            Participante.objects.filter(
                proceso=self.proceso,
                numero_alumno='PG-1',
            ).count(),
            1,
        )

    def test_solicita_sexo_solo_antes_del_instrumento_que_lo_requiere(self):
        self.proceso.configuraciones_instrumento.all().delete()
        instrumento = Instrumento.objects.create(nombre='ISRA', clave='isra')
        PreguntaInstrumento.objects.create(
            instrumento=instrumento,
            orden=1,
            texto='Reactivo ISRA',
            opciones=[{'valor': '1', 'etiqueta': 'Sí'}],
        )
        ConfiguracionInstrumento.objects.create(
            proceso=self.proceso,
            instrumento=instrumento,
            orden=1,
        )
        publica, _ = AplicacionPublica.objects.get_or_create(proceso=self.proceso)
        self.client.logout()
        url = reverse(
            'certificacion_intera:aplicacion_publica',
            args=[publica.token],
        )
        datos = {
            'nombre': 'Persona ISRA',
            'numero_alumno': 'ISRA-1',
            'fecha_nacimiento': '2008-01-01',
            'grupo': 'A',
        }
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        contexto = self.client.get(url)
        self.assertContains(
            contexto,
            'Sexo (requerido para baremos del instrumento)',
        )
        self.assertContains(contexto, 'value="femenino"')
        self.assertContains(contexto, 'value="masculino"')
        self.assertNotContains(contexto, 'no_especificado')
        self.assertNotContains(contexto, 'value="otro"')
        self.assertEqual(
            self.client.post(url, {'sexo': 'femenino'}).status_code,
            302,
        )
        participante = Participante.objects.get(proceso=self.proceso, numero_alumno='ISRA-1')
        self.assertEqual(participante.sexo, 'femenino')
        siguiente = self.client.get(url)
        self.assertContains(siguiente, 'Comenzar evaluación')
        self.assertNotContains(
            siguiente,
            'Sexo (requerido para baremos del instrumento)',
        )

    @patch(
        'apps.certificacion_intera.views.campos_contexto_requeridos',
        return_value={'sexo'},
    )
    def test_reutiliza_sexo_para_varios_instrumentos_del_mismo_flujo(
        self,
        _campos_contexto,
    ):
        self.proceso.configuraciones_instrumento.all().delete()
        primero = Instrumento.objects.create(
            nombre='Instrumento uno',
            clave='contexto-uno',
        )
        segundo = Instrumento.objects.create(
            nombre='Instrumento dos',
            clave='contexto-dos',
        )
        pregunta_uno = PreguntaInstrumento.objects.create(
            instrumento=primero,
            orden=1,
            texto='Reactivo uno',
            opciones=[{'valor': '1', 'etiqueta': 'Sí'}],
        )
        PreguntaInstrumento.objects.create(
            instrumento=segundo,
            orden=1,
            texto='Reactivo dos',
            opciones=[{'valor': '1', 'etiqueta': 'Sí'}],
        )
        ConfiguracionInstrumento.objects.create(
            proceso=self.proceso,
            instrumento=primero,
            orden=1,
        )
        ConfiguracionInstrumento.objects.create(
            proceso=self.proceso,
            instrumento=segundo,
            orden=2,
        )
        publica, _ = AplicacionPublica.objects.get_or_create(proceso=self.proceso)
        self.client.logout()
        url = reverse(
            'certificacion_intera:aplicacion_publica',
            args=[publica.token],
        )
        self.client.post(
            url,
            {
                'nombre': 'Persona contexto',
                'numero_alumno': 'CTX-1',
                'fecha_nacimiento': '2008-01-01',
            },
        )
        self.assertContains(
            self.client.get(url),
            'Sexo (requerido para baremos del instrumento)',
        )
        self.client.post(url, {'sexo': 'masculino'})
        self.client.post(url, {'accion': 'comenzar'})
        self.client.post(
            url,
            {
                'accion': 'responder',
                f'pregunta_{pregunta_uno.id}': '1',
            },
        )
        siguiente = self.client.get(url)
        self.assertContains(siguiente, 'Instrumento dos')
        self.assertNotContains(
            siguiente,
            'Sexo (requerido para baremos del instrumento)',
        )

    def test_ficha_presenta_acciones_publicas_con_jerarquia_y_nombres(self):
        publica, _ = AplicacionPublica.objects.get_or_create(
            proceso=self.proceso,
        )
        respuesta = self.client.get(
            reverse(
                'certificacion_intera:proceso_detalle',
                args=[self.proceso.id],
            ),
            {'tab': 'bateria'},
        )

        self.assertContains(respuesta, 'Activa')
        self.assertContains(respuesta, 'Copiar enlace')
        self.assertContains(respuesta, 'Abrir aplicación')
        self.assertContains(respuesta, 'Desactivar')
        self.assertContains(respuesta, 'aplicacion-publica__acciones')
        self.assertContains(respuesta, 'intera-btn-secondary')
        self.assertContains(respuesta, 'intera-btn-caution')
        self.assertContains(respuesta, 'intera-btn-small')
        self.assertContains(respuesta, 'Vista individual')
        self.assertContains(respuesta, publica.url_publica)
        self.assertContains(respuesta, 'readonly')

        self.assertNotContains(respuesta, 'Registrar participante')
        self.assertNotContains(respuesta, 'Mostrar enlace')
        self.assertNotContains(respuesta, 'Ocultar enlace')
        self.assertNotContains(respuesta, '<br>')

    def test_ficha_muestra_url_de_solo_lectura_sin_regenerar_enlace(self):
        publica, _ = AplicacionPublica.objects.get_or_create(
            proceso=self.proceso,
        )
        token_original = publica.token

        respuesta = self.client.get(
            reverse(
                'certificacion_intera:proceso_detalle',
                args=[self.proceso.id],
            ),
            {'tab': 'bateria'},
        )

        self.assertContains(respuesta, 'readonly')
        self.assertContains(respuesta, 'data-copy-status')
        self.assertContains(respuesta, 'Copiar enlace')
        self.assertContains(respuesta, 'Abrir aplicación')
        self.assertContains(respuesta, publica.url_publica)

        self.assertNotContains(respuesta, 'Mostrar enlace')
        self.assertNotContains(respuesta, 'Ocultar enlace')

        publica.refresh_from_db()

        self.assertEqual(
            publica.token,
            token_original,
        )

    def test_resultado_muestra_advertencia_orientativa_separada(self):
        participante = Participante.objects.create(
            proceso=self.proceso,
            nombre='Participante orientativo',
            numero_alumno='ORI-1',
        )
        aplicacion = AplicacionInstrumento.objects.create(
            proceso=self.proceso,
            participante=participante,
            instrumento=self.instrumento,
            interpretacion='Interpretación calculada.',
            revision_calculadora={
                'clave': 'regla-orientativa',
                'version_regla': '1.0',
                'estado': 'orientativa',
            },
        )

        respuesta = self.client.get(
            reverse('certificacion_intera:resultado', args=[aplicacion.id])
        )

        self.assertContains(respuesta, 'Interpretación calculada.')
        self.assertContains(
            respuesta,
            ADVERTENCIA_RESULTADO_ORIENTATIVO,
        )


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class CierreProcesoTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(
            username='cierre-proceso',
            password='secreto',
        )
        self.usuario.groups.add(
            Group.objects.get_or_create(name='Certificación')[0],
        )
        self.client.force_login(self.usuario)
        escuela = Escuela.objects.create(
            nombre='Escuela cierre',
            director='Dirección',
            cantidad_total_alumnos=10,
            estado='Estado',
            municipio='Municipio',
        )
        self.proceso = ProcesoCertificacion.objects.create(
            escuela=escuela,
            ciclo_escolar='cierre',
            fecha_inicio=date.today(),
        )
        self.instrumento = Instrumento.objects.create(
            nombre='Instrumento cierre',
            clave='instrumento-cierre',
        )
        self.pregunta = PreguntaInstrumento.objects.create(
            instrumento=self.instrumento,
            orden=1,
            texto='Pregunta cierre',
            opciones=[{'valor': 'si', 'etiqueta': 'Sí'}],
        )
        ConfiguracionInstrumento.objects.create(
            proceso=self.proceso,
            instrumento=self.instrumento,
            orden=1,
        )
        self.participante = Participante.objects.create(
            proceso=self.proceso,
            nombre='Participante histórico',
            numero_alumno='CIERRE-1',
        )
        self.aplicacion = AplicacionInstrumento.objects.create(
            proceso=self.proceso,
            participante=self.participante,
            instrumento=self.instrumento,
            estado=AplicacionInstrumento.Estado.RESPONDIDA,
        )
        RespuestaInstrumento.objects.create(
            aplicacion=self.aplicacion,
            pregunta=self.pregunta,
            valor='si',
        )
        ResultadoInstrumento.objects.create(
            aplicacion=self.aplicacion,
            estado=ResultadoInstrumento.Estado.EVALUADO,
        )
        self.publica = AplicacionPublica.objects.create(proceso=self.proceso)
        self.url_detalle = reverse(
            'certificacion_intera:proceso_detalle',
            args=[self.proceso.id],
        )
        self.url_cierre = reverse(
            'certificacion_intera:proceso_cerrar',
            args=[self.proceso.id],
        )

    def test_abierto_muestra_accion_y_get_solo_confirma(self):
        detalle = self.client.get(self.url_detalle)
        self.assertContains(detalle, 'Cerrar proceso')

        confirmacion = self.client.get(self.url_cierre)
        self.proceso.refresh_from_db()
        self.assertEqual(confirmacion.status_code, 200)
        self.assertContains(confirmacion, 'Ya no se recibirán nuevos participantes')
        self.assertContains(confirmacion, 'csrfmiddlewaretoken')
        self.assertNotEqual(self.proceso.estado, ProcesoCertificacion.Estado.CERRADO)

    def test_cierre_requiere_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)

        respuesta = cliente.post(self.url_cierre)

        self.assertEqual(respuesta.status_code, 403)
        self.proceso.refresh_from_db()
        self.assertNotEqual(self.proceso.estado, ProcesoCertificacion.Estado.CERRADO)

    def test_cierre_registra_bitacora_conserva_historial_y_oculta_accion(self):
        totales = {
            'participantes': self.proceso.participantes.count(),
            'aplicaciones': self.proceso.aplicaciones.count(),
            'respuestas': RespuestaInstrumento.objects.filter(
                aplicacion__proceso=self.proceso,
            ).count(),
            'resultados': ResultadoInstrumento.objects.filter(
                aplicacion__proceso=self.proceso,
            ).count(),
        }

        respuesta = self.client.post(self.url_cierre)
        self.proceso.refresh_from_db()

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.proceso.estado, ProcesoCertificacion.Estado.CERRADO)
        self.assertEqual(self.proceso.fecha_cierre, date.today())
        evento = BitacoraProceso.objects.get(
            proceso=self.proceso,
            evento='Cierre de proceso',
        )
        self.assertEqual(evento.usuario, self.usuario)
        self.assertIsNotNone(evento.creado_en)
        self.assertEqual(self.proceso.participantes.count(), totales['participantes'])
        self.assertEqual(self.proceso.aplicaciones.count(), totales['aplicaciones'])
        self.assertEqual(
            RespuestaInstrumento.objects.filter(aplicacion__proceso=self.proceso).count(),
            totales['respuestas'],
        )
        self.assertEqual(
            ResultadoInstrumento.objects.filter(aplicacion__proceso=self.proceso).count(),
            totales['resultados'],
        )
        detalle = self.client.get(self.url_detalle)
        self.assertContains(detalle, 'Finalizado')
        self.assertNotContains(detalle, 'Cerrar proceso')
        resultado = self.client.get(
            reverse('certificacion_intera:resultado', args=[self.aplicacion.id]),
        )
        self.assertEqual(resultado.status_code, 200)

    def test_cerrado_bloquea_altas_y_respuestas_pero_conserva_url_y_qr(self):
        pendiente = AplicacionInstrumento.objects.create(
            proceso=self.proceso,
            participante=self.participante,
            instrumento=self.instrumento,
        )
        self.client.post(self.url_cierre)
        participantes_antes = self.proceso.participantes.count()
        respuestas_antes = RespuestaInstrumento.objects.count()

        publico = Client()
        general = publico.post(
            self.publica.url_publica,
            {
                'nombre': 'Participante nuevo',
                'numero_alumno': 'NUEVO',
                'fecha_nacimiento': '2008-01-01',
            },
        )
        individual = publico.post(
            reverse(
                'certificacion_intera:aplicacion_individual',
                args=[pendiente.token],
            ),
            {f'pregunta_{self.pregunta.id}': 'si'},
        )

        mensaje = 'Este proceso de certificación ha finalizado y ya no recibe respuestas.'
        self.assertEqual(general.status_code, 200)
        self.assertContains(general, mensaje)
        self.assertEqual(individual.status_code, 200)
        self.assertContains(individual, mensaje)
        self.assertEqual(self.proceso.participantes.count(), participantes_antes)
        self.assertEqual(RespuestaInstrumento.objects.count(), respuestas_antes)
        qr = self.client.get(
            reverse(
                'certificacion_intera:aplicacion_publica_proceso_qr',
                args=[self.proceso.id],
            ),
        )
        self.assertEqual(qr.status_code, 200)
        self.publica.refresh_from_db()
        self.assertIsNotNone(self.publica.token)
