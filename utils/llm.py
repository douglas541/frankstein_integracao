from langchain_community.document_loaders import PyMuPDFLoader, DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_chroma import Chroma

from langchain_together import Together, TogetherEmbeddings
from langchain_openai import OpenAIEmbeddings
from operator import itemgetter
import datetime

from dotenv import load_dotenv
import os
import re

load_dotenv()


MODEL_PATH = os.getenv('model_path')
VECTORDB_FOLDER = os.getenv('vectordb_path')
DOCUMENTS_FOLDER = os.getenv('documents_path')
SENTENCE_EMBEDDING_MODEL = os.getenv('sentence_embedding_model')
TOGETHER_API_KEY = os.getenv('together_api_key')
OPENAI_API_KEY = os.getenv('openai_api_key')
HF_API_KEY = os.getenv('hf_api_key')

from langchain.schema import BaseRetriever

class FilteredRetriever(BaseRetriever):
    def __init__(self, retriever, filter_criteria):
        self.retriever = retriever
        self.filter_criteria = filter_criteria

    def get_relevant_documents(self, query):
        return self.retriever.get_relevant_documents(query, filter=self.filter_criteria)

    async def aget_relevant_documents(self, query):
        return await self.retriever.aget_relevant_documents(query, filter=self.filter_criteria)




