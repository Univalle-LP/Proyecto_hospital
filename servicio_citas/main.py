from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pika
import json
import mysql.connector
from mysql.connector import Error
import time
import jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import string

app = FastAPI(title="Microservicio de Citas Hospitalarias")

app.add_middleware(
    CORSMiddleware,
    # Autorizamos específicamente los puertos del Frontend web para evitar el bloqueo CORS
    allow_origins=["http://localhost:8080", "http://localhost", "http://127.0.0.1:8080", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 1. CONFIGURACIÓN DE SEGURIDAD (Tokens y Cifrado)
# ==========================================
SECRET_KEY = "healthsync_super_secreto_2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 # La sesión expirará en 30 minutos

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def obtener_hash_password(password):
    return pwd_context.hash(password)

def verificar_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def crear_token_acceso(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# ==========================================
# 2. MODELOS DE DATOS (Pydantic)
# ==========================================
class LoginData(BaseModel):
    usuario: str
    password: str
class RecuperarData(BaseModel):
    correo: str

class RegistroData(BaseModel):
    usuario: str
    password: str
    rol: str = "paciente"
    nombre_completo: str
    correo: str
class RecuperarData(BaseModel):
    correo: str

class CambioPasswordData(BaseModel):
    usuario: str
    password_actual: str
    password_nuevo: str

class Cita(BaseModel):
    paciente: str
    doctor: str
    fecha: str
    motivo: str
    horario_id: int  # Relaciona la cita con el cupo elegido

class Horario(BaseModel):
    doctor: str
    fecha_hora: str

class EstadoCita(BaseModel):
    estado: str

# ==========================================
# 3. CONFIGURACIÓN E INICIALIZACIÓN DE BD
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
            
            # Tabla de Usuarios (Asegurando la columna correo)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    usuario VARCHAR(50) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    rol VARCHAR(20) NOT NULL,
                    nombre_completo VARCHAR(100) NOT NULL,
                    correo VARCHAR(100)
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
            
# ... (Aquí está tu código de usuarios demo) ...

            # Insertar Horarios de Doctores de Prueba
            cursor.execute("SELECT COUNT(*) FROM horarios_disponibles")
            if cursor.fetchone()[0] == 0:
                horarios_demo = [
                    ("Dr. Perez (Cirujano)", "2026-06-15 09:00", "Reservado"),
                    ("Dr. Perez (Cirujano)", "2026-06-15 10:00", "Disponible"),
                    ("Dra. Miranda (Pediatra)", "2026-06-16 14:00", "Reservado"),
                    ("Dra. Miranda (Pediatra)", "2026-06-16 15:00", "Disponible")
                ]
                cursor.executemany("INSERT INTO horarios_disponibles (doctor, fecha_hora, estado) VALUES (%s, %s, %s)", horarios_demo)

            # Insertar Citas de Prueba
            cursor.execute("SELECT COUNT(*) FROM citas")
            if cursor.fetchone()[0] == 0:
                citas_demo = [
                    ("Juan Gabriel Rada Escobar", "Dr. Perez (Cirujano)", "2026-06-15 09:00", "Chequeo general post-operatorio", "Validada"),
                    ("Maria Gonzales", "Dra. Miranda (Pediatra)", "2026-06-16 14:00", "Control de vacunas", "Pendiente"),
                    ("Carlos Sanchez", "Dr. Perez (Cirujano)", "2026-06-18 11:00", "Dolor abdominal agudo", "Cancelada")
                ]
                cursor.executemany("INSERT INTO citas (paciente, doctor, fecha, motivo, estado) VALUES (%s, %s, %s, %s, %s)", citas_demo)

            # Insertar usuarios de demostración si está vacía
            cursor.execute("SELECT COUNT(*) FROM usuarios")
            if cursor.fetchone()[0] == 0:
                # Ciframos las contraseñas ANTES de meterlas a la base de datos
                hashed_admin = obtener_hash_password("admin123")
                hashed_123 = obtener_hash_password("123")
                
                usuarios_demo = [
                    ("admin", hashed_admin, "admin", "Administrador Central", "admin@hospital.com"),
                    ("dr_perez", hashed_123, "doctor", "Dr. Perez (Cirujano)", "perez@hospital.com"),
                    ("dra_miranda", hashed_123, "doctor", "Dra. Miranda (Pediatra)", "miranda@hospital.com"),
                    ("juan", hashed_123, "paciente", "Juan Gabriel Rada Escobar", "juan@hospital.com")
                ]
                cursor.executemany(
                    "INSERT INTO usuarios (usuario, password, rol, nombre_completo, correo) VALUES (%s, %s, %s, %s, %s)", 
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
# 4. FUNCIÓN DE COMUNICACIÓN CON RABBITMQ
# ==========================================
def notificar_rabbitmq(cita_id, estado):
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
# 5. ENDPOINTS DE LA API (RUTAS)
# ==========================================

@app.post("/registro")
def registrar_usuario(datos: RegistroData):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor()
        
        # Ciframos la contraseña antes de guardarla
        hashed_password = obtener_hash_password(datos.password)
        
        cursor.execute("INSERT INTO usuarios (usuario, password, rol, nombre_completo, correo) VALUES (%s, %s, %s, %s, %s)", 
                       (datos.usuario, hashed_password, datos.rol, datos.nombre_completo, datos.correo))
        conexion.commit()
        cursor.close()
        conexion.close()
        return {"status": "éxito", "mensaje": "Usuario registrado correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.post("/login")
def login(datos: LoginData):
    # 1. Intentamos conectar a la BD primero
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT id, usuario, password, rol, nombre_completo FROM usuarios WHERE usuario=%s", 
                       (datos.usuario,))
        usuario = cursor.fetchone()
        cursor.close()
        conexion.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de base de datos: {str(e)}")
        
    # 2. Fuera del Try-Except, validamos la contraseña de forma segura
    if usuario and verificar_password(datos.password, usuario['password']):
        # Creamos el Token de sesión
        token_data = {"sub": usuario['usuario'], "rol": usuario['rol'], "nombre": usuario['nombre_completo']}
        token = crear_token_acceso(token_data)
        return {
            "status": "éxito", 
            "access_token": token, 
            "token_type": "bearer", 
            "usuario": {
                "usuario": usuario['usuario'], 
                "nombre_completo": usuario['nombre_completo'], 
                "rol": usuario['rol']
            }
        }
    else:
        # Si la contraseña está mal, lanzamos un 401 limpio
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

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
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/citas/{cita_id}/estado")
def cambiar_estado_cita(cita_id: int, datos: EstadoCita):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor()
        
        # 1. Actualizamos el estado de la cita
        cursor.execute("UPDATE citas SET estado = %s WHERE id = %s", (datos.estado, cita_id))
        conexion.commit()
        cursor.close()
        conexion.close()
        
        # 2. Disparamos la notificación asíncrona
        notificar_rabbitmq(cita_id, datos.estado)
        
        return {"status": "éxito"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# Función para enviar el correo real usando Gmail
def enviar_correo_real(destinatario, nombre_usuario, temp_password):
    remitente = "juangabrielrada99@gmail.com" # <--- CAMBIA ESTO POR TU GMAIL
    password_app = "oiolhchbhynxyjpc" # <--- PEGA AQUÍ LA CONTRASEÑA DEL PASO 1 (Sin espacios)

    msg = MIMEMultipart()
    msg['From'] = remitente
    msg['To'] = destinatario
    msg['Subject'] = "Recuperación de Contraseña - HealthSync Hospital"

    cuerpo = f"""
    Hola {nombre_usuario},

    Hemos recibido una solicitud para recuperar tu acceso al sistema de HealthSync Hospital.
    
    Tu nueva contraseña temporal es: {temp_password}

    Por favor, inicia sesión con esta contraseña. Por motivos de seguridad, te recomendamos no compartirla con nadie.

    Saludos cordiales,
    El equipo de soporte de HealthSync.
    """
    msg.attach(MIMEText(cuerpo, 'plain'))

    try:
        # Conectando al servidor de Gmail
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(remitente, password_app)
        server.send_message(msg)
        server.quit()
        print(f"✅ Correo de recuperación enviado a {destinatario}")
    except Exception as e:
        print(f"❌ Error al enviar correo: {e}")

# Endpoint que recibe la petición del Frontend
@app.post("/recuperar-password")
def recuperar_password(datos: RecuperarData):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor(dictionary=True)
        
        # Buscamos si el correo existe
        cursor.execute("SELECT id, usuario, correo, nombre_completo FROM usuarios WHERE correo=%s", (datos.correo,))
        usuario = cursor.fetchone()

        if usuario:
            # 1. Generamos una contraseña temporal de 8 caracteres
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            
            # 2. La ciframos
            hashed_temp = obtener_hash_password(temp_password)
            
            # 3. La guardamos en la base de datos
            cursor.execute("UPDATE usuarios SET password=%s WHERE id=%s", (hashed_temp, usuario['id']))
            conexion.commit()
            
            # 4. Enviamos el correo real
            enviar_correo_real(usuario['correo'], usuario['nombre_completo'], temp_password)

        cursor.close()
        conexion.close()
        
        # Por seguridad (anti-hackers), siempre devolvemos el mismo mensaje, exista o no el correo
        return {"status": "éxito", "mensaje": "Proceso completado"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.put("/cambiar-password")
def cambiar_password(datos: CambioPasswordData):
    try:
        conexion = mysql.connector.connect(**db_config)
        cursor = conexion.cursor(dictionary=True)

        # 1. Buscamos al usuario en la BD
        cursor.execute("SELECT id, password FROM usuarios WHERE usuario=%s", (datos.usuario,))
        usuario = cursor.fetchone()

        # 2. Verificamos que la contraseña temporal (actual) sea correcta
        if usuario and verificar_password(datos.password_actual, usuario['password']):
            
            # 3. Ciframos la NUEVA contraseña y la guardamos
            hashed_nuevo = obtener_hash_password(datos.password_nuevo)
            cursor.execute("UPDATE usuarios SET password=%s WHERE id=%s", (hashed_nuevo, usuario['id']))
            conexion.commit()
            
            cursor.close()
            conexion.close()
            return {"status": "éxito", "mensaje": "Contraseña actualizada correctamente"}
        else:
            cursor.close()
            conexion.close()
            raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))