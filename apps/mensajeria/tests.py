import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Baja, Envio, SistemaSuscrito

PLANTILLAS_PRUEBA = {
    'intra_recordatorio_cita_v1': {
        'variables': ['1', '2', '3', '4'],
        'idiomas': ['es_MX'],
    },
}


@override_settings(MENSAJERIA_PLANTILLAS=PLANTILLAS_PRUEBA)
class PasarelaMensajeriaTests(TestCase):
    """Las cuatro pruebas de la sección 9 del contrato, más autenticación y
    formato de error. `meta_client.enviar_plantilla` se mockea: estas
    pruebas verifican la lógica de la pasarela (idempotencia, bajas,
    contrato de errores), no la integración real con Meta -- esa es manual,
    contra un número propio, antes de conectar cualquier proceso real."""

    def setUp(self):
        self.sistema = SistemaSuscrito.objects.create(
            nombre='crm_ventas', api_key='clave-de-prueba',
        )
        self.headers = {
            'HTTP_AUTHORIZATION': 'ApiKey clave-de-prueba',
            'HTTP_X_CONTRACT_VERSION': '1',
            'content_type': 'application/json',
        }

    def _payload(self, **overrides):
        payload = {
            'destinatario': '+528442896091',
            'plantilla': 'intra_recordatorio_cita_v1',
            'idioma': 'es_MX',
            'variables': {'1': 'María González', '2': 'sucursal Centro', '3': 'martes', '4': '16:00'},
            'origen': {'sistema': 'crm_ventas', 'entidad': 'Prospecto', 'id': 4821},
        }
        payload.update(overrides)
        return payload

    def _post_envio(self, payload, idempotency_key='idem-1'):
        return self.client.post(
            reverse('mensajeria:envios'),
            data=json.dumps(payload),
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
            **self.headers,
        )

    # -- Prueba 1: cada plantilla aprobada llega con el formato correcto --

    @patch('apps.mensajeria.meta_client.requests.post')
    def test_plantilla_aprobada_se_envia_con_formato_correcto(self, post_mock):
        post_mock.return_value.status_code = 200
        post_mock.return_value.json.return_value = {'messages': [{'id': 'wamid.ABC'}]}

        respuesta = self._post_envio(self._payload())

        self.assertEqual(respuesta.status_code, 201)
        cuerpo_enviado = post_mock.call_args.kwargs['json']
        self.assertEqual(cuerpo_enviado['type'], 'template')
        self.assertEqual(cuerpo_enviado['template']['name'], 'intra_recordatorio_cita_v1')
        self.assertEqual(cuerpo_enviado['to'], '+528442896091')

        envio = Envio.objects.get()
        self.assertEqual(envio.estado, Envio.Estado.ENVIADO)
        self.assertEqual(envio.wa_message_id, 'wamid.ABC')

    # -- Prueba 2: misma Idempotency-Key dos veces -> un solo mensaje --

    @patch('apps.mensajeria.meta_client.requests.post')
    def test_misma_idempotency_key_no_duplica_envio(self, post_mock):
        post_mock.return_value.status_code = 200
        post_mock.return_value.json.return_value = {'messages': [{'id': 'wamid.ABC'}]}

        primera = self._post_envio(self._payload(), idempotency_key='misma-key')
        segunda = self._post_envio(self._payload(), idempotency_key='misma-key')

        self.assertEqual(primera.json()['envio_id'], segunda.json()['envio_id'])
        self.assertEqual(post_mock.call_count, 1)
        self.assertEqual(Envio.objects.count(), 1)

    def test_misma_idempotency_key_con_payload_distinto_es_conflicto(self):
        with patch('apps.mensajeria.meta_client.requests.post') as post_mock:
            post_mock.return_value.status_code = 200
            post_mock.return_value.json.return_value = {'messages': [{'id': 'wamid.ABC'}]}
            self._post_envio(self._payload(), idempotency_key='misma-key')

        respuesta = self._post_envio(
            self._payload(variables={'1': 'Otra Persona', '2': 'x', '3': 'y', '4': 'z'}),
            idempotency_key='misma-key',
        )

        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.json()['code'], 'idempotencia_en_conflicto')

    # -- Prueba 3: número dado de baja -> destinatario_dado_de_baja sin llamar a Meta --

    @patch('apps.mensajeria.meta_client.requests.post')
    def test_destinatario_dado_de_baja_no_llama_a_meta(self, post_mock):
        Baja.objects.create(destinatario='+528442896091', origen_sistema='crm_ventas')

        respuesta = self._post_envio(self._payload())

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['estado'], Envio.Estado.BLOQUEADO)
        post_mock.assert_not_called()

        envio = Envio.objects.get()
        self.assertEqual(envio.motivo_bloqueo, 'destinatario_dado_de_baja')

    # -- Prueba 4: respuesta a botón de plantilla llega como webhook al sistema solicitante --

    @patch('apps.mensajeria.emisor_webhooks.requests.post')
    @patch('apps.mensajeria.meta_client.verificar_firma_webhook', return_value=True)
    def test_respuesta_de_boton_notifica_al_sistema_solicitante(self, _firma_mock, notificar_mock):
        SistemaSuscrito.objects.filter(nombre='crm_ventas').update(
            webhook_url='https://crm.example/webhooks/mensajeria/',
            webhook_hmac_secret='secreto',
        )
        envio = Envio.objects.create(
            destinatario='+528442896091', plantilla='intra_recordatorio_cita_v1',
            origen_sistema='crm_ventas', origen_entidad='Prospecto', origen_id='4821',
            idempotency_key='idem-x', huella_payload='x', wa_message_id='wamid.ABC',
            estado=Envio.Estado.ENVIADO,
        )

        cuerpo_webhook = {
            'entry': [{'changes': [{'value': {
                'messages': [{
                    'from': '+528442896091',
                    'timestamp': str(int(timezone.now().timestamp())),
                    'type': 'button',
                    'button': {'payload': 'confirmar_asistencia', 'text': 'Confirmar asistencia'},
                }],
            }}]}],
        }

        respuesta = self.client.post(
            reverse('mensajeria:webhook_meta'),
            data=json.dumps(cuerpo_webhook),
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256='sha256=lo-que-sea',
        )

        self.assertEqual(respuesta.status_code, 200)
        notificar_mock.assert_called_once()
        cuerpo_enviado = json.loads(notificar_mock.call_args.kwargs['data'])
        self.assertEqual(cuerpo_enviado['evento'], 'respuesta_boton')
        self.assertEqual(cuerpo_enviado['data']['envio_id'], envio.envio_id)
        self.assertEqual(cuerpo_enviado['data']['boton_id'], 'confirmar_asistencia')

    # -- Autenticación y formato de error (sección 7) --

    def test_sin_api_key_responde_401_con_formato_estandar(self):
        respuesta = self.client.post(
            reverse('mensajeria:envios'),
            data=json.dumps(self._payload()),
            content_type='application/json',
            HTTP_X_CONTRACT_VERSION='1',
            HTTP_IDEMPOTENCY_KEY='idem-1',
        )
        self.assertEqual(respuesta.status_code, 401)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['code'], 'autenticacion_invalida')
        self.assertIn('request_id', cuerpo)

    def test_plantilla_desconocida(self):
        respuesta = self._post_envio(self._payload(plantilla='no_existe'))
        self.assertEqual(respuesta.status_code, 422)
        self.assertEqual(respuesta.json()['code'], 'plantilla_desconocida')

    def test_variables_incompletas(self):
        respuesta = self._post_envio(self._payload(variables={'1': 'María'}))
        self.assertEqual(respuesta.status_code, 422)
        self.assertEqual(respuesta.json()['code'], 'variables_incompletas')

    def test_destinatario_invalido(self):
        respuesta = self._post_envio(self._payload(destinatario='8442896091'))
        self.assertEqual(respuesta.status_code, 422)
        self.assertEqual(respuesta.json()['code'], 'destinatario_invalido')
