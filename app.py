# ==========================================
# Imports and Configuration
# ==========================================

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    send_file,
    flash,
)
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import requests
import os
from flask_caching import Cache

# Import custom services
from services import audio_service
from services.conversation_service import ConversationService
from services.audio_service import text_to_wav, wav_to_mp3

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import atexit

# Initialize Flask app
app = Flask(__name__)
app.secret_key = "your_secret_key"

# Load environment variables from .env file
load_dotenv()

# Obtain API keys and model paths from environment variables
CLIMA_API_KEY = os.getenv("clima_api_key")
NOTICIAS_API_KEY = os.getenv("noticias_api_key")
MODEL_PATH = os.getenv("model_path")
VECTORDB_FOLDER = os.getenv("vectordb_path")
DOCUMENTS_FOLDER = os.getenv("documents_path")
SENTENCE_EMBEDDING_MODEL = os.getenv("sentence_embedding_model")
TOGETHER_API_KEY = os.getenv("together_api_key")

from utils.llm import ChatPDF

# Initialize the LLM (Large Language Model)
llm = None

def get_llm():
    """
    Function to initialize and return the LLM instance.
    """
    global llm
    llm = None
    if llm is None:
        llm = ChatPDF(
            DOCUMENTS_FOLDER,
            VECTORDB_FOLDER,
            MODEL_PATH,
            SENTENCE_EMBEDDING_MODEL,
            TOGETHER_API_KEY,
            temperature=0.3,
        )
        llm.start()
    return llm

# Configure caching
app.config["CACHE_TYPE"] = "SimpleCache"  # Use SimpleCache (stored in memory)
app.config["CACHE_DEFAULT_TIMEOUT"] = 6 * 3600  # Cache expires in 6 hours
cache = Cache(app)

conversation_service = ConversationService()

# ==========================================
# Database Setup
# ==========================================

def connect_db():
    """
    Connect to the SQLite database.
    """
    return sqlite3.connect("database.db")

