import os, requests
from flask import Flask, request, Response
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

PASTA_ENTRADAS = r'C:\Users\vlula\ScannerOCR\entradas'
os.makedirs(PASTA_ENTRADAS, exist_ok=True)

app = Flask(__name__)

@app.post("/whatsapp")
def whatsapp_webhook():
    # Dados básicos
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "")
    num_media = int(request.form.get("NumMedia", "0"))

    # Se veio mídia e for PDF, baixa
    if num_media > 0:
        content_type = request.form.get("MediaContentType0", "")
        media_url = request.form.get("MediaUrl0", "")
        if content_type == "application/pdf" and media_url:
            # Baixa o PDF
            r = requests.get(media_url, timeout=30)
            r.raise_for_status()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome = f"zap_{stamp}.pdf"
            caminho = os.path.join(PASTA_ENTRADAS, nome)
            with open(caminho, "wb") as f:
                f.write(r.content)
            print(f"📥 Recebido via WhatsApp de {from_number}: {nome}")
            # aqui você pode chamar seu script de processamento (opcional por enquanto)
            # os.system("python renomear_cte_mesma_pasta.py")
            return Response("PDF recebido. Processamento em fila.", 200)

    # Sem mídia ou não-PDF
    return Response("Envie um PDF do CT-e.", 200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
