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
from services import audio_service
from services.conversation_service import ConversationService

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import atexit


app = Flask(__name__)
app.secret_key = "your_secret_key"

# Carregar as variáveis do arquivo .env
load_dotenv()

# Obter a chave da API de clima a partir do .env
CLIMA_API_KEY = os.getenv("clima_api_key")
NOTICIAS_API_KEY = os.getenv("noticias_api_key")

MODEL_PATH = os.getenv("model_path")
VECTORDB_FOLDER = os.getenv("vectordb_path")
DOCUMENTS_FOLDER = os.getenv("documents_path")
SENTENCE_EMBEDDING_MODEL = os.getenv("sentence_embedding_model")
TOGETHER_API_KEY = os.getenv("together_api_key")

from utils.llm import ChatPDF

llm = None


def get_llm():
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


# Configurar o cache
app.config["CACHE_TYPE"] = "SimpleCache"  # Usar SimpleCache (armazenado na memória)
app.config["CACHE_DEFAULT_TIMEOUT"] = (
    6 * 3600
)  # O cache expira em 300 segundos (5 minutos)
cache = Cache(app)


# Conectando ao banco de dados
def connect_db():
    return sqlite3.connect("database.db")


def init_db():
    with connect_db() as conn:
        # Tabela de usuários
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

        # Tabela de pessoas auxiliares com o novo campo 'role'
        conn.execute("""CREATE TABLE IF NOT EXISTS auxiliary_people (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        celular TEXT NOT NULL,
                        chat_id TEXT,
                        role TEXT NOT NULL, -- 'gerente' ou 'motorista'
                        FOREIGN KEY(user_id) REFERENCES users(id)
                        )""")

        # Tabela de máquinas com a coluna 'motorista_id'
        conn.execute("""CREATE TABLE IF NOT EXISTS machines (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        motorista_id INTEGER, -- Motorista único
                        model TEXT NOT NULL,
                        serial_number TEXT,
                        purchase_date DATE,
                        other_details TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(motorista_id) REFERENCES auxiliary_people(id)
                        )""")

        # Tabela para relacionar máquinas e gerentes
        conn.execute("""CREATE TABLE IF NOT EXISTS machine_managers (
                        machine_id INTEGER NOT NULL,
                        gerente_id INTEGER NOT NULL,
                        PRIMARY KEY(machine_id, gerente_id),
                        FOREIGN KEY(machine_id) REFERENCES machines(id),
                        FOREIGN KEY(gerente_id) REFERENCES auxiliary_people(id)
                        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS maintenance_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        motorista_id INTEGER NOT NULL,
                        gerente_ids TEXT,
                        date TEXT NOT NULL,
                        tasks TEXT,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (motorista_id) REFERENCES auxiliary_people(id)
                        )""")

        conn.commit()


# Função para iniciar o agendador
def start_scheduler():
    scheduler = BackgroundScheduler()
    job = scheduler.add_job(
        func=generate_maintenance_tasks,
        trigger="interval",
        days=1,
        next_run_time=datetime.now(),
    )
    scheduler.start()
    print(f"Job ID: {job.id}, Próxima execução: {job.next_run_time}")
    # Fechar o agendador de forma segura na saída
    atexit.register(lambda: scheduler.shutdown())


@app.route("/dados_pessoais", methods=["GET", "POST"])
def dados_pessoais():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        # Obter os dados do formulário, incluindo estado e cidade
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
        estado = request.form["estado"]  # Novo campo
        cidade = request.form["cidade"]  # Novo campo

        # Atualizar os dados no banco de dados
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

    # Se for GET, buscar os dados existentes
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

    # Carregar todos os estados
    estados = requests.get(
        "https://servicodados.ibge.gov.br/api/v1/localidades/estados"
    ).json()

    # Carregar as cidades se o estado já estiver selecionado
    cidades = None
    if user[10]:  # Se o estado estiver selecionado
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


