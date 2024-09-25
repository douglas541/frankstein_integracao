from flask import Flask, render_template, request, redirect, url_for, session, send_file
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import requests
import os
from flask_caching import Cache

from datetime import datetime

from services import audio_service


app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Carregar as variáveis do arquivo .env
load_dotenv()

# Obter a chave da API de clima a partir do .env
CLIMA_API_KEY = os.getenv('clima_api_key')
NOTICIAS_API_KEY = os.getenv('noticias_api_key')

MODEL_PATH = os.getenv('model_path')
VECTORDB_FOLDER = os.getenv('vectordb_path')
DOCUMENTS_FOLDER = os.getenv('documents_path')
SENTENCE_EMBEDDING_MODEL = os.getenv('sentence_embedding_model')
TOGETHER_API_KEY = os.getenv('together_api_key')

from utils.llm import ChatPDF

llm = None

def get_llm():
    global llm
    if llm is None:
        llm = ChatPDF(DOCUMENTS_FOLDER, VECTORDB_FOLDER, MODEL_PATH, SENTENCE_EMBEDDING_MODEL, TOGETHER_API_KEY, temperature=0.3)
        llm.start()
    return llm

# Configurar o cache
app.config['CACHE_TYPE'] = 'SimpleCache'  # Usar SimpleCache (armazenado na memória)
app.config['CACHE_DEFAULT_TIMEOUT'] = 6*3600  # O cache expira em 300 segundos (5 minutos)
cache = Cache(app)

# Conectando ao banco de dados
def connect_db():
    return sqlite3.connect('database.db')

