from argparse import ArgumentError
import ssl
from django.db.models import Avg
from datetime import timedelta, datetime
from receiver.models import Data, Measurement
import paho.mqtt.client as mqtt
import schedule
import time
from django.conf import settings

client = mqtt.Client(settings.MQTT_USER_PUB)


def analyze_data():
    # Consulta todos los datos de la última hora, los agrupa por estación y variable
    # Compara el promedio con los valores límite que están en la base de datos para esa variable.
    # Si el promedio se excede de los límites, se envia un mensaje de alerta.

    print("Calculando alertas...")

    data = Data.objects.filter(
        base_time__gte=datetime.now() - timedelta(hours=1))
    aggregation = data.annotate(check_value=Avg('avg_value')) \
        .select_related('station', 'measurement') \
        .select_related('station__user', 'station__location') \
        .select_related('station__location__city', 'station__location__state',
                        'station__location__country') \
        .values('check_value', 'station__user__username',
                'measurement__name',
                'measurement__max_value',
                'measurement__min_value',
                'station__location__city__name',
                'station__location__state__name',
                'station__location__country__name')
    
    alerts = 0
    for item in aggregation:
        alert = False
        additional_message = ""

        variable = item["measurement__name"]
        max_value = item["measurement__max_value"] or 0
        min_value = item["measurement__min_value"] or 0

        country = item['station__location__country__name']
        state = item['station__location__state__name']
        city = item['station__location__city__name']
        user = item['station__user__username']

        if item["check_value"] > max_value or item["check_value"] < min_value:
            alert = True
            additional_message = "Valor promedio fuera de rango"

        if alert:
            message = "ALERT {} {} {} {}".format(variable, additional_message, min_value, max_value)
            topic = '{}/{}/{}/{}/in'.format(country, state, city, user)
            print(datetime.now(), "Sending alert to {} {}".format(topic, variable))
            client.publish(topic, message)
            alerts += 1

    print(len(aggregation), "dispositivos revisados")
    print(alerts, "alertas enviadas")



def analyze_fire():
        # Consulta todos los datos de la última hora, los agrupa por estación y variable
    # Compara el promedio con los valores límite que están en la base de datos para esa variable.
    # Si el promedio se excede de los límites, se envia un mensaje de alerta.

    print("Detectando incendios...")

    data = Data.objects.filter(
        base_time__gte=datetime.now() - timedelta(minutes=5))
    aggregation = data.annotate(check_value=Avg('avg_value')) \
        .select_related('station', 'measurement') \
        .select_related('station__user', 'station__location') \
        .select_related('station__location__city', 'station__location__state',
                        'station__location__country') \
        .values('check_value', 'station__user__username',
                'measurement__name',
                'measurement__max_value',
                'measurement__min_value',
                'station__location__city__name',
                'station__location__state__name',
                'station__location__country__name')
    
    alerts = 0
    humidity_item = None
    temperature_item = None
    for item in aggregation:
        if item["measurement__name"] == "humedad":
            humidity_item = item
            break
        if item['measurement__name'] == "temperatura":
            temperature_item = item
            break

    if humidity_item and temperature_item:
        alert = False

        if humidity_item['check_value'] > humidity_item['measurement__min_value'] and temperature_item['check_value'] > temperature_item['measurement__max_value']:
            alert = True
            additional_message = "INCENDIO DETECTADO"

        if alert:
            message = "ALERT {}".format(additional_message)
            topic = '{}/{}/{}/{}/in'.format(humidity_item['station__location__country__name'], humidity_item['station__location__state__name'], humidity_item['station__location__city__name'], humidity_item['station__user__username'])
            print(datetime.now(), "Sending alert to fire prevention {}".format(topic))
            client.publish(topic, message)
            alerts += 1
    

    print(len(aggregation), "dispositivos revisados")
    print(alerts, "alertas de fuego enviadas")
    print(humidity_item['check_value'], temperature_item['check_value'], 'Datos')


def on_connect(client, userdata, flags, rc):
    '''
    Función que se ejecuta cuando se conecta al bróker.
    '''
    print("Conectando al broker MQTT...", mqtt.connack_string(rc))


def on_disconnect(client: mqtt.Client, userdata, rc):
    '''
    Función que se ejecuta cuando se desconecta del broker.
    Intenta reconectar al bróker.
    '''
    print("Desconectado con mensaje:" + str(mqtt.connack_string(rc)))
    print("Reconectando...")
    client.reconnect()


def setup_mqtt():
    '''
    Configura el cliente MQTT para conectarse al broker.
    '''

    print("Iniciando cliente MQTT...", settings.MQTT_HOST, settings.MQTT_PORT)
    global client
    try:
        client = mqtt.Client(settings.MQTT_USER_PUB)
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect

        if settings.MQTT_USE_TLS:
            client.tls_set(ca_certs=settings.CA_CRT_PATH,
                           tls_version=ssl.PROTOCOL_TLSv1_2, cert_reqs=ssl.CERT_NONE)

        client.username_pw_set(settings.MQTT_USER_PUB,
                               settings.MQTT_PASSWORD_PUB)
        client.connect(settings.MQTT_HOST, settings.MQTT_PORT)

    except Exception as e:
        print('Ocurrió un error al conectar con el bróker MQTT:', e)


def start_cron():
    '''
    Inicia el cron que se encarga de ejecutar la función analyze_data cada 5 minutos.
    '''
    print("Iniciando cron...")
    schedule.every(3).minutes.do(analyze_data)
    schedule.every(0.2).minutes.do(analyze_fire)
    print("Servicio de control iniciado")
    while 1:
        schedule.run_pending()
        time.sleep(1)