# Lista de modelos disponíveis
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
    Função que retorna a série da máquina com base no modelo.
    """
    for series, models in MACHINE_MODELS.items():
        if model in models:
            return series
    return None


def generate_maintenance_tasks():
    """
    Função para gerar as tarefas de manutenção diárias para cada tipo de máquina.
    """
    # Verificar se já existem tarefas de manutenção para hoje
    with connect_db() as conn:
        today_date = str(datetime.now().date())
        existing_tasks = conn.execute(
            """
            SELECT 1 FROM maintenance_tasks WHERE date = ?
        """,
            (today_date,),
        ).fetchone()

    if existing_tasks:
        print(
            "As tarefas de manutenção já foram geradas para hoje. A função não será executada novamente."
        )
        return  # Não executa o restante da função se já existirem tarefas para hoje

    machine_series_manuals = {
        "R Series": "manualOperador_7200J_7215J_7230J.pdf",
        "J Series 7200": "manualOperador_7200J_7215J_7230J.pdf",
        "M Series": "manualOperador_7200J_7215J_7230J.pdf",
        # Adicione outros manuais conforme necessário
    }

    with connect_db() as conn:
        # Obter todas as máquinas cadastradas, incluindo o user_id
        machines = conn.execute("""
            SELECT m.id, m.user_id, m.model, m.motorista_id, a.name as motorista_name, a.email, a.celular
            FROM machines m
            LEFT JOIN auxiliary_people a ON m.motorista_id = a.id
        """).fetchall()

    # Iterar sobre cada máquina e gerar o checklist de manutenção
    for machine in machines:
        machine_id = machine[0]
        user_id = machine[1]
        model = machine[2]
        motorista_id = machine[3]
        motorista_name = machine[4]
        motorista_email = machine[5]
        motorista_celular = machine[6]

        with connect_db() as conn:
            gerente_rows = conn.execute(
                """
                SELECT gerente_id FROM machine_managers WHERE machine_id = ?
            """,
                (machine_id,),
            ).fetchall()
        gerente_ids = [str(row[0]) for row in gerente_rows]
        gerente_ids_str = ",".join(gerente_ids) if gerente_ids else None

        # Inferir a série da máquina com base no modelo
        series = infer_series_from_model(model)

        # Verificar se a série da máquina tem um manual correspondente
        if series in machine_series_manuals:
            manual = machine_series_manuals[series]

            # Geração de tarefas com base no manual
            try:
                llm = get_llm()
                document_names = [manual]
                llm.create_qa_session(document_names)

                # Obter as informações de localização do usuário
                with connect_db() as conn:
                    user = conn.execute(
                        "SELECT cidade, estado FROM users WHERE id = ?", (user_id,)
                    ).fetchone()

                if user:
                    cidade = user[0]
                    estado = user[1]
                else:
                    cidade = None
                    estado = None

                # Obter latitude e longitude
                lat, lon = get_lat_lon(cidade, estado)
                weather = None
                description = "Informações climáticas indisponíveis"
                temperature = "N/A"

                if lat and lon:
                    weather = get_weather(lat, lon)

                if weather:
                    description = weather.get("description", "não disponível")
                    temperature = weather.get("temperature", "não disponível")

                # Prompt para o modelo de IA
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

            # Armazenar o checklist no banco de dados
            with connect_db() as conn:
                conn.execute(
                    """
                    INSERT INTO maintenance_tasks (user_id, motorista_id, gerente_ids, date, tasks)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        user_id,
                        motorista_id,
                        gerente_ids_str,
                        today_date,
                        str(maintenance_tasks),
                    ),
                )
                conn.commit()
            # Enviar o checklist para o motorista
            send_checklist_to_motorista(
                motorista_name, motorista_email, maintenance_tasks, motorista_id
            )


def send_checklist_to_motorista(motorista_name, motorista_email, maintenance_tasks):
    """
    Função para enviar o checklist de manutenção para o motorista.
    """
    message = f"Olá {motorista_name},\n\nAqui está o checklist de manutenção preventiva para hoje:\n\n"
    for task in maintenance_tasks:
        message += f"- {task}\n"

    # Exemplo de envio (definir o método de envio, como e-mail ou WhatsApp)
    print(f"Checklist enviado para {motorista_email}: \n{message}")
    # send_email(motorista_email, "Checklist de Manutenção", message)


@app.route("/send_maintenance_to_motoristas", methods=["POST"])
def send_maintenance_to_motoristas():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    today_date = str(datetime.now().date())

    # Obter as tarefas de manutenção para o dia atual
    with connect_db() as conn:
        tasks_row = conn.execute(
            """
            SELECT tasks FROM maintenance_tasks
            WHERE user_id = ? AND date = ?
        """,
            (user_id, today_date),
        ).fetchone()

    if tasks_row:
        maintenance_tasks = eval(tasks_row[0]) if tasks_row else None

        # Obter motoristas associados às máquinas
        with connect_db() as conn:
            motoristas = conn.execute(
                """
                SELECT a.name, a.email
                FROM machines m
                JOIN auxiliary_people a ON m.motorista_id = a.id
                WHERE m.user_id = ?
            """,
                (user_id,),
            ).fetchall()

        # Enviar tarefas de manutenção para cada motorista
        for motorista in motoristas:
            motorista_name = motorista[0]
            motorista_email = motorista[1]
            send_checklist_to_motorista(
                motorista_name, motorista_email, maintenance_tasks
            )

        flash("Tarefas de manutenção enviadas com sucesso aos motoristas!")
    else:
        flash("Não há tarefas de manutenção para hoje.")

    return redirect(url_for("dashboard"))


