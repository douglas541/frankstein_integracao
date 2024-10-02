from langchain_community.document_loaders import PyMuPDFLoader, DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA

from langchain_together import Together, TogetherEmbeddings
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
HF_API_KEY = os.getenv('hf_api_key')

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
                chunk.metadata = {"source": page.metadata["source"]}
            self.chunks.extend(document_chunks)

        return len(self.chunks)

    
    def get_embeddings(self):
        """
        Obtem os embeddings do modelo de linguagem definido no atributo sentence_embedding_model.
        """
        self.embeddings = TogetherEmbeddings(
            together_api_key=self.together_api_key,
            model=self.sentence_embedding_model,
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

    def create_retriever(self, k=10, filter_by_documents=None):
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

    def create_qa_session(self, document_names = None, k=10):
        """
        Cria uma sessão de QA, usando o LLM e Retriever instanciados, filtrando pelos nomes dos documentos especificados.

        Args:
            document_names (str or list of str): Nome ou lista de nomes dos documentos a serem usados para o QA.
            k (int, optional): Número de chunks a serem retornados pelo retriever. O padrão é 10.
        """
        # Verifica se 'document_names' é uma string e converte para lista
        if isinstance(document_names, str):
            document_names = [document_names]
        else:
            document_names = None

        # Cria o retriever filtrando pelos documentos fornecidos
        self.create_retriever(k=k, filter_by_documents=document_names)

        # Definição do template para o QA
        PROMPT_TEMPLATE = """
        Você é um assistente especializado em manutenção de máquinas agrícolas. Com base nas informações fornecidas no contexto, gere uma lista de tarefas de manutenção preventiva que devem ser realizadas hoje, considerando as condições climáticas atuais.

        Instruções:
        - Utilize apenas as informações presentes no contexto. Não adicione informações extras.
        - Cada tarefa deve ser descrita em uma frase clara e concisa.
        - **Retorne apenas a lista de tarefas no formato Python: ['tarefa 1', 'tarefa 2', 'tarefa 3', ...], sem nenhum texto adicional.**

        Contexto:
        {context}

        Condições climáticas:
        {question}

        Lista de Tarefas:
        """


        QA_CHAIN_PROMPT = PromptTemplate.from_template(PROMPT_TEMPLATE)

        # Cria a sessão de QA utilizando o LLM e o retriever configurado
        self.qa = RetrievalQA.from_chain_type(
            self.llm,
            'stuff',
            retriever=self.retriever,
            return_source_documents=True,
            chain_type_kwargs={'prompt': QA_CHAIN_PROMPT}
        )

    def start(self):
        self.get_embeddings()
        if os.path.exists(os.path.join(self.vectordb_folder, 'index')):
            # Carregar o banco de dados vetorial existente
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
        self.create_retriever()
        self.create_qa_session()