def init_db():
    """
    Initialize the database with required tables.
    """
    with connect_db() as conn:
        # Users table
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        full_name TEXT,
                        email TEXT,
                        telefone TEXT UNIQUE NOT NULL,
                        endereco TEXT,
                        tamanho_fazenda REAL,
                        tipo_cultivo TEXT,
                        sistema_irrigacao TEXT,
                        numero_funcionarios INTEGER,
                        historico_pesticidas TEXT,
                        observacoes TEXT,
                        estado TEXT,
                        cidade TEXT,
                        chat_id TEXT
                        )""")

        # Auxiliary people table with 'role' field
        conn.execute("""CREATE TABLE IF NOT EXISTS auxiliary_people (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        telefone TEXT UNIQUE NOT NULL,  -- Cell phone number is unique
                        chat_id TEXT,
                        role TEXT NOT NULL,  -- 'gerente' or 'motorista'
                        FOREIGN KEY(user_id) REFERENCES users(id)
                        )""")

        # Machines table with 'motorista_id' field
        conn.execute("""CREATE TABLE IF NOT EXISTS machines (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        motorista_id INTEGER,  -- Single driver
                        model TEXT NOT NULL,
                        serial_number TEXT,
                        purchase_date DATE,
                        other_details TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(motorista_id) REFERENCES auxiliary_people(id)
                        )""")

        # Machine managers relation table
        conn.execute("""CREATE TABLE IF NOT EXISTS machine_managers (
                        machine_id INTEGER NOT NULL,
                        gerente_id INTEGER NOT NULL,
                        PRIMARY KEY(machine_id, gerente_id),
                        FOREIGN KEY(machine_id) REFERENCES machines(id),
                        FOREIGN KEY(gerente_id) REFERENCES auxiliary_people(id)
                        )""")

        # Maintenance task templates table
        conn.execute('''CREATE TABLE IF NOT EXISTS maintenance_task_templates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        model TEXT NOT NULL,
                        cidade TEXT NOT NULL,
                        estado TEXT NOT NULL,
                        date TEXT NOT NULL,
                        tasks TEXT
                        )''')

        # Maintenance tasks assigned to drivers
        conn.execute('''CREATE TABLE IF NOT EXISTS maintenance_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        motorista_id INTEGER NOT NULL,
                        date TEXT NOT NULL,
                        FOREIGN KEY (motorista_id) REFERENCES auxiliary_people(id)
                        )''')

        # New table for individual maintenance task items
        conn.execute('''CREATE TABLE IF NOT EXISTS maintenance_task_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        maintenance_task_id INTEGER NOT NULL,
                        task TEXT NOT NULL,
                        status TEXT DEFAULT 'pendente',
                        FOREIGN KEY (maintenance_task_id) REFERENCES maintenance_tasks(id)
                        )''')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS conversation_states (
                    chat_id TEXT PRIMARY KEY,
                    state TEXT,
                    new_aux_name TEXT,
                    new_aux_email TEXT,
                    new_aux_phone TEXT
                    )''')
        
        conn.commit()

# ==========================================
# Scheduler Functions
# ==========================================

def start_scheduler():
    """
    Start the background scheduler for generating maintenance tasks daily.
    """
    scheduler = BackgroundScheduler()
    job = scheduler.add_job(
        func=generate_maintenance_tasks,
        trigger="interval",
        days=1,
        next_run_time=datetime.now(),
    )
    scheduler.start()
    print(f"Job ID: {job.id}, Próxima execução: {job.next_run_time}")
    # Safely shut down the scheduler on exit
    atexit.register(lambda: scheduler.shutdown())

# ==========================================
# Utility Functions
# ==========================================

@cache.cached(timeout=6 * 3600, key_prefix="lat_lon_{city}_{state}")
def get_lat_lon(city, state, api_key=CLIMA_API_KEY):
    """
    Get latitude and longitude for a given city and state using OpenWeatherMap API.
    """
    url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},{state},BR&limit=1&appid={api_key}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data:
            return data[0]["lat"], data[0]["lon"]  # Return latitude and longitude
    return None, None

@cache.cached(timeout=6 * 3600, key_prefix="weather_{lat}_{lon}")
def get_weather(lat, lon, api_key=CLIMA_API_KEY):
    """
    Get weather information for given latitude and longitude.
    """
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&lang=pt&units=metric"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        if "main" in data and "weather" in data:
            weather = {
                "temperature": data["main"]["temp"],
                "description": data["weather"][0]["description"],
            }
            return weather
    else:
        print(f"Erro ao obter o clima: {response.status_code} - {response.text}")

    return None  # Return None or some default value

def get_news(city, state, api_key=NOTICIAS_API_KEY):
    """
    Get top headlines from NewsAPI.
    """
    url = f"https://newsapi.org/v2/top-headlines?country=br&apiKey={api_key}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        print(data)
        return data["articles"][:5]  # Return the first 5 news articles
    return None

def get_auxiliaries(user_id):
    """
    Retrieve auxiliary people associated with a user.
    """
    with connect_db() as conn:
        auxiliaries = conn.execute(
            """
            SELECT name, email, telefone, chat_id, role
            FROM auxiliary_people
            WHERE user_id = ?
        """,
            (user_id,),
        ).fetchall()

    return [
        {
            "name": aux[0],
            "email": aux[1],
            "telefone": aux[2],
            "chat_id": aux[3],
            "role": aux[4],
        }
        for aux in auxiliaries
    ]

def get_auxiliaries_by_role(user_id):
    """
    Retrieve auxiliary people by role ('motorista' or 'gerente').
    """
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row

        motoristas = conn.execute(
            """
            SELECT id, name FROM auxiliary_people WHERE user_id = ? AND role = 'motorista'
        """,
            (user_id,),
        ).fetchall()

        gerentes = conn.execute(
            """
            SELECT id, name FROM auxiliary_people WHERE user_id = ? AND role = 'gerente'
        """,
            (user_id,),
        ).fetchall()

    return {
        "motoristas": [
            {"id": motorista["id"], "name": motorista["name"]}
            for motorista in motoristas
        ],
        "gerentes": [
            {"id": gerente["id"], "name": gerente["name"]} for gerente in gerentes
        ],
    }

# ==========================================
# Machine Models and Helper Functions
# ==========================================

# List of available machine models
MACHINE_MODELS = {
    "R Series": ["8260R", "8285R", "8310R", "8335R", "8360R"],
    "J Series 7200": ["7200J", "7215J", "7230J"],
    "M Series": ["6155M", "6175M", "6195M"],
    #"J Series 6135": ["6135J", "6150J", "6170J", "6190J", "6210J"],
    #"J Series 6110": ["6110J", "6125J", "6130J"],
    #"M Series 4040": ["M4040", "M4030"],
    #"Series 4730/4830": ["4730", "4830"],
}

def infer_series_from_model(model):
    """
    Return the machine series based on the model.
    """
    for series, models in MACHINE_MODELS.items():
        if model in models:
            return series
    return None

# ==========================================
# Maintenance Task Generation and Assignment
# ==========================================

import json
from datetime import datetime

import ast
from datetime import datetime

def generate_maintenance_tasks():
    today_date = str(datetime.now().date())
    with connect_db() as conn:
        existing_tasks = conn.execute('''
            SELECT 1 FROM maintenance_task_templates WHERE date = ?
        ''', (today_date,)).fetchone()

    if existing_tasks:
        print("As tarefas de manutenção já foram geradas para hoje.")
        return

    with connect_db() as conn:
        combinations = conn.execute('''
            SELECT DISTINCT m.model, u.cidade, u.estado
            FROM machines m
            JOIN users u ON m.user_id = u.id
        ''').fetchall()

    machine_series_manuals = {
        'R Series': 'manualOperador_7200J_7215J_7230J.pdf',
        'J Series 7200': 'manualOperador_7200J_7215J_7230J.pdf',
        'M Series': 'manualOperador_7200J_7215J_7230J.pdf',
    }

    for combo in combinations:
        model, cidade, estado = combo
        print(model, cidade, estado)

        series = infer_series_from_model(model)

        if series in machine_series_manuals:
            manual = machine_series_manuals[series]

            try:
                llm = get_llm()
                document_names = [manual]
                llm.create_qa_session(document_names)

                lat, lon = get_lat_lon(cidade, estado)
                description = "Informações climáticas indisponíveis"
                temperature = "N/A"

                if lat and lon:
                    weather = get_weather(lat, lon)
                    if weather:
                        description = weather.get("description", "não disponível")
                        temperature = weather.get("temperature", "não disponível")

                prompt = f"""
                -{description} com temperatura de {temperature}°C
                """

                response = llm.qa.invoke(prompt)["result"]
                print("Resposta do modelo:", response)

                try:
                    maintenance_tasks = ast.literal_eval(response.strip())
                    if not isinstance(maintenance_tasks, list):
                        maintenance_tasks = None
                        print("A resposta não é uma lista válida.")
                except Exception as e:
                    maintenance_tasks = None
                    print(f"Erro ao avaliar a resposta: {e}")

            except Exception as e:
                maintenance_tasks = None
                print(f"Erro ao gerar tarefas para o modelo {model}: {e}")

            if maintenance_tasks is not None:
                with connect_db() as conn:
                    conn.execute('''
                        INSERT INTO maintenance_task_templates (model, cidade, estado, date, tasks)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (model, cidade, estado, today_date, str(maintenance_tasks)))
                    conn.commit()

    print("Tarefas de manutenção geradas com sucesso.")



def assign_tasks_to_motoristas():
    """
    Assign maintenance tasks to drivers based on machine model and location.
    """
    today_date = str(datetime.now().date())

    # Get all drivers
    with connect_db() as conn:
        motoristas = conn.execute('''
            SELECT a.id as motorista_id, a.name as motorista_name, a.telefone, u.cidade, u.estado
            FROM auxiliary_people a
            JOIN users u ON a.user_id = u.id
            WHERE a.role = 'motorista'
        ''').fetchall()

    for motorista in motoristas:
        motorista_id = motorista[0]
        motorista_name = motorista[1]
        motorista_telefone = motorista[2]
        cidade = motorista[3]
        estado = motorista[4]

        # Get models of machines the driver operates
        with connect_db() as conn:
            models = conn.execute('''
                SELECT DISTINCT m.model
                FROM machines m
                WHERE m.motorista_id = ?
            ''', (motorista_id,)).fetchall()

        for model_row in models:
            model = model_row[0]

            # Get maintenance tasks for the model and location
            with connect_db() as conn:
                tasks_row = conn.execute('''
                    SELECT tasks FROM maintenance_task_templates
                    WHERE model = ? AND cidade = ? AND estado = ? AND date = ?
                ''', (model, cidade, estado, today_date)).fetchone()
            if tasks_row:
                maintenance_tasks = eval(tasks_row[0])

                # Store tasks assigned to the driver
                with connect_db() as conn:
                    # Insert into maintenance_tasks and get the ID
                    cursor = conn.execute('''
                        INSERT INTO maintenance_tasks (motorista_id, date)
                        VALUES (?, ?)
                    ''', (motorista_id, today_date))
                    maintenance_task_id = cursor.lastrowid

                    # Insert individual tasks into maintenance_task_items
                    for task in maintenance_tasks:
                        conn.execute('''
                            INSERT INTO maintenance_task_items (maintenance_task_id, task)
                            VALUES (?, ?)
                        ''', (maintenance_task_id, task))

                    conn.commit()

                # Send the checklist to the driver
                send_checklist_to_motorista(motorista_name, motorista_telefone, maintenance_tasks)
            else:
                print(f"Não há tarefas de manutenção para o motorista {motorista_name} com o modelo {model} em {cidade}, {estado}.")

    print("Tarefas de manutenção atribuídas aos motoristas.")


@app.route("/assign_tasks", methods=["POST"])
def assign_tasks():
    """
    Route to assign maintenance tasks to drivers.
    """
    assign_tasks_to_motoristas()
    flash("Tarefas de manutenção atribuídas aos motoristas com sucesso!")
    return redirect(url_for("dashboard"))

def send_checklist_to_motorista(motorista_name, motorista_telefone, maintenance_tasks):
    """
    Send the maintenance checklist to the driver.
    """
    # Retrieve the driver's chat_id based on their cell phone number
    with connect_db() as conn:
        motorista_info = conn.execute('''
            SELECT chat_id FROM auxiliary_people
            WHERE telefone = ?
        ''', (motorista_telefone,)).fetchone()
    chat_id = motorista_info[0] if motorista_info else None

    if not chat_id:
        print(f"Chat ID não cadastrado para o motorista {motorista_name}")
        return

    # Build the message with the maintenance checklist
    message = f"Olá {motorista_name},\n\nAqui está o checklist de manutenção preventiva para hoje:\n\n"
    for idx, task in enumerate(maintenance_tasks, start=1):
        message += f"{idx}. {task}\n"

    message += "\nPara marcar uma tarefa como concluída, responda com o número da tarefa seguido de 'concluída'. Por exemplo: 'Tarefa 1 concluída'"

    try:
        conversation_service = ConversationService()
        # Send text message to the driver's chat_id
        response_text = conversation_service.send_message(message, chat_id)
        print(f"Mensagem de texto enviada para {motorista_name} (Chat ID: {chat_id})")

        # Generate audio from the message
        wav_file_path = text_to_wav(message)
        if wav_file_path:
            # Convert WAV to MP3
            mp3_file_path = wav_to_mp3(wav_file_path)

            # Send audio message to the driver's chat_id
            response_audio = conversation_service.send_message(
                message=None,
                recipient=chat_id,
                message_type="media",
                media=mp3_file_path
            )
            print(f"Áudio enviado para {motorista_name} (Chat ID: {chat_id})")
        else:
            print(f"Erro ao gerar o áudio para {motorista_name}")

    except Exception as e:
        print(f"Erro ao enviar para {motorista_name}: {e}")


# ==========================================
# Route Definitions - User Authentication
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():
    """
    User login route.
    """
    error_message = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        with connect_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()

            if user and check_password_hash(user[2], password):
                session["user_id"] = user[0]
                session["username"] = user[1]
                return redirect(url_for("dashboard"))
            else:
                error_message = "Credenciais inválidas!"

    return render_template("login.html", error_message=error_message)

@app.route("/register", methods=["GET", "POST"])
def register():
    """
    User registration route.
    """
    error_message = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]  # Nova variável
        full_name = request.form["full_name"]
        email = request.form["email"]
        telefone = request.form["telefone"]
        estado = request.form["estado"]
        cidade = request.form["cidade"]

        # Verificar se as senhas são iguais
        if password != confirm_password:
            error_message = "As senhas não correspondem. Por favor, tente novamente."
            return render_template("register.html", error_message=error_message)

        hashed_password = generate_password_hash(password)

        # Verificar se todos os campos foram preenchidos
        if not all([username, password, full_name, email, telefone, estado, cidade]):
            error_message = "Por favor, preencha todos os campos."
            return render_template("register.html", error_message=error_message)

        with connect_db() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO users (username, password, full_name, email, telefone, estado, cidade)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        hashed_password,
                        full_name,
                        email,
                        telefone,
                        estado,
                        cidade,
                    ),
                )
                conn.commit()
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error_message = "Usuário já existe ou dados inválidos!"
    
    else:
        error_message = None

    # Carregar a lista de estados para o formulário
    estados = requests.get(
        "https://servicodados.ibge.gov.br/api/v1/localidades/estados"
    ).json()

    return render_template("register.html", error_message=error_message, estados=estados)


@app.route("/logout")
def logout():
    """
    User logout route.
    """
    session.pop("user_id", None)
    session.pop("username", None)
    return redirect(url_for("login"))

# ==========================================
# Route Definitions - User Profile
# ==========================================

@app.route("/dados_pessoais", methods=["GET", "POST"])
def dados_pessoais():
    """
    Route to view and update personal data.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        # Get form data
        full_name = request.form["full_name"]
        endereco = request.form["endereco"]
        tamanho_fazenda = request.form["tamanho_fazenda"]
        tipo_cultivo = request.form["tipo_cultivo"]
        sistema_irrigacao = request.form["sistema_irrigacao"]
        numero_funcionarios = request.form["numero_funcionarios"]
        historico_pesticidas = request.form["historico_pesticidas"]
        observacoes = request.form["observacoes"]

        # Update data in the database
        with connect_db() as conn:
            conn.execute(
                """
                UPDATE users
                SET full_name = ?, endereco = ?, tamanho_fazenda = ?,
                    tipo_cultivo = ?, sistema_irrigacao = ?, numero_funcionarios = ?,
                    historico_pesticidas = ?, observacoes = ?
                WHERE id = ?
            """,
                (
                    full_name,
                    endereco,
                    tamanho_fazenda,
                    tipo_cultivo,
                    sistema_irrigacao,
                    numero_funcionarios,
                    historico_pesticidas,
                    observacoes,
                    user_id,
                ),
            )
            conn.commit()

        return redirect(url_for("dashboard"))

    # If GET, fetch existing data
    with connect_db() as conn:
        user = conn.execute(
            """
            SELECT full_name, endereco, tamanho_fazenda,
                   tipo_cultivo, sistema_irrigacao, numero_funcionarios,
                   historico_pesticidas, observacoes
            FROM users
            WHERE id = ?
        """,
            (user_id,),
        ).fetchone()

    return render_template(
        "cadastro/dados_pessoais.html",
        full_name=user[0],
        endereco=user[1],
        tamanho_fazenda=user[2],
        tipo_cultivo=user[3],
        sistema_irrigacao=user[4],
        numero_funcionarios=user[5],
        historico_pesticidas=user[6],
        observacoes=user[7],
    )