@app.route("/machines")
def list_machines():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row  # Permite acessar os resultados como dicionários

        # Obter máquinas com motoristas
        machines = conn.execute(
            """
            SELECT m.*, a.name as motorista_name
            FROM machines m
            LEFT JOIN auxiliary_people a ON m.motorista_id = a.id
            WHERE m.user_id = ?
        """,
            (user_id,),
        ).fetchall()

        # Obter gerentes para cada máquina
        machine_managers = conn.execute(
            """
            SELECT mm.machine_id, ap.name as gerente_name
            FROM machine_managers mm
            JOIN auxiliary_people ap ON mm.gerente_id = ap.id
            WHERE ap.user_id = ?
        """,
            (user_id,),
        ).fetchall()

        # Organizar os gerentes por máquina
        gerentes_por_maquina = {}
        for manager in machine_managers:
            machine_id = manager["machine_id"]
            if machine_id not in gerentes_por_maquina:
                gerentes_por_maquina[machine_id] = []
            gerentes_por_maquina[machine_id].append(manager["gerente_name"])

    # Passar as máquinas e gerentes para o template
    return render_template(
        "machines/list.html",
        machines=machines,
        gerentes_por_maquina=gerentes_por_maquina,
    )


@app.route("/machines/add", methods=["GET", "POST"])
def add_machine():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        model = request.form["model"]
        serial_number = request.form["serial_number"]
        purchase_date = request.form["purchase_date"]
        other_details = request.form["other_details"]
        motorista_id = request.form.get("motorista_id")
        gerente_ids = request.form.getlist("gerente_ids")  # Lista de IDs dos gerentes

        if not model:
            flash("O campo modelo é obrigatório.")
            return redirect(url_for("add_machine"))

        # Verificar se o modelo selecionado é válido
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

            # Inserir gerentes na tabela machine_managers
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

    # Obter motoristas e gerentes para exibir na página
    auxiliaries = get_auxiliaries_by_role(user_id)
    return render_template(
        "machines/add.html", auxiliaries=auxiliaries, machine_models=MACHINE_MODELS
    )


