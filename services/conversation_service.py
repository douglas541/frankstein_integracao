import requests
import os


class ConversationService:
    def __init__(self):
        # Obtenha a chave da API do Telegram do arquivo .env ou variáveis de ambiente
        self.telegram_api_key = os.getenv("telegram_api_key")

    def send_message(
        self, message: str, recipient: str, message_type: str = "text", media=None
    ):
        """
        Envia uma mensagem ou mídia para o Telegram.

        :param message: A mensagem de texto a ser enviada.
        :param recipient: O 'chat_id' ou 'username' para o Telegram.
        :param message_type: O tipo de mensagem (text, media). Default: "text".
        :param media: O caminho ou URL da mídia, caso message_type seja "media".
        """
        if message_type == "text":
            return self.send_telegram_message(message, recipient)
        elif message_type == "media":
            return self.send_telegram_media(recipient, media)
        else:
            raise ValueError("Tipo de mensagem inválido. Use 'text' ou 'media'.")

    def send_telegram_message(self, message: str, recipient: str):
        """
        Envia uma mensagem de texto para o Telegram.
        """
        url = f"https://api.telegram.org/bot{self.telegram_api_key}/sendMessage"
        data = {"chat_id": recipient, "text": message}
        response = requests.post(url, data=data)
        if response.status_code == 200:
            return "Mensagem enviada ao Telegram com sucesso."
        else:
            return f"Erro ao enviar mensagem ao Telegram: {response.text}"

    def send_telegram_media(self, recipient: str, media_path: str):
        """
        Envia um arquivo de mídia (PDF, imagem, vídeo, etc.) para o Telegram.
        """
        url = f"https://api.telegram.org/bot{self.telegram_api_key}/sendDocument"
        with open(media_path, "rb") as media_file:
            files = {"document": media_file}
            data = {"chat_id": recipient}
            response = requests.post(url, data=data, files=files)
        if response.status_code == 200:
            return "Mídia enviada ao Telegram com sucesso."
        else:
            return f"Erro ao enviar mídia ao Telegram: {response.text}"

    def receive_telegram_message(self):
        """
        Recebe uma mensagem de um chat do Telegram (verificando as atualizações da API).
        """
        url = f"https://api.telegram.org/bot{self.telegram_api_key}/getUpdates"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if "result" in data and len(data["result"]) > 0:
                return data["result"][-1]["message"][
                    "text"
                ]  # Retorna a última mensagem recebida
            return "Nenhuma mensagem nova no Telegram."
        else:
            return f"Erro ao receber mensagem do Telegram: {response.text}"