@app.route("/profile", methods=["GET", "POST"])
def profile():
    """
    User profile route to view and update profile information.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        # Get data from the form
        full_name = request.form["full_name"]
        email = request.form["email"]
        machine1 = int(request.form["machine1"])
        machine2 = int(request.form["machine2"])
        machine3 = int(request.form["machine3"])
        machine4 = int(request.form["machine4"])

        # Save information to the database
        with connect_db() as conn:
            # Update user information
            conn.execute(
                """
                UPDATE users
                SET full_name = ?, email = ?, machine1 = ?, machine2 = ?, machine3 = ?, machine4 = ?
                WHERE id = ?
            """,
                (full_name, email, machine1, machine2, machine3, machine4, user_id),
            )
            conn.commit()

            # Remove existing auxiliary people
            conn.execute("DELETE FROM auxiliary_people WHERE user_id = ?", (user_id,))

            # Add new auxiliary people
            auxiliary_names = {
                key: value
                for key, value in request.form.items()
                if key.startswith("auxiliary_name_")
            }
            auxiliary_emails = {
                key: value
                for key, value in request.form.items()
                if key.startswith("auxiliary_email_")
            }

            for key in auxiliary_names:
                index = key.split("_")[-1]
                name = auxiliary_names[key]
                email_key = f"auxiliary_email_{index}"
                email_aux = auxiliary_emails.get(email_key)

                if name and email_aux:
                    conn.execute(
                        "INSERT INTO auxiliary_people (user_id, name, email) VALUES (?, ?, ?)",
                        (user_id, name, email_aux),
                    )
            conn.commit()

        return redirect(url_for("dashboard"))

    # If GET, load user data
    with connect_db() as conn:
        user = conn.execute(
            "SELECT full_name, email, machine1, machine2, machine3, machine4 FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        # Load auxiliary people
        auxiliaries = conn.execute(
            "SELECT name, email FROM auxiliary_people WHERE user_id = ?", (user_id,)
        ).fetchall()

    # Pass user data and auxiliary people to the template
    return render_template(
        "profile.html",
        full_name=user[0],
        email=user[1],
        machine1=user[2],
        machine2=user[3],
        machine3=user[4],
        machine4=user[5],
        auxiliaries=auxiliaries,
    )

# ==========================================
# Route Definitions - Dashboard and Misc
# ==========================================

@app.route("/dashboard")
def dashboard():
    """
    Dashboard route displaying user information and maintenance tasks.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Fetch user's location data
    with connect_db() as conn:
        user = conn.execute(
            "SELECT cidade, estado FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    cidade = user[0]
    estado = user[1]

    if not cidade or not estado:
        # If no location information, display a friendly message
        missing_location_message = f"""
            Você ainda não cadastrou sua localização. Ao adicionar sua cidade e estado, você terá acesso
            a informações climáticas personalizadas e relevantes para suas atividades agrícolas.
            <a href='{url_for("dados_pessoais")}'>Clique aqui para cadastrar sua localização</a>.
        """

        return render_template(
            "dashboard.html",
            username=session["username"],
            missing_location_message=missing_location_message,
            weather=None,
            noticias=None,
            maintenance_tasks=None,
        )

    # Fetch maintenance tasks assigned to drivers associated with the user
    today_date = str(datetime.now().date())
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row
        maintenance_tasks = conn.execute(
            """
            SELECT mti.task, mti.status, a.name as motorista_name
            FROM maintenance_task_items mti
            JOIN maintenance_tasks mt ON mti.maintenance_task_id = mt.id
            JOIN auxiliary_people a ON mt.motorista_id = a.id
            JOIN machines m ON a.id = m.motorista_id
            WHERE m.user_id = ? AND mt.date = ?
            """,
            (user_id, today_date),
        ).fetchall()

    # Get weather and news information
    lat, lon = get_lat_lon(cidade, estado)
    weather = get_weather(lat, lon) if lat and lon else None
    noticias = get_news(cidade, estado)

    return render_template(
        "dashboard.html",
        username=session["username"],
        cidade=cidade,
        estado=estado,
        weather=weather,
        noticias=noticias,
        maintenance_tasks=maintenance_tasks,
    )


@app.route("/settings")
def settings():
    """
    Settings route.
    """
    return render_template("settings.html")

@app.route("/")
def index():
    """
    Home page route.
    """
    return render_template("index.html")

# ==========================================
# Route Definitions - Machine Management
# ==========================================

@app.route("/machines")
def list_machines():
    """
    List all machines associated with the user.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row

        # Get machines with drivers
        machines = conn.execute(
            """
            SELECT m.*, a.name as motorista_name
            FROM machines m
            LEFT JOIN auxiliary_people a ON m.motorista_id = a.id
            WHERE m.user_id = ?
        """,
            (user_id,),
        ).fetchall()

        # Get managers for each machine
        machine_managers = conn.execute(
            """
            SELECT mm.machine_id, ap.name as gerente_name
            FROM machine_managers mm
            JOIN auxiliary_people ap ON mm.gerente_id = ap.id
            WHERE ap.user_id = ?
        """,
            (user_id,),
        ).fetchall()

        # Organize managers by machine
        gerentes_por_maquina = {}
        for manager in machine_managers:
            machine_id = manager["machine_id"]
            if machine_id not in gerentes_por_maquina:
                gerentes_por_maquina[machine_id] = []
            gerentes_por_maquina[machine_id].append(manager["gerente_name"])

    # Pass machines and managers to the template
    return render_template(
        "machines/list.html",
        machines=machines,
        gerentes_por_maquina=gerentes_por_maquina,
    )

@app.route("/machines/add", methods=["GET", "POST"])
def add_machine():
    """
    Add a new machine.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        model = request.form["model"]
        serial_number = request.form["serial_number"]
        purchase_date = request.form["purchase_date"]
        other_details = request.form["other_details"]
        motorista_id = request.form.get("motorista_id")
        gerente_ids = request.form.getlist("gerente_ids")  # List of manager IDs

        if not model:
            flash("O campo modelo é obrigatório.")
            return redirect(url_for("add_machine"))

        # Verify if the selected model is valid
        valid_models = [model for models in MACHINE_MODELS.values() for model in models]
        if model not in valid_models:
            flash("Modelo inválido selecionado.")
            return redirect(url_for("add_machine"))

        with connect_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO machines (user_id, model, serial_number, purchase_date, other_details, motorista_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    user_id,
                    model,
                    serial_number,
                    purchase_date,
                    other_details,
                    motorista_id,
                ),
            )
            machine_id = cursor.lastrowid

            # Insert managers into machine_managers table
            for gerente_id in gerente_ids:
                conn.execute(
                    """
                    INSERT INTO machine_managers (machine_id, gerente_id)
                    VALUES (?, ?)
                """,
                    (machine_id, gerente_id),
                )

            conn.commit()

        flash("Máquina adicionada com sucesso!")
        return redirect(url_for("list_machines"))

    # Get drivers and managers to display on the page
    auxiliaries = get_auxiliaries_by_role(user_id)
    return render_template(
        "machines/add.html", auxiliaries=auxiliaries, machine_models=MACHINE_MODELS
    )

