import requests
import os
import io

class ConversationService:
    def __init__(self):
        # Obtenha a chave da API do Telegram do arquivo .env ou variáveis de ambiente
        self.telegram_api_key = os.getenv("telegram_api_key")

class ConversationService:
    def __init__(self):
        # Obtenha a chave da API do Telegram do arquivo .env ou variáveis de ambiente
        self.telegram_api_key = os.getenv("telegram_api_key")

    def send_message(
        self, message: str, recipient: str, message_type: str = "text", media=None, reply_markup=None
    ):
        """
        Envia uma mensagem ou mídia para o Telegram.

        :param message: A mensagem de texto a ser enviada.
        :param recipient: O 'chat_id' ou 'username' para o Telegram.
        :param message_type: O tipo de mensagem ('text' ou 'media'). Default: "text".
        :param media: O caminho ou URL da mídia, caso message_type seja "media".
        :param reply_markup: O markup de resposta opcional, como teclados customizados, etc.
        """
        if message_type == "text":
            return self.send_telegram_message(message, recipient, reply_markup)
        elif message_type == "media":
            return self.send_telegram_media(recipient, media)
        else:
            raise ValueError("Tipo de mensagem inválido. Use 'text' ou 'media'.")

    def send_message(
        self, message: str, recipient: str, message_type: str = "text", media=None, reply_markup=None
    ):
        if message_type == "text":
            return self.send_telegram_message(message, recipient, reply_markup)
        elif message_type == "media":
            return self.send_telegram_media(recipient, media)
        else:
            raise ValueError("Tipo de mensagem inválido. Use 'text' ou 'media'.")

    def send_telegram_message(self, message: str, recipient: str, reply_markup=None):
        url = f"https://api.telegram.org/bot{self.telegram_api_key}/sendMessage"
        data = {
            "chat_id": recipient,
            "text": message
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        response = requests.post(url, json=data)
        if response.status_code == 200:
            return "Mensagem enviada ao Telegram com sucesso."
        else:
            return f"Erro ao enviar mensagem ao Telegram: {response.text}"

    def send_telegram_media(self, recipient: str, media, media_type="audio"):
        """
        Envia um arquivo de mídia para o Telegram (suporta áudio, PDF ou outros tipos).
        
        :param recipient: O 'chat_id' ou 'username' para o Telegram.
        :param media: Pode ser o caminho para o arquivo no sistema ou um objeto BytesIO.
        :param media_type: Tipo de mídia a ser enviada (default: "audio"). Exemplo: "document", "audio", etc.
        """
        # Determinar o tipo de URL com base no tipo de mídia
        if media_type == "audio":
            url = f"https://api.telegram.org/bot{self.telegram_api_key}/sendAudio"
            file_param = 'audio'
        elif media_type == "document":
            url = f"https://api.telegram.org/bot{self.telegram_api_key}/sendDocument"
            file_param = 'document'
        else:
            raise ValueError("Tipo de mídia não suportado. Use 'audio' ou 'document'.")

        # Se for um objeto BytesIO, use diretamente
        if isinstance(media, io.BytesIO):
            media.seek(0)  # Certifique-se de que o ponteiro está no início do arquivo
            files = {file_param: media}
        else:
            # Se for uma string, assuma que é o caminho de um arquivo no sistema
            files = {file_param: open(media, 'rb')}

        data = {
            'chat_id': recipient
        }

        response = requests.post(url, data=data, files=files)

        # Verificando a resposta da API
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
