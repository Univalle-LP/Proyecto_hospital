import pika
import json
import time

def procesar_mensaje(ch, method, properties, body):
    mensaje = json.loads(body)
    # Si no trae estado, asumimos que es nueva (Pendiente)
    estado = mensaje.get('estado', 'Pendiente')
    
    print("\n" + "="*50)
    print(f" 🔔 [EVENTO] Alerta de Cita - Estado: {estado.upper()}")
    print("="*50)
    print(f" 👤 Destinatario (Paciente): {mensaje['paciente']}")
    
    # Redacción dinámica del correo según el estado
    if estado == 'Pendiente':
        print(" 📝 Asunto: Solicitud Recibida")
        print(" ✉️ Cuerpo: Su cita ha sido registrada y está esperando aprobación del administrador.")
    elif estado == 'Validada':
        print(" ✅ Asunto: ¡Cita APROBADA!")
        print(f" ✉️ Cuerpo: Su cita fue aceptada. Por favor, asista puntualmente con el {mensaje['doctor']} en la fecha {mensaje['fecha'].replace('T', ' ')}.")
    elif estado == 'Realizada':
        print(" 🏁 Asunto: Consulta Finalizada")
        print(" ✉️ Cuerpo: Su cita ha concluido satisfactoriamente. ¡Gracias por confiar en HealthSync Hospital!")
    elif estado == 'Cancelada':
        print(" ❌ Asunto: Cita Cancelada")
        print(f" ✉️ Cuerpo: Lo sentimos, su cita con el {mensaje['doctor']} ha sido cancelada por el área médica.")
        
    time.sleep(2) # Simulamos el tiempo de envío a Gmail
    print(" 📨 Correo simulado enviado exitosamente.")
    ch.basic_ack(delivery_tag=method.delivery_tag)

def iniciar_trabajador():
    print(' [*] Iniciando Microservicio de Notificaciones...')
    connection = None
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            print(' ✅ Conexión con RabbitMQ establecida con éxito.')
            break
        except pika.exceptions.AMQPConnectionError:
            print(' ⚠️ RabbitMQ no está listo aún. Reintentando en 5 segundos...')
            time.sleep(5)
            
    channel = connection.channel()
    channel.queue_declare(queue='citas_pendientes')
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue='citas_pendientes', on_message_callback=procesar_mensaje)

    print(' [*] Worker encendido y escuchando cambios de estado...')
    channel.start_consuming()
    
if __name__ == '__main__':
    iniciar_trabajador()