# Criando o banco de dados
def init_db():
    with connect_db() as conn:
        # Tabela de usuários
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
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
                        estado TEXT,  -- Campo representando o estado
                        cidade TEXT,  -- Campo representando a cidade
                        machine_r_series INTEGER DEFAULT 0,  -- 8260R, 8285R, 8310R, 8335R, 8360R
                        machine_j_series_7200 INTEGER DEFAULT 0,  -- 7200J, 7215J, 7230J
                        machine_m_series INTEGER DEFAULT 0,  -- 6155M, 6175M, 6195M
                        machine_j_series_6135 INTEGER DEFAULT 0,  -- 6135J, 6150J, 6170J, 6190J, 6210J
                        machine_j_series_6110 INTEGER DEFAULT 0,  -- 6110J, 6125J, 6130J
                        machine_m_series_4040 INTEGER DEFAULT 0,  -- M4040, M4030
                        machine_series_4730_4830 INTEGER DEFAULT 0  -- 4730, 4830
                        )''')

        # Tabela de pessoas auxiliares
        conn.execute('''CREATE TABLE IF NOT EXISTS auxiliary_people (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        celular TEXT NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users(id))''')
        conn.commit()

# Rotas existentes (login, registro, dashboard) permanecem as mesmas

@app.route('/dados_pessoais', methods=['GET', 'POST'])
def dados_pessoais():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        # Obter os dados do formulário, incluindo estado e cidade
        full_name = request.form['full_name']
        email = request.form['email']
        telefone = request.form['telefone']
        endereco = request.form['endereco']
        tamanho_fazenda = request.form['tamanho_fazenda']
        tipo_cultivo = request.form['tipo_cultivo']
        sistema_irrigacao = request.form['sistema_irrigacao']
        numero_funcionarios = request.form['numero_funcionarios']
        historico_pesticidas = request.form['historico_pesticidas']
        observacoes = request.form['observacoes']
        estado = request.form['estado']  # Novo campo
        cidade = request.form['cidade']  # Novo campo

        # Atualizar os dados no banco de dados
        with connect_db() as conn:
            conn.execute('''
                UPDATE users
                SET full_name = ?, email = ?, telefone = ?, endereco = ?, tamanho_fazenda = ?,
                    tipo_cultivo = ?, sistema_irrigacao = ?, numero_funcionarios = ?,
                    historico_pesticidas = ?, observacoes = ?, estado = ?, cidade = ?
                WHERE id = ?
            ''', (full_name, email, telefone, endereco, tamanho_fazenda,
                  tipo_cultivo, sistema_irrigacao, numero_funcionarios,
                  historico_pesticidas, observacoes, estado, cidade, user_id))
            conn.commit()

        return redirect(url_for('dashboard'))

    # Se for GET, buscar os dados existentes
    with connect_db() as conn:
        user = conn.execute('''
            SELECT full_name, email, telefone, endereco, tamanho_fazenda,
                   tipo_cultivo, sistema_irrigacao, numero_funcionarios,
                   historico_pesticidas, observacoes, estado, cidade
            FROM users
            WHERE id = ?
        ''', (user_id,)).fetchone()

    # Carregar todos os estados
    estados = requests.get('https://servicodados.ibge.gov.br/api/v1/localidades/estados').json()

    # Carregar as cidades se o estado já estiver selecionado
    cidades = None
    if user[10]:  # Se o estado estiver selecionado
        cidades = requests.get(f'https://servicodados.ibge.gov.br/api/v1/localidades/estados/{user[10]}/municipios').json()

    return render_template('cadastro/dados_pessoais.html',
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
                           cidades=cidades)


@app.route('/maquinas', methods=['GET', 'POST'])
def maquinas():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        # Obtenha os valores do formulário
        machine_r_series = int(request.form['machine_r_series'])
        machine_j_series_7200 = int(request.form['machine_j_series_7200'])
        machine_m_series = int(request.form['machine_m_series'])
        machine_j_series_6135 = int(request.form['machine_j_series_6135'])
        machine_j_series_6110 = int(request.form['machine_j_series_6110'])
        machine_m_series_4040 = int(request.form['machine_m_series_4040'])
        machine_series_4730_4830 = int(request.form['machine_series_4730_4830'])

        # Atualize os dados no banco de dados
        with connect_db() as conn:
            conn.execute('''
                UPDATE users
                SET machine_r_series = ?, machine_j_series_7200 = ?, machine_m_series = ?, machine_j_series_6135 = ?, machine_j_series_6110 = ?,
                    machine_m_series_4040 = ?, machine_series_4730_4830 = ?
                WHERE id = ?
            ''', (machine_r_series, machine_j_series_7200, machine_m_series, machine_j_series_6135, machine_j_series_6110,
                  machine_m_series_4040, machine_series_4730_4830, user_id))
            conn.commit()

        return redirect(url_for('dashboard'))

    # Se for GET, busque os valores atuais do banco
    with connect_db() as conn:
        user = conn.execute('''
            SELECT machine_r_series, machine_j_series_7200, machine_m_series, machine_j_series_6135, machine_j_series_6110,
                   machine_m_series_4040, machine_series_4730_4830
            FROM users
            WHERE id = ?
        ''', (user_id,)).fetchone()

    # Passe os valores atuais para o template
    return render_template('cadastro/maquinas.html',
                           machine_r_series=user[0],
                           machine_j_series_7200=user[1],
                           machine_m_series=user[2],
                           machine_j_series_6135=user[3],
                           machine_j_series_6110=user[4],
                           machine_m_series_4040=user[5],
                           machine_series_4730_4830=user[6])

def get_auxiliaries(user_id):
    with connect_db() as conn:
        auxiliaries = conn.execute('''
            SELECT name, email, celular
            FROM auxiliary_people
            WHERE user_id = ?
        ''', (user_id,)).fetchall()
    return auxiliaries

@app.route('/pessoas_auxiliares', methods=['GET', 'POST'])
def pessoas_auxiliares():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        try:
            # Remover todas as pessoas auxiliares existentes
            with connect_db() as conn:
                conn.execute('DELETE FROM auxiliary_people WHERE user_id = ?', (user_id,))

                # Adicionar as novas pessoas auxiliares
                auxiliary_names = {key: value for key, value in request.form.items() if key.startswith('auxiliary_name_')}
                auxiliary_emails = {key: value for key, value in request.form.items() if key.startswith('auxiliary_email_')}
                auxiliary_celulares = {key: value for key, value in request.form.items() if key.startswith('auxiliary_celular_')}

                for key in auxiliary_names:
                    index = key.split('_')[-1]
                    name = auxiliary_names[key]
                    email_key = f'auxiliary_email_{index}'
                    email_aux = auxiliary_emails.get(email_key)
                    celular_key = f'auxiliary_celular_{index}'
                    celular_aux = auxiliary_celulares.get(celular_key)

                    if name and email_aux and celular_aux:
                        conn.execute('''
                            INSERT INTO auxiliary_people (user_id, name, email, celular)
                            VALUES (?, ?, ?, ?)
                        ''', (user_id, name, email_aux, celular_aux))
                conn.commit()

            success_message = "Pessoas auxiliares atualizadas com sucesso!"
            # Recuperar novamente as pessoas auxiliares para exibir
            auxiliaries = get_auxiliaries(user_id)
            return render_template('cadastro/pessoas_auxiliares.html', auxiliaries=auxiliaries, success_message=success_message)
        except Exception as e:
            error_message = "Ocorreu um erro ao atualizar as pessoas auxiliares. Por favor, tente novamente."
            auxiliaries = get_auxiliaries(user_id)
            return render_template('cadastro/pessoas_auxiliares.html', auxiliaries=auxiliaries, error_message=error_message)

    # Se for GET, buscar as pessoas auxiliares existentes
    auxiliaries = get_auxiliaries(user_id)
    return render_template('cadastro/pessoas_auxiliares.html', auxiliaries=auxiliaries)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Buscar os dados de localização do usuário
    with connect_db() as conn:
        user = conn.execute('SELECT cidade, estado FROM users WHERE id = ?', (user_id,)).fetchone()

    cidade = user[0]
    estado = user[1]

    # Obter latitude e longitude
    lat, lon = get_lat_lon(cidade, estado)

    # Obter informações do clima
    weather = None
    if lat and lon:
        weather = get_weather(lat, lon)

    noticias = get_news(cidade, estado)

    # Obter data atual
    today_date = datetime.now().date()

    # Gerar tarefas de manutenção
    if True:
        prompt = f"""
        Com base nas informações a seguir, gere uma lista de tarefas de manutenção preventiva que devem ser realizadas hoje:

        - Condições climáticas: {weather['description']} com temperatura de -2°C

        Analise o clima e utilize apenas as informações fornecidas nos documentos para sugerir as tarefas que podem ser de manutenção ou prevenção, sem inventar informações.
        Seja o mais breve possível.

        Lista de tarefas:
        """
        try:
            llm = get_llm()
            document_names = ['manualOperador_7200J_7215J_7230J.pdf']
            llm.create_qa_session(document_names)
            response = llm.qa.invoke(prompt)['result']
            print(response)
            maintenance_tasks = eval(response.strip())
            if not isinstance(maintenance_tasks, list):
                maintenance_tasks = ["Erro ao gerar lista de tarefas."]
        except Exception as e:
            maintenance_tasks = "Não foi possível gerar as tarefas de manutenção para hoje."
            print(f"Erro ao gerar tarefas de manutenção: {e}")

        session['maintenance_tasks'] = maintenance_tasks
        session['maintenance_date'] = str(today_date)
    else:
        maintenance_tasks = session.get('maintenance_tasks')

    return render_template('dashboard.html', username=session['username'], cidade=cidade, estado=estado, weather=weather, noticias=noticias, maintenance_tasks=maintenance_tasks)



@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        with connect_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

            if user and check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['username'] = user[1]
                return redirect(url_for('dashboard'))
            else:
                error_message = 'Credenciais inválidas!'

    return render_template('login.html', error_message=error_message)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error_message = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password)

        with connect_db() as conn:
            try:
                conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
                conn.commit()
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                error_message = 'Usuário já existe!'

    return render_template('register.html', error_message=error_message)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        # Obtendo os dados do formulário
        full_name = request.form['full_name']
        email = request.form['email']
        machine1 = int(request.form['machine1'])
        machine2 = int(request.form['machine2'])
        machine3 = int(request.form['machine3'])
        machine4 = int(request.form['machine4'])

        # Salvando as informações no banco de dados
        with connect_db() as conn:
            # Atualizar informações do usuário
            conn.execute('''
                UPDATE users
                SET full_name = ?, email = ?, machine1 = ?, machine2 = ?, machine3 = ?, machine4 = ?
                WHERE id = ?
            ''', (full_name, email, machine1, machine2, machine3, machine4, user_id))
            conn.commit()

            # Remover as pessoas auxiliares existentes
            conn.execute('DELETE FROM auxiliary_people WHERE user_id = ?', (user_id,))

            # Adicionar as novas pessoas auxiliares
            # Filtrar os campos que começam com 'auxiliary_name_'
            auxiliary_names = {key: value for key, value in request.form.items() if key.startswith('auxiliary_name_')}
            auxiliary_emails = {key: value for key, value in request.form.items() if key.startswith('auxiliary_email_')}

            for key in auxiliary_names:
                index = key.split('_')[-1]
                name = auxiliary_names[key]
                email_key = f'auxiliary_email_{index}'
                email_aux = auxiliary_emails.get(email_key)

                if name and email_aux:
                    conn.execute('INSERT INTO auxiliary_people (user_id, name, email) VALUES (?, ?, ?)', (user_id, name, email_aux))
            conn.commit()

        return redirect(url_for('dashboard'))

    # Se for uma requisição GET, carregar os dados do usuário
    with connect_db() as conn:
        user = conn.execute('SELECT full_name, email, machine1, machine2, machine3, machine4 FROM users WHERE id = ?', (user_id,)).fetchone()

        # Carregar as pessoas auxiliares
        auxiliaries = conn.execute('SELECT name, email FROM auxiliary_people WHERE user_id = ?', (user_id,)).fetchall()

    # Passar os dados do usuário e das pessoas auxiliares para o template
    return render_template('profile.html', full_name=user[0], email=user[1],
                           machine1=user[2], machine2=user[3], machine3=user[4], machine4=user[5],
                           auxiliaries=auxiliaries)


@app.route('/settings')
def settings():
    return render_template('settings.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('login'))


@cache.cached(timeout=6*3600, key_prefix="lat_lon_{city}_{state}")
def get_lat_lon(city, state, api_key=CLIMA_API_KEY):
    url = f'http://api.openweathermap.org/geo/1.0/direct?q={city},{state},BR&limit=1&appid={api_key}'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data:
            return data[0]['lat'], data[0]['lon']  # Retorna latitude e longitude
    return None, None

# Função que obtém as informações de clima com caching
@cache.cached(timeout=6*3600, key_prefix="weather_{lat}_{lon}")
def get_weather(lat, lon, api_key=CLIMA_API_KEY):
    url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&lang=pt&units=metric'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        weather = {
            'temperature': data['main']['temp'],
            'description': data['weather'][0]['description'],
            'city': data['timezone']
        }
        return weather
    return None

def get_news(city, state, api_key=NOTICIAS_API_KEY):
    url = f'https://newsapi.org/v2/top-headlines?country=br&apiKey={api_key}'
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        print(data)
        return data['articles'][:5]  # Retorna as 5 primeiras notícias
    return None

@app.route('/transformar_em_audio', methods=['POST'])
def transformar_em_audio():
    text = request.form['text_input']

    # Chamar a função de conversão de texto para áudio
    wav_file = audio_service.text_to_wav(text)

    if wav_file:
        return send_file(wav_file, as_attachment=True)
    else:
        return "Erro ao gerar o áudio.", 500


if __name__ == '__main__':
    init_db()
    #initialize_llm()
    app.run(debug=True)
