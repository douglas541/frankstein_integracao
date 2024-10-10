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

    response = chat_pdf.generate_maintenance_tasks(
        document_name='utils/manuais/manualOperador_6155M_6175M_6195M.pdf',
        temperature='38°C',
        descricao_clima='céu limpo'
    )

    print("Resposta: ",response['output_text'])

    # for item in response['source_documents']:
    #      print('\n\n', item)