@app.route("/machines/edit/<int:machine_id>", methods=["GET", "POST"])
def edit_machine(machine_id):
    """
    Edit an existing machine.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with connect_db() as conn:
        conn.row_factory = sqlite3.Row

        # Get machine details
        machine = conn.execute(
            "SELECT * FROM machines WHERE id = ? AND user_id = ?", (machine_id, user_id)
        ).fetchone()
        if not machine:
            flash("Máquina não encontrada.")
            return redirect(url_for("list_machines"))

        # Get IDs of managers associated with the machine
        gerente_ids = [
            row["gerente_id"]
            for row in conn.execute(
                """
            SELECT gerente_id FROM machine_managers WHERE machine_id = ?
        """,
                (machine_id,),
            ).fetchall()
        ]

        if request.method == "POST":
            model = request.form["model"]
            serial_number = request.form["serial_number"]
            purchase_date = request.form["purchase_date"]
            other_details = request.form["other_details"]
            motorista_id = request.form.get("motorista_id")
            novos_gerente_ids = request.form.getlist("gerente_ids")

            if not model:
                flash("O campo modelo é obrigatório.")
                return redirect(url_for("edit_machine", machine_id=machine_id))

            # Update machine details
            conn.execute(
                """
                UPDATE machines
                SET model = ?, serial_number = ?, purchase_date = ?, other_details = ?, motorista_id = ?
                WHERE id = ? AND user_id = ?
            """,
                (
                    model,
                    serial_number,
                    purchase_date,
                    other_details,
                    motorista_id,
                    machine_id,
                    user_id,
                ),
            )

            # Update associated managers
            conn.execute(
                "DELETE FROM machine_managers WHERE machine_id = ?", (machine_id,)
            )
            for gerente_id in novos_gerente_ids:
                conn.execute(
                    """
                    INSERT INTO machine_managers (machine_id, gerente_id)
                    VALUES (?, ?)
                """,
                    (machine_id, gerente_id),
                )

            conn.commit()

            flash("Máquina atualizada com sucesso!")
            return redirect(url_for("list_machines"))

    # Get drivers and managers to display
    auxiliaries = get_auxiliaries_by_role(user_id)

    # Send the list of associated manager IDs to the template
    return render_template(
        "machines/edit.html",
        machine=machine,
        auxiliaries=auxiliaries,
        gerente_ids=gerente_ids,
        machine_models=MACHINE_MODELS,
    )

@app.route("/machines/delete/<int:machine_id>", methods=["POST"])
def delete_machine(machine_id):
    """
    Delete a machine.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with connect_db() as conn:
        conn.execute(
            "DELETE FROM machines WHERE id = ? AND user_id = ?", (machine_id, user_id)
        )
        conn.commit()

    flash("Máquina excluída com sucesso!")
    return redirect(url_for("list_machines"))

# ==========================================
# Route Definitions - Auxiliary People Management
# ==========================================

@app.route("/pessoas_auxiliares", methods=["GET", "POST"])
def pessoas_auxiliares():
    """
    Manage auxiliary people (drivers and managers).
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        try:
            # Remove all existing auxiliary people for the current user
            with connect_db() as conn:
                conn.execute(
                    "DELETE FROM auxiliary_people WHERE user_id = ?", (user_id,)
                )

                # Add new auxiliary people with their respective fields
                auxiliary_names = {
                    key: value
                    for key, value in request.form.items()
                    if key.startswith("auxiliary_name_")
                }
                auxiliary_emails = {
                    key: value
                    for key, value in request.form.items()
                    if key.startswith("auxiliary_email_")
                }
                auxiliary_telefonees = {
                    key: value
                    for key, value in request.form.items()
                    if key.startswith("auxiliary_telefone_")
                }
                auxiliary_chat_ids = {
                    key: value
                    for key, value in request.form.items()
                    if key.startswith("auxiliary_chat_id_")
                }
                auxiliary_roles = {
                    key: value
                    for key, value in request.form.items()
                    if key.startswith("auxiliary_role_")
                }

                for key in auxiliary_names:
                    index = key.split("_")[-1]
                    name = auxiliary_names[key]
                    email_key = f"auxiliary_email_{index}"
                    email_aux = auxiliary_emails.get(email_key)
                    telefone_key = f"auxiliary_telefone_{index}"
                    telefone_aux = auxiliary_telefonees.get(telefone_key)
                    chat_id_key = f"auxiliary_chat_id_{index}"
                    chat_id_aux = auxiliary_chat_ids.get(chat_id_key)
                    role_key = f"auxiliary_role_{index}"
                    role = auxiliary_roles.get(role_key)

                    if name and email_aux and telefone_aux and role:
                        conn.execute(
                            """
                            INSERT INTO auxiliary_people (user_id, name, email, telefone, chat_id, role)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, name, email_aux, telefone_aux, chat_id_aux, role),
                        )
                conn.commit()

            success_message = "Pessoas auxiliares atualizadas com sucesso!"
            # Retrieve auxiliary people again to display
            auxiliaries = get_auxiliaries(user_id)
            return render_template(
                "cadastro/pessoas_auxiliares.html",
                auxiliaries=auxiliaries,
                success_message=success_message,
            )
        except Exception as e:
            error_message = "Ocorreu um erro ao atualizar as pessoas auxiliares. Por favor, tente novamente."
            auxiliaries = get_auxiliaries(user_id)
            return render_template(
                "cadastro/pessoas_auxiliares.html",
                auxiliaries=auxiliaries,
                error_message=error_message,
            )

    # If GET, fetch existing auxiliary people
    auxiliaries = get_auxiliaries(user_id)
    return render_template("cadastro/pessoas_auxiliares.html", auxiliaries=auxiliaries)

