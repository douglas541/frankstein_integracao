import requests
import os


class ConversationService:
    def __init__(self):
        # Obtenha as chaves de API dos canais do arquivo .env ou variáveis de ambiente
        self.telegram_api_key = os.getenv("telegram_api_key")
        self.whatsapp_api_url = os.getenv("WHATSAPP_API_URL")
        self.whatsapp_token = os.getenv("WHATSAPP_TOKEN")

    def send_message(self, message: str, channel: str, recipient: str = None):
        """
        Envia uma mensagem para o canal especificado (Telegram ou WhatsApp).

        :param message: A mensagem a ser enviada
        :param channel: O canal para onde enviar ('telegram' ou 'whatsapp')
        :param recipient: O 'chat_id' ou 'username' para o Telegram, ou o número de telefone para WhatsApp
        """
        if channel == "telegram":
            if recipient is None:
                raise ValueError(
                    "O 'chat_id' ou 'username' é necessário para o Telegram."
                )
            return self.send_telegram_message(message, recipient)
        elif channel == "whatsapp":
            if recipient is None:
                raise ValueError("O número de telefone é necessário para o WhatsApp.")
            return self.send_whatsapp_message(message, recipient)
        else:
            raise ValueError("Canal inválido. Escolha entre 'telegram' ou 'whatsapp'.")

    def receive_message(self, channel: str):
        """
        Recebe uma mensagem do canal especificado (Telegram ou WhatsApp).

        :param channel: O canal de onde receber a mensagem ('telegram' ou 'whatsapp')
        :return: A mensagem recebida
        """
        if channel == "telegram":
            return self.receive_telegram_message()
        elif channel == "whatsapp":
            return self.receive_whatsapp_message()
        else:
            raise ValueError("Canal inválido. Escolha entre 'telegram' ou 'whatsapp'.")

    def send_telegram_message(self, message: str, recipient: str):
        """
        Envia uma mensagem para um chat do Telegram usando a API do Telegram.

        :param message: A mensagem a ser enviada
        :param recipient: O 'chat_id' ou 'username' para o Telegram
        """
        url = f"https://api.telegram.org/bot{self.telegram_api_key}/sendMessage"
        data = {"chat_id": recipient, "text": message}
        response = requests.post(url, data=data)
        if response.status_code == 200:
            return "Mensagem enviada ao Telegram com sucesso."
        else:
            return f"Erro ao enviar mensagem ao Telegram: {response.text}"

    def send_whatsapp_message(self, message: str, phone_number: str):
        """
        Envia uma mensagem via WhatsApp usando uma API de integração (exemplo: Twilio).

        :param message: A mensagem a ser enviada
        :param phone_number: O número de telefone para o qual enviar a mensagem
        """
        url = f"{self.whatsapp_api_url}/messages"
        headers = {
            "Authorization": f"Bearer {self.whatsapp_token}",
            "Content-Type": "application/json",
        }
        data = {"to": phone_number, "type": "text", "text": {"body": message}}
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return "Mensagem enviada ao WhatsApp com sucesso."
        else:
            return f"Erro ao enviar mensagem ao WhatsApp: {response.text}"

    def receive_telegram_message(self):
        """
        Recebe uma mensagem de um chat do Telegram (por exemplo, verificando as atualizações da API).

        :return: A mensagem recebida
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

    def receive_whatsapp_message(self):
        """
        Recebe uma mensagem via WhatsApp (usando uma API como Twilio).

        :return: A mensagem recebida
        """
        url = f"{self.whatsapp_api_url}/messages"  # Exemplo de endpoint para receber mensagens
        headers = {
            "Authorization": f"Bearer {self.whatsapp_token}",
            "Content-Type": "application/json",
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "messages" in data and len(data["messages"]) > 0:
                return data["messages"][-1]["text"][
                    "body"
                ]  # Retorna a última mensagem recebida
            return "Nenhuma mensagem nova no WhatsApp."
        else:
            return f"Erro ao receber mensagem do WhatsApp: {response.text}"
