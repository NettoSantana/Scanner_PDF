import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

def _ensure_whatsapp_prefix(phone: str) -> str:
    if not phone:
        return phone
    return phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

def main():
    load_dotenv()  # carrega variáveis do .env

    sid    = os.getenv("TWILIO_ACCOUNT_SID")
    token  = os.getenv("TWILIO_AUTH_TOKEN")
    w_from = os.getenv("TWILIO_WHATSAPP_FROM")  # ex.: whatsapp:+14155238886
    w_to   = os.getenv("TWILIO_WHATSAPP_TO")    # ex.: whatsapp:+5571986061117

    missing = [k for k, v in {
        "TWILIO_ACCOUNT_SID": sid,
        "TWILIO_AUTH_TOKEN": token,
        "TWILIO_WHATSAPP_FROM": w_from,
        "TWILIO_WHATSAPP_TO": w_to,
    }.items() if not v]
    if missing:
        raise EnvironmentError(f"❌ Variáveis ausentes no .env: {', '.join(missing)}")

    w_from = _ensure_whatsapp_prefix(w_from)
    w_to   = _ensure_whatsapp_prefix(w_to)

    try:
        client = Client(sid, token)
        client.http_client.timeout = 15  # timeout defensivo

        msg = client.messages.create(
            from_=w_from,
            to=w_to,
            body="✅ ScannerOCR: teste de WhatsApp via Twilio funcionando."
        )
        print(f"✅ Mensagem enviada para {w_to}. SID: {msg.sid}")
    except TwilioRestException as e:
        # Erros da API Twilio (credencial, número inválido, sandbox, etc.)
        detalhes = getattr(e, "msg", str(e))
        codigo   = getattr(e, "code", None)
        status   = getattr(e, "status", None)
        print(f"❌ TwilioRestException (status={status}, code={codigo}): {detalhes}")
        raise
    except Exception as e:
        print(f"❌ Erro inesperado ao enviar WhatsApp: {e}")
        raise

if __name__ == "__main__":
    main()
