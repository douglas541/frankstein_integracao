import os
import requests


def get_chat_ids():
    # Carregar a chave da API do Telegram a partir da variável de ambiente
    telegram_api_key = os.getenv("telegram_api_key")

    if not telegram_api_key:
        raise ValueError("A variável de ambiente 'telegram_api_key' não está definida.")

    # URL da API de updates do Telegram
    url = f"https://api.telegram.org/bot{telegram_api_key}/getUpdates"

    # Faz a requisição para obter as últimas interações
    response = requests.get(url)

    if response.status_code != 200:
        raise Exception(f"Erro ao acessar a API do Telegram: {response.text}")

    data = response.json()

    # Verificar se há resultados e resgatar os chat_ids
    chat_ids = set()  # Usar um set para evitar duplicatas
    if "result" in data:
        for update in data["result"]:
            # Verifica se há mensagem e extrai o chat_id
            if "message" in update:
                chat_id = update["message"]["chat"]["id"]
                chat_ids.add(chat_id)

    if chat_ids:
        print("Chat IDs encontrados:")
        for chat_id in chat_ids:
            print(chat_id)
    else:
        print("Nenhum chat_id encontrado.")


if __name__ == "__main__":
    get_chat_ids()
