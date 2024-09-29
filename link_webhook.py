import os
import requests
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Obter a chave da API do Telegram e a URL do webhook
telegram_api_key = os.getenv("telegram_api_key")
webhook_url = "https://aaca-2804-d59-981a-d000-ed86-b44b-c601-4236.ngrok-free.app" + "/webhook"

# Endpoint para definir o webhook
set_webhook_url = f" https://api.telegram.org/bot{telegram_api_key}/setWebhook?url={webhook_url}"

# Dados a serem enviados na solicitação
data = {
    "url": webhook_url
}

# Envia a solicitação para o Telegram
response = requests.post(set_webhook_url, json=data)

# Exibe o resultado da solicitação
if response.status_code == 200:
    print(f"Webhook atualizado com sucesso! {response.json()}")
else:
    print(f"Falha ao atualizar o webhook: {response.status_code} - {response.text}")
