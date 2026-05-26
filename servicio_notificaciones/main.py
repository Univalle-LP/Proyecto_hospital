import pika
import json
import time

def procesar_mensaje(ch, method, properties, body):
    mensaje = json.loads(body)
    
    print("\n" + "="*50)
    print(" 🔔 [NUEVO EVENTO] Procesando notificación...")
    print("="*50)
    print(f" 📧 Simulando envío de correo a: {mensaje['paciente']}")
    print(f" 🩺 Doctor asignado: {mensaje['doctor']}")
    print(f" 📅 Fecha: {mensaje['fecha']}")
    
    # Simulamos el tiempo de envío de un correo real
    time.sleep(3) 
    
    print(" ✅ Correo enviado exitosamente.")
    ch.basic_ack(delivery_tag=method.delivery_tag)

def iniciar_trabajador():
    print(' [*] Iniciando Microservicio de Notificaciones...')
    
    connection = None
    # Ciclo infinito de reintentos hasta que RabbitMQ despierte
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            print(' ✅ Conexión con RabbitMQ establecida con éxito.')
            break  # Si se conecta, rompe el ciclo y avanza
        except pika.exceptions.AMQPConnectionError:
            print(' ⚠️ RabbitMQ no está listo aún. Reintentando en 5 segundos...')
            time.sleep(5)
            
    channel = connection.channel()
    channel.queue_declare(queue='citas_pendientes')
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue='citas_pendientes', on_message_callback=procesar_mensaje)

    print(' [*] Worker encendido y escuchando la cola de mensajes...')
    channel.start_consuming()
    
if __name__ == '__main__':
    iniciar_trabajador()