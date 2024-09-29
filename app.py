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
from services.audio_service import text_to_wav

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
                        telefone TEXT,
                        endereco TEXT,
                        tamanho_fazenda REAL,
                        tipo_cultivo TEXT,
                        sistema_irrigacao TEXT,
                        numero_funcionarios INTEGER,
                        historico_pesticidas TEXT,
                        observacoes TEXT,
                        estado TEXT,
                        cidade TEXT
                        )""")

        # Auxiliary people table with 'role' field
        conn.execute("""CREATE TABLE IF NOT EXISTS auxiliary_people (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        celular TEXT UNIQUE NOT NULL,  -- Cell phone number is unique
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
            SELECT name, email, celular, chat_id, role
            FROM auxiliary_people
            WHERE user_id = ?
        """,
            (user_id,),
        ).fetchall()

    return [
        {
            "name": aux[0],
            "email": aux[1],
            "celular": aux[2],
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
    "J Series 6135": ["6135J", "6150J", "6170J", "6190J", "6210J"],
    "J Series 6110": ["6110J", "6125J", "6130J"],
    "M Series 4040": ["M4040", "M4030"],
    "Series 4730/4830": ["4730", "4830"],
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

def generate_maintenance_tasks():
    """
    Generate daily maintenance tasks for each unique combination of machine model and location.
    """
    today_date = str(datetime.now().date())
    with connect_db() as conn:
        existing_tasks = conn.execute('''
            SELECT 1 FROM maintenance_task_templates WHERE date = ?
        ''', (today_date,)).fetchone()

    if existing_tasks:
        print("As tarefas de manutenção já foram geradas para hoje.")
        return  # Do not proceed if tasks already exist for today

    # Get all unique combinations of machine model and location (city, state)
    with connect_db() as conn:
        combinations = conn.execute('''
            SELECT DISTINCT m.model, u.cidade, u.estado
            FROM machines m
            JOIN users u ON m.user_id = u.id
        ''').fetchall()

    # Map of machine series to their manuals
    machine_series_manuals = {
        'R Series': 'manualOperador_7200J_7215J_7230J.pdf',
        'J Series 7200': 'manualOperador_7200J_7215J_7230J.pdf',
        'M Series': 'manualOperador_7200J_7215J_7230J.pdf',
        # Add other manuals as necessary
    }

    # Generate maintenance tasks for each unique combination
    for combo in combinations:
        model = combo[0]
        cidade = combo[1]
        estado = combo[2]

        # Infer machine series from model
        series = infer_series_from_model(model)

        # Check if machine series has a corresponding manual
        if series in machine_series_manuals:
            manual = machine_series_manuals[series]

            # Generate tasks based on the manual
            try:
                llm = get_llm()
                document_names = [manual]
                llm.create_qa_session(document_names)

                # Get latitude and longitude
                lat, lon = get_lat_lon(cidade, estado)
                weather = None
                description = "Informações climáticas indisponíveis"
                temperature = "N/A"

                if lat and lon:
                    weather = get_weather(lat, lon)

                if weather:
                    description = weather.get("description", "não disponível")
                    temperature = weather.get("temperature", "não disponível")

                # Prompt for the AI model
                prompt = f"""
                    Com base nas informações a seguir, gere uma lista de tarefas de manutenção preventiva que devem ser realizadas hoje:

                    - Condições climáticas: {description} com temperatura de {temperature}°C

                    Analise o clima e utilize apenas as informações fornecidas nos documentos para sugerir as tarefas que podem ser de manutenção ou prevenção, sem inventar informações.
                    Seja o mais breve possível.

                    Lista de tarefas:
                """
                response = llm.qa.invoke(prompt)["result"]
                maintenance_tasks = eval(response.strip())
                if not isinstance(maintenance_tasks, list):
                    maintenance_tasks = ["Erro ao gerar lista de tarefas."]
            except Exception as e:
                maintenance_tasks = ["Erro ao gerar tarefas de manutenção."]
                print(f"Erro ao gerar tarefas para o modelo {model}: {e}")

            # Store the checklist in the database, associated with model, city, state
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
            SELECT a.id as motorista_id, a.name as motorista_name, a.celular, u.cidade, u.estado
            FROM auxiliary_people a
            JOIN users u ON a.user_id = u.id
            WHERE a.role = 'motorista'
        ''').fetchall()

    for motorista in motoristas:
        motorista_id = motorista[0]
        motorista_name = motorista[1]
        motorista_celular = motorista[2]
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
                send_checklist_to_motorista(motorista_name, motorista_celular, maintenance_tasks)
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

def send_checklist_to_motorista(motorista_name, motorista_celular, maintenance_tasks):
    """
    Send the maintenance checklist to the driver.
    """
    # Retrieve the driver's chat_id based on their cell phone number
    with connect_db() as conn:
        motorista_info = conn.execute('''
            SELECT chat_id FROM auxiliary_people
            WHERE celular = ?
        ''', (motorista_celular,)).fetchone()
    chat_id = motorista_info[0] if motorista_info else "Chat ID não cadastrado"

    # Build the message with the maintenance checklist
    message = f"Olá {motorista_name},\n\nAqui está o checklist de manutenção preventiva para hoje:\n\n"
    for idx, task in enumerate(maintenance_tasks, start=1):
        message += f"{idx}. {task}\n"

    message += "\nPara marcar uma tarefa como concluída, responda com o número da tarefa seguido de 'concluída'. Por exemplo: 'Tarefa 1 concluída'"

    try:
        conversation_service = ConversationService()
        # Send message to the driver's chat_id
        response = conversation_service.send_message(message, chat_id)
        print(f"Checklist enviado para {motorista_name} (Chat ID: {chat_id})")
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
        hashed_password = generate_password_hash(password)

        with connect_db() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    (username, hashed_password),
                )
                conn.commit()
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error_message = "Usuário já existe!"

    return render_template("register.html", error_message=error_message)

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
    Route to view and update personal data, including state and city.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        # Get form data, including state and city
        full_name = request.form["full_name"]
        email = request.form["email"]
        telefone = request.form["telefone"]
        endereco = request.form["endereco"]
        tamanho_fazenda = request.form["tamanho_fazenda"]
        tipo_cultivo = request.form["tipo_cultivo"]
        sistema_irrigacao = request.form["sistema_irrigacao"]
        numero_funcionarios = request.form["numero_funcionarios"]
        historico_pesticidas = request.form["historico_pesticidas"]
        observacoes = request.form["observacoes"]
        estado = request.form["estado"]  # New field
        cidade = request.form["cidade"]  # New field

        # Update data in the database
        with connect_db() as conn:
            conn.execute(
                """
                UPDATE users
                SET full_name = ?, email = ?, telefone = ?, endereco = ?, tamanho_fazenda = ?,
                    tipo_cultivo = ?, sistema_irrigacao = ?, numero_funcionarios = ?,
                    historico_pesticidas = ?, observacoes = ?, estado = ?, cidade = ?
                WHERE id = ?
            """,
                (
                    full_name,
                    email,
                    telefone,
                    endereco,
                    tamanho_fazenda,
                    tipo_cultivo,
                    sistema_irrigacao,
                    numero_funcionarios,
                    historico_pesticidas,
                    observacoes,
                    estado,
                    cidade,
                    user_id,
                ),
            )
            conn.commit()

        return redirect(url_for("dashboard"))

    # If GET, fetch existing data
    with connect_db() as conn:
        user = conn.execute(
            """
            SELECT full_name, email, telefone, endereco, tamanho_fazenda,
                   tipo_cultivo, sistema_irrigacao, numero_funcionarios,
                   historico_pesticidas, observacoes, estado, cidade
            FROM users
            WHERE id = ?
        """,
            (user_id,),
        ).fetchone()

    # Load all states
    estados = requests.get(
        "https://servicodados.ibge.gov.br/api/v1/localidades/estados"
    ).json()

    # Load cities if state is already selected
    cidades = None
    if user[10]:  # If state is selected
        cidades = requests.get(
            f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{user[10]}/municipios"
        ).json()

    return render_template(
        "cadastro/dados_pessoais.html",
        full_name=user[0],
        email=user[1],
        telefone=user[2],
        endereco=user[3],
        tamanho_fazenda=user[4],
        tipo_cultivo=user[5],
        sistema_irrigacao=user[6],
        numero_funcionarios=user[7],
        historico_pesticidas=user[8],
        observacoes=user[9],
        estado_selecionado=user[10],
        cidade_selecionada=user[11],
        estados=estados,
        cidades=cidades,
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
                auxiliary_celulares = {
                    key: value
                    for key, value in request.form.items()
                    if key.startswith("auxiliary_celular_")
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
                    celular_key = f"auxiliary_celular_{index}"
                    celular_aux = auxiliary_celulares.get(celular_key)
                    chat_id_key = f"auxiliary_chat_id_{index}"
                    chat_id_aux = auxiliary_chat_ids.get(chat_id_key)
                    role_key = f"auxiliary_role_{index}"
                    role = auxiliary_roles.get(role_key)

                    if name and email_aux and celular_aux and role:
                        conn.execute(
                            """
                            INSERT INTO auxiliary_people (user_id, name, email, celular, chat_id, role)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (user_id, name, email_aux, celular_aux, chat_id_aux, role),
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

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.get_json()
    if 'message' in update and 'text' in update['message']:
        chat_id = str(update['message']['chat']['id'])
        text = update['message']['text'].strip()
        # Process the message
        with connect_db() as conn:
            conn.row_factory = sqlite3.Row
            # Find the driver
            motorista = conn.execute(
                "SELECT * FROM auxiliary_people WHERE chat_id = ?",
                (chat_id,)
            ).fetchone()
            if motorista:
                motorista_id = motorista['id']
                # Find today's maintenance tasks assigned to the driver
                today_date = str(datetime.now().date())
                maintenance_task = conn.execute(
                    "SELECT * FROM maintenance_tasks WHERE motorista_id = ? AND date = ?",
                    (motorista_id, today_date)
                ).fetchone()
                if maintenance_task:
                    maintenance_task_id = maintenance_task['id']
                    # Find tasks in maintenance_task_items
                    tasks = conn.execute(
                        "SELECT * FROM maintenance_task_items WHERE maintenance_task_id = ?",
                        (maintenance_task_id,)
                    ).fetchall()
                    # Process the text to determine which task is being updated
                    import re
                    match = re.match(r'Tarefa (\d+) concluída', text, re.IGNORECASE)
                    if match:
                        task_number = int(match.group(1))
                        if 1 <= task_number <= len(tasks):
                            task_item = tasks[task_number -1]
                            # Update the status of the task
                            conn.execute(
                                "UPDATE maintenance_task_items SET status = ? WHERE id = ?",
                                ('concluída', task_item['id'])
                            )
                            conn.commit()
                            # Send a confirmation message to the driver
                            response_message = f"Tarefa {task_number} marcada como concluída."
                            # Send message via Telegram
                            conversation_service.send_message(response_message, chat_id)

                            # Verificar se todas as tarefas foram concluídas
                            todas_concluidas = conn.execute(
                                "SELECT COUNT(*) FROM maintenance_task_items WHERE maintenance_task_id = ? AND status = 'pendente'",
                                (maintenance_task_id,)
                            ).fetchone()[0] == 0
                            if todas_concluidas:
                                # Obter o gerente associado ao motorista
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
                                    # Gerar e enviar o relatório para o gerente
                                    gerente_id = gerente['gerente_id']
                                    send_gerente_report(gerente_id)
                        else:
                            # Invalid task number
                            response_message = "Número de tarefa inválido."
                            conversation_service.send_message(response_message, chat_id)
                    else:
                        # Unrecognized message
                        response_message = "Mensagem não reconhecida. Para marcar uma tarefa como concluída, responda com o número da tarefa seguido de 'concluída'. Por exemplo: 'Tarefa 1 concluída'"
                        conversation_service.send_message(response_message, chat_id)
            else:
                # Unknown driver
                response_message = "Motorista não encontrado."
                conversation_service.send_message(response_message, chat_id)
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
        conversation_service.send_telegram_media(chat_id, pdf_buffer)
        print("Relatório enviado!")

    return redirect(url_for("dashboard"))



from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from datetime import datetime
import io

def generate_gerente_report_pdf(gerente_id):
    """
    Gera um relatório PDF das tarefas concluídas pelos motoristas subordinados ao gerente fornecido.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # Estilos e fontes
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', fontSize=24, alignment=1, spaceAfter=20)
    subtitle_style = ParagraphStyle('Subtitle', fontSize=16, textColor=colors.HexColor("#0066CC"))
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#003366")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ])

    # Título do relatório
    today_date = datetime.now().strftime('%d/%m/%Y')
    title = Paragraph(f"Relatório de Tarefas Concluídas ({today_date})", title_style)
    elements.append(title)

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
            elements.append(Paragraph("Nenhum motorista subordinado encontrado para o gerente.", subtitle_style))
            doc.build(elements)
            buffer.seek(0)
            return buffer

        # Obter tarefas concluídas de cada motorista
        report_data = []
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
            elements.append(Paragraph("Nenhuma tarefa concluída para os motoristas subordinados ao gerente.", subtitle_style))
            doc.build(elements)
            buffer.seek(0)
            return buffer

        # Gerar o relatório formatado
        for data in report_data:
            elements.append(Paragraph(f"Motorista: {data['motorista_name']}", subtitle_style))

            # Construir a tabela de tarefas concluídas
            table_data = [["Tarefa", "Status"]]
            for task in data['tasks']:
                table_data.append([task['task'], task['status']])

            table = Table(table_data, colWidths=[10 * cm, 4 * cm])
            table.setStyle(table_style)
            elements.append(table)
            elements.append(Paragraph("<br/><br/>", styles["Normal"]))

    # Build the PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer

# Função para enviar o PDF como resposta em um endpoint Flask
@app.route('/gerar_relatorio_pdf/<int:gerente_id>')
def gerar_relatorio_pdf(gerente_id):
    pdf_buffer = generate_gerente_report_pdf(gerente_id)
    
    response = send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"relatorio_gerente_{gerente_id}.pdf",
        mimetype='application/pdf'
    )
    return response

# ==========================================
# Main Execution
# ==========================================

if __name__ == "__main__":
    init_db()
    start_scheduler()
    # initialize_llm()
    app.run(debug=True)