# ==========================================
# Route Definitions - Audio Conversion and Messaging
# ==========================================

@app.route("/transformar_em_audio", methods=["POST"])
def transformar_em_audio():
    """
    Convert text input to audio and return the audio file.
    """
    text = request.form["text_input"]

    # Call the text-to-speech conversion function
    wav_file = audio_service.text_to_wav(text)

    if wav_file:
        return send_file(wav_file, as_attachment=True)
    else:
        return "Erro ao gerar o áudio.", 500

@app.route("/send_report/<message_type>/<recipient>", methods=["POST"])
def send_report(message_type, recipient):
    """
    Send a report or checklist to a recipient via Telegram.
    """
    # Basic validation
    if not recipient:
        flash("Por favor, insira o chat ID ou username do Telegram.")
        return redirect(url_for("dashboard"))

    # Define the message based on the type
    if message_type == "relatorio":
        message = "Aqui está o relatório solicitado."
    elif message_type == "checklist":
        message = "Aqui está o checklist solicitado."
    else:
        flash("Tipo de mensagem inválido.")
        return redirect(url_for("dashboard"))

    conversation_service = ConversationService()

    try:
        # Send message via Telegram
        response = conversation_service.send_message(message, recipient)
        flash(
            f"{message_type.capitalize()} enviado com sucesso para {recipient} via Telegram!"
        )
        print(response)
    except Exception as e:
        flash(f"Erro ao enviar {message_type}: {e}")

    return redirect(url_for("dashboard"))

import re

STATE_INITIAL = 'initial'
STATE_COLLECT_NAME = 'collect_name'
STATE_COLLECT_EMAIL = 'collect_email'
STATE_COLLECT_PHONE = 'collect_phone'
STATE_COLLECT_ROLE = 'collect_role'

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.get_json()
    chat_id = None
    text = ''
    phone_number = ''
    #print(update)
    if 'message' in update:
        message = update['message']
        chat_id = str(message['chat']['id'])

        if 'text' in message:
            text = message['text'].strip()
        elif 'contact' in message:
            # User sent their contact info
            contact = message['contact']
            phone_number = contact.get('phone_number', '').strip()

        with connect_db() as conn:
            conn.row_factory = sqlite3.Row

            state_row = conn.execute(
                "SELECT * FROM conversation_states WHERE chat_id = ?",
                (chat_id,)
            ).fetchone()
            
            if state_row:
                user_state = state_row['state']
            else:
                user_state = STATE_INITIAL

            # Verifica se o chat_id já está na tabela 'users'
            user = conn.execute(
                "SELECT * FROM users WHERE chat_id = ?",
                (chat_id,)
            ).fetchone()

            if user:
                print(user_state)
                if user_state == STATE_INITIAL:
                    response_message = "Você gostaria de adicionar uma nova pessoa auxiliar? Por favor, envie o nome da pessoa."
                    # Inserir ou atualizar o estado no banco de dados
                    conn.execute("""
                        INSERT INTO conversation_states (chat_id, state)
                        VALUES (?, ?)
                        ON CONFLICT(chat_id) DO UPDATE SET state=excluded.state;
                    """, (chat_id, STATE_COLLECT_NAME))
                    conn.commit()
                    conversation_service.send_message(response_message, chat_id)

                elif user_state == STATE_COLLECT_NAME:
                    # Armazena o nome no banco de dados
                    conn.execute("""
                        UPDATE conversation_states SET new_aux_name = ?, state = ?
                        WHERE chat_id = ?;
                    """, (text, STATE_COLLECT_EMAIL, chat_id))
                    conn.commit()
                    response_message = "Por favor, envie o email da pessoa."
                    conversation_service.send_message(response_message, chat_id)

                elif user_state == STATE_COLLECT_EMAIL:
                    # Armazena o email no banco de dados
                    conn.execute("""
                        UPDATE conversation_states SET new_aux_email = ?, state = ?
                        WHERE chat_id = ?;
                    """, (text, STATE_COLLECT_PHONE, chat_id))
                    conn.commit()
                    response_message = "Por favor, envie o número de telefone da pessoa."
                    conversation_service.send_message(response_message, chat_id)

                elif user_state == STATE_COLLECT_PHONE:
                    # Armazena o telefone no banco de dados
                    conn.execute("""
                        UPDATE conversation_states SET new_aux_phone = ?, state = ?
                        WHERE chat_id = ?;
                    """, (text, STATE_COLLECT_ROLE, chat_id))
                    conn.commit()
                    response_message = "Por favor, envie a função da pessoa (gerente ou motorista)."
                    conversation_service.send_message(response_message, chat_id)

                elif user_state == STATE_COLLECT_ROLE:
                    if text.lower() in ['gerente', 'motorista']:
                        # Recupera os dados armazenados
                        state_data = conn.execute(
                            "SELECT * FROM conversation_states WHERE chat_id = ?",
                            (chat_id,)
                        ).fetchone()
                        new_aux_name = state_data['new_aux_name']
                        new_aux_email = state_data['new_aux_email']
                        new_aux_phone = state_data['new_aux_phone']
                        new_aux_role = text.lower()

                        # Insere a pessoa auxiliar no banco de dados
                        conn.execute(
                            """
                            INSERT INTO auxiliary_people (user_id, name, email, telefone, role)
                            VALUES (?, ?, ?, ?, ?)
                            """, 
                            (user['id'], new_aux_name, new_aux_email, new_aux_phone, new_aux_role)
                        )
                        conn.commit()

                        # Remove o estado do usuário
                        conn.execute(
                            "DELETE FROM conversation_states WHERE chat_id = ?",
                            (chat_id,)
                        )
                        conn.commit()

                        response_message = f"Pessoa auxiliar '{new_aux_name}' adicionada com sucesso!"
                        conversation_service.send_message(response_message, chat_id)
                    else:
                        response_message = "Função inválida. Por favor, envie 'gerente' ou 'motorista'."
                        conversation_service.send_message(response_message, chat_id)
                else:
                    # Caso o estado não seja reconhecido, reinicia o processo
                    conn.execute(
                        "DELETE FROM conversation_states WHERE chat_id = ?",
                        (chat_id,)
                    )
                    conn.commit()
                    response_message = "Ocorreu um erro. Vamos reiniciar o processo. Por favor, envie o nome da pessoa auxiliar."
                    conn.execute("""
                        INSERT INTO conversation_states (chat_id, state)
                        VALUES (?, ?)
                        ON CONFLICT(chat_id) DO UPDATE SET state=excluded.state;
                    """, (chat_id, STATE_COLLECT_NAME))
                    conn.commit()
                    conversation_service.send_message(response_message, chat_id)
            else:
                # Check if chat_id exists in 'auxiliary_people' table
                motorista = conn.execute(
                    "SELECT * FROM auxiliary_people WHERE chat_id = ?",
                    (chat_id,)
                ).fetchone()

                if motorista:
                    # Existing motorista flow
                    motorista_id = motorista['id']
                    today_date = str(datetime.now().date())
                    maintenance_task = conn.execute(
                        "SELECT * FROM maintenance_tasks WHERE motorista_id = ? AND date = ?",
                        (motorista_id, today_date)
                    ).fetchone()

                    if maintenance_task:
                        maintenance_task_id = maintenance_task['id']
                        tasks = conn.execute(
                            "SELECT * FROM maintenance_task_items WHERE maintenance_task_id = ?",
                            (maintenance_task_id,)
                        ).fetchall()

                        match = re.match(r'Tarefa (\d+) concluída', text, re.IGNORECASE)
                        if match:
                            task_number = int(match.group(1))
                            if 1 <= task_number <= len(tasks):
                                task_item = tasks[task_number - 1]
                                conn.execute(
                                    "UPDATE maintenance_task_items SET status = ? WHERE id = ?",
                                    ('concluída', task_item['id'])
                                )
                                conn.commit()
                                response_message = f"Tarefa {task_number} marcada como concluída."
                                conversation_service.send_message(response_message, chat_id)

                                # Check if all tasks are completed
                                todas_concluidas = conn.execute(
                                    "SELECT COUNT(*) FROM maintenance_task_items WHERE maintenance_task_id = ? AND status = 'pendente'",
                                    (maintenance_task_id,)
                                ).fetchone()[0] == 0
                                if todas_concluidas:
                                    gerente = conn.execute(
                                        """
                                        SELECT ap.id as gerente_id
                                        FROM machine_managers mm
                                        JOIN auxiliary_people ap ON mm.gerente_id = ap.id
                                        JOIN machines m ON mm.machine_id = m.id
                                        WHERE m.motorista_id = ?
                                        """, (motorista_id,)
                                    ).fetchone()

                                    if gerente:
                                        gerente_id = gerente['gerente_id']
                                        send_gerente_report(gerente_id)
                            else:
                                response_message = "Número de tarefa inválido."
                                conversation_service.send_message(response_message, chat_id)
                        else:
                            response_message = ("Mensagem não reconhecida. Para marcar uma tarefa como concluída, "
                                                "responda com o número da tarefa seguido de 'concluída'. "
                                                "Por exemplo: 'Tarefa 1 concluída'")
                            conversation_service.send_message(response_message, chat_id)
                    else:
                        response_message = "Nenhuma tarefa de manutenção atribuída para hoje."
                        conversation_service.send_message(response_message, chat_id)
                else:
                    # Chat ID not found, handle phone number
                    if phone_number:
                        # Remove non-digit characters
                        phone_number_digits = re.sub(r'\D', '', phone_number)[2:]
                        print(phone_number_digits)

                        # Check in 'user' table
                        user_by_phone = conn.execute(
                            "SELECT * FROM users WHERE telefone = ?",
                            (phone_number_digits,)
                        ).fetchone()

                        if user_by_phone:
                            conn.execute(
                                "UPDATE users SET chat_id = ? WHERE id = ?",
                                (chat_id, user_by_phone['id'])
                            )
                            conn.commit()
                            response_message = f"Chat ID atualizado com sucesso. Bem-vindo, {user_by_phone['nome']}!"
                            conversation_service.send_message(response_message, chat_id)
                            # Implement additional user-specific logic here
                        else:
                            # Check in 'auxiliary_people' table
                            aux_by_phone = conn.execute(
                                "SELECT * FROM auxiliary_people WHERE telefone = ?",
                                (phone_number_digits,)
                            ).fetchone()

                            if aux_by_phone:
                                conn.execute(
                                    "UPDATE auxiliary_people SET chat_id = ? WHERE id = ?",
                                    (chat_id, aux_by_phone['id'])
                                )
                                conn.commit()
                                response_message = "Chat ID atualizado com sucesso. Bem-vindo!"
                                conversation_service.send_message(response_message, chat_id)
                                # Implement additional motorista-specific logic here
                            else:
                                response_message = "Número de telefone não encontrado em nosso cadastro."
                                conversation_service.send_message(response_message, chat_id)
                    else:
                        # Ask for phone number
                        response_message = "Por favor, envie seu número de telefone para prosseguir."
                        reply_markup = {
                            "keyboard": [[{
                                "text": "Enviar meu número de telefone",
                                "request_contact": True
                            }]],
                            "one_time_keyboard": True,
                            "resize_keyboard": True
                        }
                        conversation_service.send_message(response_message, chat_id, reply_markup=reply_markup)
    return 'OK'



