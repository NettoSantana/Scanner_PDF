import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()  # lê o .env

sid   = os.getenv("TWILIO_ACCOUNT_SID")
token = os.getenv("TWILIO_AUTH_TOKEN")
w_from = os.getenv("TWILIO_WHATSAPP_FROM")   # ex: whatsapp:+14155238886
w_to   = os.getenv("TWILIO_WHATSAPP_TO")     # ex: whatsapp:+5571986061117

assert sid and token and w_from and w_to, "Variáveis do .env faltando"

client = Client(sid, token)
msg = client.messages.create(
    from_=w_from,
    to=w_to,
    body="✅ ScannerOCR: teste de WhatsApp via Twilio funcionando."
)
print("Mensagem enviada. SID:", msg.sid)
