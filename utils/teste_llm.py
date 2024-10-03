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

    chat_pdf.create_qa_session(['manualOperador_7200J_7215J_7230J.pdf'])

    # Lista de condições climáticas para testar
    clima = chat_pdf.llm.invoke(f"""Reformule a descrição climática fornecida de uma forma mais explicativa e comum, usando termos encontrado em um manual como "quente e seco", "frio e úmido", etc.

                            Condições climáticas:
                            Nublado e 21.8°C 

                            Resposta:
                            """)
    
    conditions = [
        f"""
        Manutenção preventiva adequadas para o clima: {clima}.
        Verificações para serem feitas antes de dar partida com o clima: {clima}.
        """
        ,
    ]
    
    for condition in conditions:
        print(f"\nCondições climáticas: {condition}")
        response = chat_pdf.qa.invoke(condition)
        print("Resposta:", response['result'])

        print("\nDocumentos utilizados:")
        for doc in response['source_documents']:
            print(doc)