def generate_gerente_report(gerente_id):
    """
    Gera um relatório das tarefas concluídas pelos motoristas subordinados ao gerente fornecido.
    """
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row

        # Obter motoristas subordinados ao gerente
        motoristas = conn.execute('''
            SELECT ap.id as motorista_id, ap.name as motorista_name
            FROM auxiliary_people ap
            JOIN machine_managers mm ON mm.gerente_id = ?
            JOIN machines m ON m.id = mm.machine_id AND m.motorista_id = ap.id
        ''', (gerente_id,)).fetchall()

        if not motoristas:
            return "Nenhum motorista subordinado encontrado para o gerente."

        # Obter tarefas concluídas de cada motorista
        report_data = []
        today_date = str(datetime.now().date())
        for motorista in motoristas:
            motorista_id = motorista['motorista_id']
            motorista_name = motorista['motorista_name']

            # Obter tarefas concluídas do motorista
            completed_tasks = conn.execute('''
                SELECT mti.task, mti.status
                FROM maintenance_task_items mti
                JOIN maintenance_tasks mt ON mti.maintenance_task_id = mt.id
                WHERE mt.motorista_id = ? AND mt.date = ? AND mti.status = 'concluída'
            ''', (motorista_id, today_date)).fetchall()

            if completed_tasks:
                report_data.append({
                    'motorista_name': motorista_name,
                    'tasks': completed_tasks
                })

        # Caso não existam tarefas concluídas
        if not report_data:
            return "Nenhuma tarefa concluída para os motoristas subordinados ao gerente."

        # Gerar o relatório formatado
        report = f"Relatório de Tarefas Concluídas ({today_date}):\n\n"
        for data in report_data:
            report += f"Motorista: {data['motorista_name']}\n"
            for task in data['tasks']:
                report += f"- {task['task']} (Status: {task['status']})\n"
            report += "\n"

        return report

@app.route("/send_gerente_report/<gerente_id>", methods=["POST"])
def send_gerente_report(gerente_id):
    """
    Gera e envia um relatório PDF das tarefas concluídas pelos motoristas para o gerente via Telegram.
    """
    with connect_db() as conn:
        # Obter o chat_id do gerente
        gerente_info = conn.execute('''
            SELECT chat_id FROM auxiliary_people WHERE id = ? AND role = 'gerente'
        ''', (gerente_id,)).fetchone()

        if not gerente_info:
            print("Gerente não encontrado.")
            return redirect(url_for("dashboard"))

        chat_id = gerente_info[0]

        # Gera o PDF em memória
        pdf_buffer = generate_gerente_report_pdf(gerente_id)

        # Envia o PDF via Telegram
        conversation_service.send_telegram_message("Relatório gerado com sucesso:", chat_id)
        conversation_service.send_telegram_media(recipient=chat_id, media=pdf_buffer, media_type='document')
        print("Relatório enviado!")

    return redirect(url_for("dashboard"))



from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, inch, mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image,
    PageBreak,
)
from datetime import datetime
import io

import os