@app.route("/machines/edit/<int:machine_id>", methods=["GET", "POST"])
def edit_machine(machine_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with connect_db() as conn:
        conn.row_factory = sqlite3.Row

        # Obter os detalhes da máquina
        machine = conn.execute(
            "SELECT * FROM machines WHERE id = ? AND user_id = ?", (machine_id, user_id)
        ).fetchone()
        if not machine:
            flash("Máquina não encontrada.")
            return redirect(url_for("list_machines"))

        # Obter IDs dos gerentes associados à máquina
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

            # Atualizar os detalhes da máquina
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

            # Atualizar os gerentes associados
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

    # Obter motoristas e gerentes para exibir
    auxiliaries = get_auxiliaries_by_role(user_id)

    # Enviar a lista de IDs dos gerentes associados para o template
    return render_template(
        "machines/edit.html",
        machine=machine,
        auxiliaries=auxiliaries,
        gerente_ids=gerente_ids,
        machine_models=MACHINE_MODELS,
    )


def get_auxiliaries_by_role(user_id):
    with connect_db() as conn:
        # Configurar o row_factory para acessar colunas pelos seus nomes
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

    # Retornar os resultados como dicionários (id e nome)
    return {
        "motoristas": [
            {"id": motorista["id"], "name": motorista["name"]}
            for motorista in motoristas
        ],
        "gerentes": [
            {"id": gerente["id"], "name": gerente["name"]} for gerente in gerentes
        ],
    }


@app.route("/machines/delete/<int:machine_id>", methods=["POST"])
def delete_machine(machine_id):
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


def get_auxiliaries(user_id):
    with connect_db() as conn:
        auxiliaries = conn.execute(
            """
            SELECT name, email, celular
            FROM auxiliary_people
            WHERE user_id = ?
        """,
            (user_id,),
        ).fetchall()
    return auxiliaries


@app.route("/pessoas_auxiliares", methods=["GET", "POST"])
def pessoas_auxiliares():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        try:
            # Remover todas as pessoas auxiliares existentes para o usuário atual
            with connect_db() as conn:
                conn.execute(
                    "DELETE FROM auxiliary_people WHERE user_id = ?", (user_id,)
                )

                # Adicionar as novas pessoas auxiliares com seus respectivos campos
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
            # Recuperar novamente as pessoas auxiliares para exibir
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

    # Se for GET, buscar as pessoas auxiliares existentes
    auxiliaries = get_auxiliaries(user_id)
    return render_template("cadastro/pessoas_auxiliares.html", auxiliaries=auxiliaries)


def get_auxiliaries(user_id):
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


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Buscar os dados de localização do usuário
    with connect_db() as conn:
        user = conn.execute(
            "SELECT cidade, estado FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    cidade = user[0]
    estado = user[1]

    if not cidade or not estado:
        # Se não há informações de localização, exiba a mensagem amigável
        missing_location_message = """
            Você ainda não cadastrou sua localização. Ao adicionar sua cidade e estado, você terá acesso
            a informações climáticas personalizadas e relevantes para suas atividades agrícolas.
            <a href='{}'>Clique aqui para cadastrar sua localização</a>.
        """.format(url_for("dados_pessoais"))

        return render_template(
            "dashboard.html",
            username=session["username"],
            missing_location_message=missing_location_message,
            weather=None,
            noticias=None,
            maintenance_tasks=None,
        )

    # Obter as tarefas de manutenção para o dia atual
    today_date = str(datetime.now().date())
    with connect_db() as conn:
        tasks_row = conn.execute(
            """
            SELECT tasks FROM maintenance_tasks
            WHERE user_id = ? AND date = ?
        """,
            (user_id, today_date),
        ).fetchone()
    maintenance_tasks = eval(tasks_row[0]) if tasks_row else None

    # Obter as informações de clima e notícias normalmente
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


@app.route("/login", methods=["GET", "POST"])
def login():
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


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        # Obtendo os dados do formulário
        full_name = request.form["full_name"]
        email = request.form["email"]
        machine1 = int(request.form["machine1"])
        machine2 = int(request.form["machine2"])
        machine3 = int(request.form["machine3"])
        machine4 = int(request.form["machine4"])

        # Salvando as informações no banco de dados
        with connect_db() as conn:
            # Atualizar informações do usuário
            conn.execute(
                """
                UPDATE users
                SET full_name = ?, email = ?, machine1 = ?, machine2 = ?, machine3 = ?, machine4 = ?
                WHERE id = ?
            """,
                (full_name, email, machine1, machine2, machine3, machine4, user_id),
            )
            conn.commit()

            # Remover as pessoas auxiliares existentes
            conn.execute("DELETE FROM auxiliary_people WHERE user_id = ?", (user_id,))

            # Adicionar as novas pessoas auxiliares
            # Filtrar os campos que começam com 'auxiliary_name_'
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

    # Se for uma requisição GET, carregar os dados do usuário
    with connect_db() as conn:
        user = conn.execute(
            "SELECT full_name, email, machine1, machine2, machine3, machine4 FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        # Carregar as pessoas auxiliares
        auxiliaries = conn.execute(
            "SELECT name, email FROM auxiliary_people WHERE user_id = ?", (user_id,)
        ).fetchall()

    # Passar os dados do usuário e das pessoas auxiliares para o template
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


@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template("index.html")


@cache.cached(timeout=6 * 3600, key_prefix="lat_lon_{city}_{state}")
def get_lat_lon(city, state, api_key=CLIMA_API_KEY):
    url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},{state},BR&limit=1&appid={api_key}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data:
            return data[0]["lat"], data[0]["lon"]  # Retorna latitude e longitude
    return None, None


# Função que obtém as informações de clima com caching
@cache.cached(timeout=6 * 3600, key_prefix="weather_{lat}_{lon}")
def get_weather(lat, lon, api_key=CLIMA_API_KEY):
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

    # Retorna None ou algum valor padrão
    return None


def get_news(city, state, api_key=NOTICIAS_API_KEY):
    url = f"https://newsapi.org/v2/top-headlines?country=br&apiKey={api_key}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        print(data)
        return data["articles"][:5]  # Retorna as 5 primeiras notícias
    return None


@app.route("/transformar_em_audio", methods=["POST"])
def transformar_em_audio():
    text = request.form["text_input"]

    # Chamar a função de conversão de texto para áudio
    wav_file = audio_service.text_to_wav(text)

    if wav_file:
        return send_file(wav_file, as_attachment=True)
    else:
        return "Erro ao gerar o áudio.", 500


@app.route("/send_report/<message_type>/<recipient>", methods=["POST"])
def send_report(message_type, recipient):
    # Validação básica
    if not recipient:
        flash("Por favor, insira o chat ID ou username do Telegram.")
        return redirect(url_for("dashboard"))

    # Definindo a mensagem com base no tipo
    if message_type == "relatorio":
        message = "Aqui está o relatório solicitado."
    elif message_type == "checklist":
        message = "Aqui está o checklist solicitado."
    else:
        flash("Tipo de mensagem inválido.")
        return redirect(url_for("dashboard"))

    conversation_service = ConversationService()

    try:
        # Enviar mensagem para o Telegram
        response = conversation_service.send_message(message, recipient)
        flash(
            f"{message_type.capitalize()} enviado com sucesso para {recipient} via Telegram!"
        )
        print(response)
    except Exception as e:
        flash(f"Erro ao enviar {message_type}: {e}")

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    init_db()
    start_scheduler()
    # initialize_llm()
    app.run(debug=True)
