from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pika
import json
import mysql.connector
from mysql.connector import Error
from fastapi.middleware.cors import CORSMiddleware
import time

app = FastAPI(title="Microservicio de Citas Hospitalarias")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 1. MODELOS DE DATOS
# ==========================================
class Cita(BaseModel):
    paciente: str
    doctor: str
    fecha: str
    motivo: str
    horario_id: int  # Relaciona la cita con el cupo elegido

class Horario(BaseModel):
    doctor: str
    fecha_hora: str

class LoginData(BaseModel):
    usuario: str
    password: str

class EstadoCita(BaseModel):
    estado: str

# ==========================================
# 2. CONFIGURACIÓN DE BASE DE DATOS
# ==========================================
db_config = {
    'host': 'db_citas',
    'port': 3306,
    'user': 'root',
    'password': 'root',
    'database': 'citas_db'
}

def inicializar_bd():
    print("⏳ Conectando a la base de datos...")
    intentos = 5
    while intentos > 0:
        try:
            conexion = mysql.connector.connect(**db_config)
            cursor = conexion.cursor()
            
            # Tabla de Citas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS citas (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    paciente VARCHAR(255) NOT NULL,
                    doctor VARCHAR(255) NOT NULL,
                    fecha VARCHAR(255) NOT NULL,
                    motivo TEXT NOT NULL,
                    estado VARCHAR(50) DEFAULT 'Pendiente'
                )
            """)
            
            # Tabla de Usuarios
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    usuario VARCHAR(50) UNIQUE NOT NULL,
                    password VARCHAR(50) NOT NULL,
                    rol VARCHAR(20) NOT NULL,
                    nombre_completo VARCHAR(100) NOT NULL
                )
            """)
            
            # Tabla de Horarios Ofrecidos por los Médicos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS horarios_disponibles (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    doctor VARCHAR(255) NOT NULL,
                    fecha_hora VARCHAR(255) NOT NULL,
                    estado VARCHAR(50) DEFAULT 'Disponible'
                )
            """)
            
            # Insertar usuarios de demostración si está vacía
            cursor.execute("SELECT COUNT(*) FROM usuarios")
            if cursor.fetchone()[0] == 0:
                usuarios_demo = [
                    ("admin", "admin123", "admin", "Administrador Central"),
                    ("dr_perez", "123", "doctor", "Dr. Perez (Cirujano)"),
                    ("dra_miranda", "123", "doctor", "Dra. Miranda (Pediatra)"),
                    ("juan", "123", "paciente", "Juan Gabriel Rada Escobar")
                ]
                cursor.executemany(
                    "INSERT INTO usuarios (usuario, password, rol, nombre_completo) VALUES (%s, %s, %s, %s)", 
                    usuarios_demo
                )

            conexion.commit()
            cursor.close()
            conexion.close()
            print("✅ Base de datos inicializada correctamente.")
            break
        except Error as e:
            print(f"⚠️ BD no lista aún. Reintentando en 5 segundos... Error: {e}")
            time.sleep(5)
            intentos -= 1

inicializar_bd()

# ==========================================
# 3. FUNCIÓN DE COMUNICACIÓN CON RABBITMQ
# ==========================================
def notificar_rabbitmq(cita_id, estado):
    # Busca los detalles de la cita y lanza el evento a RabbitMQ
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT paciente, doctor, fecha FROM citas WHERE id = %s", (cita_id,))
        cita = cursor.fetchone()
        cursor.close()
        conexion.close()

        if cita:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()
            channel.queue_declare(queue='citas_pendientes')
            mensaje = {
                "id_cita": cita_id,
                "paciente": cita["paciente"],
                "doctor": cita["doctor"],
                "fecha": cita["fecha"],
                "estado": estado
            }
            channel.basic_publish(exchange='', routing_key='citas_pendientes', body=json.dumps(mensaje))
            connection.close()
    except Exception as err_mq:
        print(f"⚠️ Evento RabbitMQ omitido: {err_mq}")

# ==========================================
# 4. ENDPOINTS DE LA API (RUTAS)
# ==========================================

@app.post("/login")
def login(datos: LoginData):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT id, usuario, rol, nombre_completo FROM usuarios WHERE usuario=%s AND password=%s", 
                       (datos.usuario, datos.password))
        usuario = cursor.fetchone()
        cursor.close()
        conexion.close()
        if usuario:
            return {"status": "éxito", "usuario": usuario}
        else:
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/horarios")
def agregar_horario(h: Horario):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor()
        cursor.execute("INSERT INTO horarios_disponibles (doctor, fecha_hora) VALUES (%s, %s)", (h.doctor, h.fecha_hora))
        conexion.commit()
        cursor.close()
        conexion.close()
        return {"status": "éxito"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/horarios")
def obtener_horarios():
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT * FROM horarios_disponibles ORDER BY fecha_hora ASC")
        datos = cursor.fetchall()
        cursor.close()
        conexion.close()
        return {"status": "éxito", "horarios": datos}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agendar")
def agendar_cita(cita: Cita):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor()
        
        # 1. Insertamos el registro de la cita
        cursor.execute("INSERT INTO citas (paciente, doctor, fecha, motivo) VALUES (%s, %s, %s, %s)",
                       (cita.paciente, cita.doctor, cita.fecha, cita.motivo))
        
        # 2. El cupo del doctor pasa a estar ocupado (Reservado)
        cursor.execute("UPDATE horarios_disponibles SET estado = 'Reservado' WHERE id = %s", (cita.horario_id,))
        
        conexion.commit()
        cita_id = cursor.lastrowid
        cursor.close()
        conexion.close()

        # 3. Notificar creación de cita al Worker a través de RabbitMQ
        notificar_rabbitmq(cita_id, "Pendiente")

        return {"status": "éxito", "id_cita": cita_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/citas")
def obtener_citas():
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT * FROM citas ORDER BY id DESC")
        datos = cursor.fetchall()
        cursor.close()
        conexion.close()
        return {"status": "éxito", "citas": datos}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/citas/{cita_id}/estado")
def cambiar_estado_cita(cita_id: int, datos: EstadoCita):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor()
        
        # 1. Actualizamos el estado de la cita (Validada, Realizada, Cancelada)
        cursor.execute("UPDATE citas SET estado = %s WHERE id = %s", (datos.estado, cita_id))
        conexion.commit()
        cursor.close()
        conexion.close()
        
        # 2. Disparamos la notificación asíncrona al paciente con su nuevo estado
        notificar_rabbitmq(cita_id, datos.estado)
        
        return {"status": "éxito"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))