def generate_gerente_report_pdf(gerente_id):
    """
    Gera um relatório PDF das tarefas concluídas pelos motoristas subordinados ao gerente fornecido.
    Salva o PDF no sistema de arquivos e retorna o caminho do arquivo.
    """
    # Definir o caminho do diretório onde os relatórios serão salvos
    pdf_directory = 'static/reports/'
    if not os.path.exists(pdf_directory):
        os.makedirs(pdf_directory)

    # Nome do arquivo PDF baseado no gerente_id
    pdf_filename = f'relatorio_gerente_{gerente_id}.pdf'
    pdf_path = os.path.join(pdf_directory, pdf_filename)

    # Criar o PDF em disco
    with open(pdf_path, 'wb') as pdf_file:
        doc = SimpleDocTemplate(pdf_file, pagesize=A4)
        elements = []

        # Estilos e fontes
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Title'],
            fontSize=24,
            alignment=1,
            spaceAfter=20,
        )
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Heading2'],
            fontSize=18,
            textColor=colors.HexColor("#0066CC"),
            spaceAfter=10,
        )
        normal_style = styles['Normal']

        # Cabeçalho com logotipo
        logo_path = 'static/images/logo.webp'
        try:
            logo = Image(logo_path, width=2 * inch, height=2 * inch)
            logo.hAlign = 'CENTER'
            elements.append(logo)
        except Exception as e:
            print(f"Erro ao carregar o logotipo: {e}")

        # Título do relatório
        today_date = datetime.now().strftime('%d/%m/%Y')
        title = Paragraph(f"Relatório de Tarefas Concluídas ({today_date})", title_style)
        elements.append(title)
        elements.append(Spacer(1, 12))

        with connect_db() as conn:
            conn.row_factory = sqlite3.Row

            # Obter motoristas subordinados ao gerente
            motoristas = conn.execute('''
                SELECT DISTINCT ap.id as motorista_id, ap.name as motorista_name
                FROM auxiliary_people ap
                JOIN machines m ON m.motorista_id = ap.id
                JOIN machine_managers mm ON mm.machine_id = m.id
                WHERE mm.gerente_id = ?
            ''', (gerente_id,)).fetchall()

            if not motoristas:
                elements.append(Paragraph("Nenhum motorista subordinado encontrado para o gerente.", normal_style))
                doc.build(elements)
                return pdf_path

            # Obter tarefas concluídas de cada motorista
            report_data = []
            today_iso_date = datetime.now().strftime('%Y-%m-%d')
            total_tarefas = 0
            for motorista in motoristas:
                motorista_id = motorista['motorista_id']
                motorista_name = motorista['motorista_name']
                completed_tasks = conn.execute('''
                    SELECT mti.task, mti.status
                    FROM maintenance_task_items mti
                    JOIN maintenance_tasks mt ON mti.maintenance_task_id = mt.id
                    WHERE mt.motorista_id = ? AND mt.date = ? AND mti.status = ?
                ''', (motorista_id, today_iso_date, 'concluída')).fetchall()
                if completed_tasks:
                    total_tarefas += len(completed_tasks)
                    report_data.append({
                        'motorista_name': motorista_name,
                        'tasks': completed_tasks
                    })

            # Caso não existam tarefas concluídas
            if not report_data:
                elements.append(Paragraph("Nenhuma tarefa concluída para os motoristas subordinados ao gerente.", normal_style))
                doc.build(elements)
                return pdf_path

            # Adicionar sumário
            elements.append(Paragraph(f"Total de Motoristas: {len(report_data)}", normal_style))
            elements.append(Paragraph(f"Total de Tarefas Concluídas: {total_tarefas}", normal_style))
            elements.append(Spacer(1, 12))

            # Gerar o relatório formatado
            for data in report_data:
                elements.append(Paragraph(f"Motorista: {data['motorista_name']}", subtitle_style))
                elements.append(Spacer(1, 6))

                # Construir a tabela de tarefas concluídas
                table_data = [["Tarefa", "Status"]]
                for task in data['tasks']:
                    table_data.append([Paragraph(task['task'], normal_style), task['status'].capitalize()])

                table = Table(table_data, colWidths=[12 * cm, 4 * cm])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4F81BD")),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#DCE6F1")),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.lightgrey]),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ]))
                elements.append(table)
                elements.append(Spacer(1, 24))

            # Adicionar rodapé com número de páginas
            def add_page_number(canvas, doc):
                page_num = canvas.getPageNumber()
                text = f"Página {page_num}"
                canvas.drawRightString(200 * mm, 15 * mm, text)

            doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)

    # Retornar o caminho do arquivo PDF
    return pdf_path


from flask import send_from_directory