class ChatPDF:

    def __init__(self, documents_folder: str, vectordb_folder: str, model_path: str, sentence_embedding_model: str, together_api_key:str, temperature: float = 0.1):
        """
        Constrói todos os atributos necessários para o LLM

        Args:
            documents_folder (str): Caminho/Pasta com os documentos que serão carregados para conversação no Chat
            vectordb_folder (str): Caminho/Pasta onde ficarão os arquivos do Chroma (Vector DB)
            model_path (str): Caminho/Pasta que aponta para o modelo LLM a ser utilizado
            sentence_embedding_model (str): Nome do modelo de Embedding que será usado para gerar os tokens dos documentos
            temperature (float, optional): Temperatura para calibrar o nível de aleatoriedade das respostas. O padrão é 0.1 (Muito determinístico, pouco aleatório)
        """
        self.documents_folder = documents_folder
        self.vectordb_folder = vectordb_folder
        self.model_path = model_path
        self.sentence_embedding_model = sentence_embedding_model
        self.temperature = temperature
        self.together_api_key = together_api_key
        self.pages = []
        self.chunks = []

    def clean_pages(self):
        cleaned_pages = []
        for page in self.pages:
            # Limpa o conteúdo da página removendo quebras de linha e caracteres especiais
            page.page_content = page.page_content.replace("\n", " ")
            page.page_content = ' '.join(page.page_content.split())  # Remove espaços extras
            page.page_content = re.sub(r'\s*\.\s*\.\s*', ' ', page.page_content)  # Remove trechos com "..."
            page.page_content = re.sub(r"[^\w\s]", " ", page.page_content)        # Remove pontuações, exceto palavras e espaços
            page.page_content = re.sub(r"\s+", " ", page.page_content)           # Remove espaços múltiplos

            if page.page_content.strip():
                cleaned_pages.append(page)

        self.pages = cleaned_pages


    def load(self) -> int:
        """
        Realiza a carga dos documentos do caminho/pasta definido no atributo documents_folder.

        Returns:
            int: Quantidade total de páginas carregadas de todos os arquivos PDF
        """
        loader = DirectoryLoader(
            self.documents_folder,
            glob="*.pdf",
            loader_cls=PyMuPDFLoader,
            show_progress=True,
            use_multithreading=True
        )

        self.pages = loader.load()

        return len(self.pages)

    def split(self, chunk_size: int = 1500, chunk_overlap: int = 150) -> int:
        """
        Realiza o split das páginas em chunks e adiciona o nome do documento como metadado.

        Args:
            chunk_size (int, optional): Quantidade máxima de caracteres de cada chunk. O padrão é 1500.
            chunk_overlap (int, optional): Quantidade de caracteres de overlap entre chunks. O padrão é 150.

        Returns:
            int: Quantidade total de chunks de todos os documentos carregados
        """
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        self.clean_pages()
        
        # Lista para armazenar os chunks com metadados
        self.chunks = []
        
        # Processa cada documento e armazena os chunks com o nome do documento como metadado
        for page in self.pages:
            document_chunks = text_splitter.split_documents([page])
            
            # Adiciona o nome do documento aos metadados dos chunks
            for chunk in document_chunks:
                chunk.metadata['source'] = page.metadata.get('source', '')
            self.chunks.extend(document_chunks)

        return len(self.chunks)

    
    def get_embeddings_together(self):
        """
        Obtem os embeddings do modelo de linguagem definido no atributo sentence_embedding_model.
        """
        self.embeddings = TogetherEmbeddings(
            together_api_key=self.together_api_key,
            model=self.sentence_embedding_model,
        )
    
    def get_embeddings_openai(self):
        """
        Obtem os embeddings do modelo de linguagem definido no atributo sentence_embedding_model.
        """
        self.embeddings = OpenAIEmbeddings(
            api_key="sk-wYbejAje72Veeb8gS8ZctiUnFnwGreUZB_xYcLMS9YT3BlbkFJkDzK-9-vNALGtg-o4MpNSkIeojcb-iqlSuPgu_b3YA",
        )

    def store(self):
        """
        Armazena os chunks de todos os documentos no Vector DB, utilizando o embedding definido e inclui metadados (nome do documento).
        """

        try:
            vectordb = Chroma.from_documents(
                documents=self.chunks,
                embedding=self.embeddings,
                persist_directory=self.vectordb_folder
            )
            
            self.vectordb = vectordb
        
        except Exception as e:
            print(f"Erro ao armazenar os documentos: {str(e)}")
            raise

    def create_llm(self):
        """
        Cria uma LLM local, com base no modelo definido no atributo model_path.
        """
        
        self.llm = Together(
                        model=self.model_path,
                        together_api_key=self.together_api_key,
                        temperature=self.temperature,
                        max_tokens=1024,
                    )

    def create_llm_0_7_t(self):
        """
        Cria uma LLM local, com base no modelo definido no atributo model_path.
        """
        
        self.llm_0_7_t = Together(
                        model=self.model_path,
                        together_api_key=self.together_api_key,
                        temperature=0.7,
                        max_tokens=150,
                    )

    def create_retriever(self, k=5, filter_by_documents=None):
        """
        Cria um retriever de documentos com base no Vector DB já carregado, com a possibilidade de filtrar por um ou mais documentos.

        Args:
            k (int): Número de documentos a serem retornados.
            filter_by_documents (list of str, optional): Lista de nomes dos documentos para filtrar. Retorna apenas chunks daqueles documentos.
        """
        if filter_by_documents:
            # Filtrar com base em uma lista de documentos
            search_kwargs = {
                'k': k,
                'filter': {"source": {"$in": filter_by_documents}}  # Usar $in para aceitar vários documentos
            }
        else:
            search_kwargs = {'k': k}

        self.retriever = self.vectordb.as_retriever(search_kwargs=search_kwargs)
    
    def generate_maintenance_tasks(self, document_name: str, temperature: float, descricao_clima: str, k: int = 10):
        """
        Gera tarefas de manutenção preventiva com base no documento especificado, temperatura e descrição climática.

        Args:
            document_name (str): Nome do documento a ser filtrado.
            temperature (float): Temperatura para o modelo LLM.
            descricao_clima (str): Descrição das condições climáticas.
            k (int, optional): Número de documentos a serem retornados pelo retriever. Padrão é 10.

        Returns:
            dict: Contém a resposta gerada e os documentos fonte utilizados.
        """
        # Reformula a descrição climática usando o LLM
        clima = self.llm_0_7_t.invoke(f"""
Usando a descrição climática de {temperature}°C, Descrição: {descricao_clima} fornecida, explique-a de forma simples e comum, pense em como pode afetar máquinas agrícolas de alto rendimento e encaixe nos seguintes padrões de manutenção baseados no clima:

Explicação:
"""
)

    # Prepara a condição a ser usada na consulta
        condition = f"""
        {clima}
        """
        print(f"\n\n Clima: {clima}")

        # Recupera os documentos relevantes aplicando o filtro sem recriar o retriever
        self.create_retriever(filter_by_documents=[document_name])
        retrieved_docs = self.retriever.invoke(condition)

        for r in retrieved_docs:
            print('\n\n', r)

        # Define o template do prompt
        PROMPT_TEMPLATE = """
        Você é um assistente especializado em manutenção de máquinas agrícolas. Baseando-se no contexto fornecido e nas condições climáticas atuais, gere uma lista de tarefas de manutenção preventiva que devem ser realizadas hoje.

        Instruções:
        - Cada tarefa deve estar embasada no contexto fornecido e citar diretamente o impacto das condições climáticas nas máquinas agrícolas.
        - Dê uma breve explicação sobre o motivo da tarefa, fazendo referência direta às condições climáticas e ao contexto.
        - Use os dados fornecidos e as condições climáticas para justificar a urgência ou relevância da tarefa.
        - Retorne exatamente 5 tarefas, cada uma em uma única frase clara e objetiva, com uma breve explicação.
        - O formato de retorno deve ser uma lista Python: ['tarefa 1', 'tarefa 2', 'tarefa 3', 'tarefa 4', 'tarefa 5'].

        Dados:
        - Contexto: {context}
        - Condições climáticas: {question}

        Lista de strings em Python:
        """
        QA_CHAIN_PROMPT = PromptTemplate.from_template(PROMPT_TEMPLATE)

        from langchain.chains.question_answering import load_qa_chain

        chain = load_qa_chain(
            llm=self.llm,
            chain_type="stuff",
            prompt=QA_CHAIN_PROMPT,
            verbose=True,
        )

        # Executa a cadeia com os documentos recuperados
        response = chain.invoke(
            {"input_documents": retrieved_docs, "question": condition},
            return_only_outputs=True
        )

        # Adiciona os documentos fonte à resposta
        response['source_documents'] = retrieved_docs

        return response
    
    def generate_efficiency_tasks(self, document_name: str, temperature: float, descricao_clima: str, operational_data: str, k: int = 10):
        """
        Gera tarefas para melhorar a eficiência das máquinas e do plantio com base no documento especificado, temperatura, descrição climática e dados operacionais.

        Args:
            document_name (str): Nome do documento a ser filtrado.
            temperature (float): Temperatura atual.
            descricao_clima (str): Descrição das condições climáticas.
            operational_data (str): Dados operacionais atuais (exemplo: tipo de cultura, fase do plantio, etc.).
            k (int, optional): Número de documentos a serem retornados pelo retriever. Padrão é 10.

        Returns:
            dict: Contém a resposta gerada e os documentos fonte utilizados.
        """
        # Reformula a descrição climática usando o LLM
        clima = self.llm_0_7_t.invoke(f"""
Usando a descrição climática de {temperature}°C, Descrição: {descricao_clima} fornecida, explique-a de forma simples e comum, pense em como pode afetar a eficiência das máquinas agrícolas e do plantio e encaixe nos seguintes padrões de eficiência baseados no clima:

Explicação:
"""
)
        print(f"\n\nClima: {clima}")

        # Prepara a condição a ser usada na consulta
        condition = f"""
        {clima}
        Dados Operacionais: {operational_data}
        """
        # Recupera os documentos relevantes aplicando o filtro
        self.create_retriever(filter_by_documents=[document_name])
        retrieved_docs = self.retriever.get_relevant_documents(condition)

        # Log retrieved documents for debugging
        for r in retrieved_docs:
            print('\n\n', r)

        # Define o template do prompt
        PROMPT_TEMPLATE = """
Você é um assistente especializado em eficiência agrícola. Baseando-se no contexto fornecido, nas condições climáticas atuais e nos dados operacionais, gere uma lista de tarefas para melhorar a eficiência das máquinas e do plantio.

Instruções:
- Cada tarefa deve estar embasada no contexto fornecido e citar diretamente o impacto das condições climáticas e dos dados operacionais na eficiência.
- Dê uma breve explicação sobre o motivo da tarefa, fazendo referência direta às condições climáticas, aos dados operacionais e ao contexto.
- Use os dados fornecidos para justificar a relevância da tarefa.
- Retorne exatamente 5 tarefas, cada uma em uma única frase clara e objetiva, com uma breve explicação.
- O formato de retorno deve ser uma lista Python: ['tarefa 1', 'tarefa 2', 'tarefa 3', 'tarefa 4', 'tarefa 5'].

Dados:
- Contexto: {context}
- Condições climáticas e operacionais: {question}

Lista de strings em Python:
"""
        QA_CHAIN_PROMPT = PromptTemplate.from_template(PROMPT_TEMPLATE)

        from langchain.chains.question_answering import load_qa_chain

        chain = load_qa_chain(
            llm=self.llm,
            chain_type="stuff",
            prompt=QA_CHAIN_PROMPT,
            verbose=True,
        )

        # Executa a cadeia com os documentos recuperados
        response = chain(
            {"input_documents": retrieved_docs, "question": condition}
        )

        # Adiciona os documentos fonte à resposta
        response['source_documents'] = retrieved_docs

        return response

    def generate_safety_tasks(self, document_name: str, temperature: float, descricao_clima: str, safety_guidelines: str, k: int = 10):
        """
        Gera tarefas de segurança para os trabalhadores operando as máquinas agrícolas com base no documento especificado, temperatura, descrição climática e diretrizes de segurança.

        Args:
            document_name (str): Nome do documento a ser filtrado.
            temperature (float): Temperatura atual.
            descricao_clima (str): Descrição das condições climáticas.
            safety_guidelines (str): Diretrizes ou preocupações de segurança atuais.
            k (int, optional): Número de documentos a serem retornados pelo retriever. Padrão é 10.

        Returns:
            dict: Contém a resposta gerada e os documentos fonte utilizados.
        """
        # Reformula a descrição climática usando o LLM
        clima = self.llm_0_7_t.invoke(f"""
Usando a descrição climática de {temperature}°C, Descrição: {descricao_clima} fornecida, explique-a de forma simples e comum, pense em como pode afetar a segurança dos trabalhadores ao operarem máquinas agrícolas e encaixe nas seguintes diretrizes de segurança baseadas no clima:

Explicação:
"""
)
        print(f"\n\nClima: {clima}")

        # Prepara a condição a ser usada na consulta
        condition = f"""
        {clima}
        Diretrizes de Segurança: {safety_guidelines}
        """
        # Recupera os documentos relevantes aplicando o filtro
        self.create_retriever(filter_by_documents=[document_name])
        retrieved_docs = self.retriever.get_relevant_documents(condition)

        # Log retrieved documents for debugging
        for r in retrieved_docs:
            print('\n\n', r)

        # Define o template do prompt
        PROMPT_TEMPLATE = """
Você é um assistente especializado em segurança no trabalho agrícola. Baseando-se no contexto fornecido, nas condições climáticas atuais e nas diretrizes de segurança, gere uma lista de tarefas que ajudarão os trabalhadores a manter sua segurança ao operar as máquinas.

Instruções:
- Cada tarefa deve estar embasada no contexto fornecido e citar diretamente o impacto das condições climáticas e das diretrizes de segurança na operação diária.
- Dê uma breve explicação sobre o motivo da tarefa, fazendo referência direta às condições climáticas, às diretrizes de segurança e ao contexto.
- Use os dados fornecidos para justificar a relevância da tarefa.
- Retorne exatamente 5 tarefas, cada uma em uma única frase clara e objetiva, com uma breve explicação.
- O formato de retorno deve ser uma lista Python: ['tarefa 1', 'tarefa 2', 'tarefa 3', 'tarefa 4', 'tarefa 5'].

Dados:
- Contexto: {context}
- Condições climáticas e diretrizes de segurança: {question}

Lista de strings em Python:
"""
        QA_CHAIN_PROMPT = PromptTemplate.from_template(PROMPT_TEMPLATE)

        from langchain.chains.question_answering import load_qa_chain

        chain = load_qa_chain(
            llm=self.llm,
            chain_type="stuff",
            prompt=QA_CHAIN_PROMPT,
            verbose=True,
        )

        # Executa a cadeia com os documentos recuperados
        response = chain(
            {"input_documents": retrieved_docs, "question": condition}
        )

        # Adiciona os documentos fonte à resposta
        response['source_documents'] = retrieved_docs

        return response


    def start(self):
        self.get_embeddings_openai()
        print(os.path.join(self.vectordb_folder, 'chroma.sqlite3'))
        if os.path.exists(os.path.join(self.vectordb_folder, 'chroma.sqlite3')):
            print("Carregou banco de dados")
            self.vectordb = Chroma(
                persist_directory=self.vectordb_folder,
                embedding_function=self.embeddings
            )
        else:
            # Carregar e processar os documentos
            
            self.load()
            self.split()
            self.store()
        self.create_llm()
        self.create_llm_0_7_t()
        self.create_retriever()
