from dotenv import load_dotenv
import os
from llm import ChatPDF
load_dotenv()

# Obtain API keys and model paths from environment variables
CLIMA_API_KEY = os.getenv("clima_api_key")
NOTICIAS_API_KEY = os.getenv("noticias_api_key")
MODEL_PATH = os.getenv("model_path")
VECTORDB_FOLDER = os.getenv("vectordb_path")
DOCUMENTS_FOLDER = os.getenv("documents_path")
SENTENCE_EMBEDDING_MODEL = os.getenv("sentence_embedding_model")
TOGETHER_API_KEY = os.getenv("together_api_key")

if __name__ == "__main__":
    chat_pdf = ChatPDF(
        documents_folder=DOCUMENTS_FOLDER,
        vectordb_folder=VECTORDB_FOLDER,
        model_path=MODEL_PATH,
        sentence_embedding_model=SENTENCE_EMBEDDING_MODEL,
        together_api_key=TOGETHER_API_KEY,
        temperature=0.3
    )

    # Inicia o processamento
    chat_pdf.start()

    temperature='38°C',
    descricao_clima='céu limpo'
    document_name='utils/manuais/manualOperador_7200J_7215J_7230J.pdf'

    clima = chat_pdf.llm_0_7_t.invoke(f"""
Use a descrição climática fornecida, explicando-a de forma simples e comum, e encaixe nos seguintes padrões de manutenção baseados no clima:

Temperatura: {temperature}°C, Descrição: {descricao_clima}

Resposta:
"""
)

    # Prepara a condição a ser usada na consulta
    condition = f"""
    {clima}
    """
    
    print(f"\n\n Clima: {clima}")

    # Recupera os documentos relevantes aplicando o filtro sem recriar o retriever
    chat_pdf.create_retriever(filter_by_documents=[document_name])
    retrieved_docs = chat_pdf.retriever.invoke(condition)

    for r in retrieved_docs:
            print('\n\n', r)