@app.route("/gerar_relatorio", methods=["GET", "POST"])
def gerar_relatorio():
    """
    Allows the manager to generate and receive the report via Telegram when the button on the dashboard is clicked.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Check if the user is a manager
    with connect_db() as conn:
        gerente_info = conn.execute('''
            SELECT id, chat_id FROM auxiliary_people WHERE user_id = ? AND role = 'gerente'
        ''', (user_id,)).fetchone()

    if not gerente_info:
        flash("Você não tem permissões para gerar relatórios.")
        return redirect(url_for("dashboard"))

    gerente_id = gerente_info[0]
    chat_id = gerente_info[1]

    # Generate the PDF report
    pdf_path = generate_gerente_report_pdf(gerente_id)

    # Generate the report highlights
    highlights_text = generate_report_highlights(gerente_id)

    # Generate the video with the 3D animated character
    video_path = generate_video_with_3d_character(highlights_text, gerente_id)

    if not video_path:
        flash("Erro ao gerar o vídeo com o personagem animado.")
        return redirect(url_for("dashboard"))

    # Send a message with the link to the interactive report
    conversation_service.send_telegram_message("Relatório gerado com sucesso:", chat_id)
    conversation_service.send_telegram_media(recipient=chat_id, media=pdf_path, media_type='document')
    interactive_url = url_for('relatorio_interativo', gerente_id=gerente_id, _external=True)
    message_text = f"Seu relatório está pronto! Você pode visualizar a versão interativa do relatório aqui: {interactive_url}"
    conversation_service.send_telegram_message(message_text, chat_id)

    flash("Relatório gerado com sucesso! Um link foi enviado para o seu Telegram.")
    return redirect(url_for("dashboard"))


import json
import time

import glob

@app.route('/relatorio_interativo/<int:gerente_id>')
def relatorio_interativo(gerente_id):
    # Paths to the video and PDF report
    video_directory = 'static/videos/'
    video_pattern = f'report_video_{gerente_id}_*.mp4'
    video_files = glob.glob(os.path.join(video_directory, video_pattern))

    if video_files:
        # Get the latest video file
        latest_video_file = max(video_files, key=os.path.getctime)
        video_url = url_for('static', filename=f'videos/{os.path.basename(latest_video_file)}')
    else:
        flash("O vídeo ainda não foi gerado. Por favor, gere o relatório primeiro.")
        return redirect(url_for("dashboard"))

    # Path to the PDF report
    pdf_filename = f'reports/relatorio_gerente_{gerente_id}.pdf'
    pdf_path = os.path.join(app.static_folder, pdf_filename)
    if not os.path.exists(pdf_path):
        flash("O relatório ainda não foi gerado. Por favor, gere o relatório primeiro.")
        return redirect(url_for("dashboard"))

    pdf_url = url_for('static', filename=pdf_filename)

    # Get the report highlights
    highlights_text = generate_report_highlights(gerente_id)

    # Get the current year for the footer
    current_year = datetime.now().year

    # Render the template with the video, report highlights, and PDF report
    return render_template(
        "relatorio_interativo.html",
        video_url=video_url,
        highlights=highlights_text,
        pdf_url=pdf_url,
        current_year=current_year
    )



def generate_report_highlights(gerente_id):
    """
    Generate highlights from the report data for a given manager.
    """
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row

        # Get drivers under the manager
        drivers = conn.execute('''
            SELECT DISTINCT ap.id as motorista_id, ap.name as motorista_name
            FROM auxiliary_people ap
            JOIN machines m ON m.motorista_id = ap.id
            JOIN machine_managers mm ON mm.machine_id = m.id
            WHERE mm.gerente_id = ?
        ''', (gerente_id,)).fetchall()

        if not drivers:
            return "Nenhum motorista subordinado encontrado para o gerente."

        # Get completed tasks for each driver
        report_data = []
        today_iso_date = datetime.now().strftime('%Y-%m-%d')
        total_tasks_completed = 0
        total_drivers_with_tasks = 0

        for driver in drivers:
            motorista_id = driver['motorista_id']
            motorista_name = driver['motorista_name']

            completed_tasks = conn.execute('''
                SELECT mti.task, mti.status
                FROM maintenance_task_items mti
                JOIN maintenance_tasks mt ON mti.maintenance_task_id = mt.id
                WHERE mt.motorista_id = ? AND mt.date = ? AND mti.status = ?
            ''', (motorista_id, today_iso_date, 'concluída')).fetchall()

            num_completed_tasks = len(completed_tasks)
            if num_completed_tasks > 0:
                total_tasks_completed += num_completed_tasks
                total_drivers_with_tasks += 1
                report_data.append({
                    'motorista_name': motorista_name,
                    'num_completed_tasks': num_completed_tasks
                })

        if total_tasks_completed == 0:
            return "Nenhuma tarefa concluída para os motoristas subordinados ao gerente."

        # Generate the highlights text
        highlights = f"Hoje, {total_drivers_with_tasks} motoristas completaram um total de {total_tasks_completed} tarefas.\n"

        for data in report_data:
            highlights += f"O motorista {data['motorista_name']} completou {data['num_completed_tasks']} tarefas.\n"

        return highlights


def generate_video_with_3d_character(text, gerente_id):
    """
    Generate a video with a 3D animated character speaking the given text using D-ID API.
    """
    DID_API_KEY = os.getenv('did_api_key')
    if not DID_API_KEY:
        print("D-ID API key not found. Please set the DID_API_KEY environment variable.")
        return None

    # Define the endpoint and headers
    url = 'https://api.d-id.com/talks'
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ik53ek53TmV1R3ptcFZTQjNVZ0J4ZyJ9.eyJodHRwczovL2QtaWQuY29tL2ZlYXR1cmVzIjoiIiwiaHR0cHM6Ly9kLWlkLmNvbS9zdHJpcGVfcHJvZHVjdF9pZCI6IiIsImh0dHBzOi8vZC1pZC5jb20vc3RyaXBlX2N1c3RvbWVyX2lkIjoiIiwiaHR0cHM6Ly9kLWlkLmNvbS9zdHJpcGVfcHJvZHVjdF9uYW1lIjoidHJpYWwiLCJodHRwczovL2QtaWQuY29tL3N0cmlwZV9zdWJzY3JpcHRpb25faWQiOiIiLCJodHRwczovL2QtaWQuY29tL3N0cmlwZV9iaWxsaW5nX2ludGVydmFsIjoibW9udGgiLCJodHRwczovL2QtaWQuY29tL3N0cmlwZV9wbGFuX2dyb3VwIjoiZGVpZC10cmlhbCIsImh0dHBzOi8vZC1pZC5jb20vc3RyaXBlX3ByaWNlX2lkIjoiIiwiaHR0cHM6Ly9kLWlkLmNvbS9zdHJpcGVfcHJpY2VfY3JlZGl0cyI6IiIsImh0dHBzOi8vZC1pZC5jb20vY2hhdF9zdHJpcGVfc3Vic2NyaXB0aW9uX2lkIjoiIiwiaHR0cHM6Ly9kLWlkLmNvbS9jaGF0X3N0cmlwZV9wcmljZV9jcmVkaXRzIjoiIiwiaHR0cHM6Ly9kLWlkLmNvbS9jaGF0X3N0cmlwZV9wcmljZV9pZCI6IiIsImh0dHBzOi8vZC1pZC5jb20vcHJvdmlkZXIiOiJnb29nbGUtb2F1dGgyIiwiaHR0cHM6Ly9kLWlkLmNvbS9pc19uZXciOmZhbHNlLCJodHRwczovL2QtaWQuY29tL2FwaV9rZXlfbW9kaWZpZWRfYXQiOiIyMDI0LTA5LTMwVDE2OjM4OjQ0LjQ3MloiLCJodHRwczovL2QtaWQuY29tL29yZ19pZCI6IiIsImh0dHBzOi8vZC1pZC5jb20vYXBwc192aXNpdGVkIjpbIlN0dWRpbyJdLCJodHRwczovL2QtaWQuY29tL2N4X2xvZ2ljX2lkIjoiIiwiaHR0cHM6Ly9kLWlkLmNvbS9jcmVhdGlvbl90aW1lc3RhbXAiOiIyMDI0LTA5LTMwVDE2OjM3OjU1LjUzOVoiLCJodHRwczovL2QtaWQuY29tL2FwaV9nYXRld2F5X2tleV9pZCI6IjJjMGY5N2kzbDYiLCJodHRwczovL2QtaWQuY29tL3VzYWdlX2lkZW50aWZpZXJfa2V5IjoiQ0gzV1FHdkExQkRMSDJvM2dXdTQ0IiwiaHR0cHM6Ly9kLWlkLmNvbS9oYXNoX2tleSI6InNwLXJ3TWVrcVZiNGFXM21jWlAzUSIsImh0dHBzOi8vZC1pZC5jb20vcHJpbWFyeSI6dHJ1ZSwiaHR0cHM6Ly9kLWlkLmNvbS9lbWFpbCI6InBlZHJvLnNhbmNoZXMyOTExQGdtYWlsLmNvbSIsImh0dHBzOi8vZC1pZC5jb20vY291bnRyeV9jb2RlIjoiQlIiLCJodHRwczovL2QtaWQuY29tL3BheW1lbnRfcHJvdmlkZXIiOiJzdHJpcGUiLCJpc3MiOiJodHRwczovL2F1dGguZC1pZC5jb20vIiwic3ViIjoiZ29vZ2xlLW9hdXRoMnwxMTIzNzM1ODg4OTUzODc1NDMyMDMiLCJhdWQiOlsiaHR0cHM6Ly9kLWlkLnVzLmF1dGgwLmNvbS9hcGkvdjIvIiwiaHR0cHM6Ly9kLWlkLnVzLmF1dGgwLmNvbS91c2VyaW5mbyJdLCJpYXQiOjE3Mjc3MTUzOTAsImV4cCI6MTcyNzgwMTc5MCwic2NvcGUiOiJvcGVuaWQgcHJvZmlsZSBlbWFpbCByZWFkOmN1cnJlbnRfdXNlciB1cGRhdGU6Y3VycmVudF91c2VyX21ldGFkYXRhIG9mZmxpbmVfYWNjZXNzIiwiYXpwIjoiR3pyTkkxT3JlOUZNM0VlRFJmM20zejNUU3cwSmxSWXEifQ.AIy0YOxufpXeOV9J-WSVO-ys2KCDn_riev45fK0O2nTwnPFGB8ES5eBd8MyvfsKmApVcXaPTwf-dKqQjIYGDCyJbgP1AYiraHcR0h-I73EVPSiUU1moxkorezHszzs4lTsSqMui3HBMaTHKTfAGhbWolHGrDoKCMEuXb7gmNc_mFdC4U2VO0khZTQY0fTdi-ylDXbEeIbqNLcMdba53zIDDI1OTuF13wZD-8uWmD5QmgLyIE3URKLuMULX4siHBUQA3_3jQ4t6PsHVr4MekiPlv-pPGGBou6szFRDgbwWLI-Ovx4Hpzdc1Lk3hl0uxZnwD5RXfzteO-U5Y3snIImTA"
    }

    # Prepare the data payload
    data = {
        'script': {
            'type': 'text',
            'input': text,
            'provider': {
                'type': 'microsoft',
                'voice_id': 'pt-BR-FranciscaNeural'  # Brazilian Portuguese voice
            },
            'ssml': False
        },
        'config': {
            'fluent': True,
            'pad_audio': 0.0,
            'result_format': 'mp4'
        },
        'source_url': 'https://d-id-public-bucket.s3.us-west-2.amazonaws.com/alice.jpg',  # URL of a 3D avatar model
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 201:
        # The request was successful
        talk_id = response.json().get('id')
        print(f'Talk created with ID: {talk_id}')
    else:
        print(f'Error creating talk: {response.status_code}, {response.text}')
        return None

    # Now poll for the video to be ready
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        time.sleep(5)  # Wait 5 seconds before checking the status

        status_response = requests.get(f'{url}/{talk_id}', headers=headers)
        if status_response.status_code == 200:
            status_data = status_response.json()
            status = status_data.get('status')
            print(f'Status: {status}')
            if status == 'done':
                # The video is ready
                result_url = status_data.get('result_url')
                if result_url:
                    # Download the video
                    video_directory = 'static/videos/'
                    if not os.path.exists(video_directory):
                        os.makedirs(video_directory)
                    video_filename = f'report_video_{gerente_id}_{talk_id}.mp4'
                    video_path = os.path.join(video_directory, video_filename)
                    video_response = requests.get(result_url)
                    with open(video_path, 'wb') as f:
                        f.write(video_response.content)
                    print(f'Video downloaded to {video_path}')
                    return video_path
                else:
                    print('Result URL not found.')
                    return None
            elif status == 'error':
                print(f'Error generating video: {status_data.get("error")}')
                return None
            else:
                # Status is 'in_progress' or something else; keep waiting
                continue
        else:
            print(f'Error checking status: {status_response.status_code}, {status_response.text}')
            return None

    print('Video generation timed out.')
    return None

# ==========================================
# Main Execution
# ==========================================

if __name__ == "__main__":
    init_db()
    start_scheduler()
    # initialize_llm()
    app.run(debug=True)
    
