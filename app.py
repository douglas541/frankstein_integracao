from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key'

from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key'

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
                        machine1 INTEGER DEFAULT 0,
                        machine2 INTEGER DEFAULT 0,
                        machine3 INTEGER DEFAULT 0,
                        machine4 INTEGER DEFAULT 0)''')
        
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
        # Obter os dados do formulário
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

        # Atualizar os dados no banco de dados
        with connect_db() as conn:
            conn.execute('''
                UPDATE users
                SET full_name = ?, email = ?, telefone = ?, endereco = ?, tamanho_fazenda = ?,
                    tipo_cultivo = ?, sistema_irrigacao = ?, numero_funcionarios = ?,
                    historico_pesticidas = ?, observacoes = ?
                WHERE id = ?
            ''', (full_name, email, telefone, endereco, tamanho_fazenda,
                  tipo_cultivo, sistema_irrigacao, numero_funcionarios,
                  historico_pesticidas, observacoes, user_id))
            conn.commit()

        return redirect(url_for('dashboard'))

    # Se for GET, buscar os dados existentes
    with connect_db() as conn:
        user = conn.execute('''
            SELECT full_name, email, telefone, endereco, tamanho_fazenda,
                   tipo_cultivo, sistema_irrigacao, numero_funcionarios,
                   historico_pesticidas, observacoes
            FROM users
            WHERE id = ?
        ''', (user_id,)).fetchone()

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
                           observacoes=user[9])


@app.route('/maquinas', methods=['GET', 'POST'])
def maquinas():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    if request.method == 'POST':
        machine1 = int(request.form['machine1'])
        machine2 = int(request.form['machine2'])
        machine3 = int(request.form['machine3'])
        machine4 = int(request.form['machine4'])

        with connect_db() as conn:
            conn.execute('''
                UPDATE users
                SET machine1 = ?, machine2 = ?, machine3 = ?, machine4 = ?
                WHERE id = ?
            ''', (machine1, machine2, machine3, machine4, user_id))
            conn.commit()

        return redirect(url_for('dashboard'))

    with connect_db() as conn:
        user = conn.execute('SELECT machine1, machine2, machine3, machine4 FROM users WHERE id = ?', (user_id,)).fetchone()

    return render_template('cadastro/maquinas.html', machine1=user[0], machine2=user[1], machine3=user[2], machine4=user[3])

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
    return render_template('dashboard.html', username=session['username'])


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

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
