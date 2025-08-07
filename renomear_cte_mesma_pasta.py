import os
import re
import fitz  # PyMuPDF
# from twilio.rest import Client  # ← Ativar quando integrar com Twilio

# Caminhos
PASTA_ENTRADAS = r'C:\Users\vlula\ScannerOCR\entradas'
PASTA_SAIDA = r'C:\Users\vlula\ScannerOCR\renomeados'
PASTA_PENDENTES = r'C:\Users\vlula\ScannerOCR\pendentes'

# Garante que as pastas existem
os.makedirs(PASTA_SAIDA, exist_ok=True)
os.makedirs(PASTA_PENDENTES, exist_ok=True)

# Modelos de CTE conhecidos
MODELOS = {
    "WANDER_PEREIRA_DE_MATOS": {
        "regex_emissor": r'\n([A-Z ]{5,})\s+CNPJ:\s*[\d./-]+\s+IE:',
        "regex_cte": r'SÉRIE\s*1\s*(\d{3,6})'
    },
    "WASHINGTON_BALTAZAR_SOUZA_LIMA_ME": {
        "regex_emissor": r'(WASHINGTON\s+BALTAZAR\s+SOUZA\s+LIMA\s+ME)',
        "regex_cte": r'N[ÚU]MERO\s+(\d{3,6})'
    }
}

# Lista todos os PDFs na pasta de entrada
pdfs = [f for f in os.listdir(PASTA_ENTRADAS) if f.lower().endswith('.pdf')]

if not pdfs:
    print("❌ Nenhum PDF encontrado em:", PASTA_ENTRADAS)
    exit(1)

for nome_arquivo in pdfs:
    caminho_pdf = os.path.join(PASTA_ENTRADAS, nome_arquivo)
    print(f"\n📄 Processando: {nome_arquivo}")

    with fitz.open(caminho_pdf) as doc:
        for i, pagina in enumerate(doc):
            nova_doc = fitz.open()
            nova_doc.insert_pdf(doc, from_page=i, to_page=i)

            texto = pagina.get_text()
            nome_emissor = "EMISSOR_DESCONHECIDO"
            numero_cte = "000"
            modelo_usado = None

            # Tenta casar com um dos modelos conhecidos
            for modelo, regras in MODELOS.items():
                if re.search(regras["regex_emissor"], texto, re.IGNORECASE):
                    modelo_usado = modelo
                    match_emissor = re.search(regras["regex_emissor"], texto, re.IGNORECASE)
                    if match_emissor:
                        nome_emissor = match_emissor.group(1).strip()
                        nome_emissor = re.sub(r'\W+', '_', nome_emissor).strip('_')

                    match_cte = re.search(regras["regex_cte"], texto, re.IGNORECASE)
                    if match_cte:
                        numero_cte = match_cte.group(1)

                    break

            # Nome final
            nome_final = f"{nome_emissor}_CTE_{numero_cte}.pdf"

            if not modelo_usado:
                print(f"⚠️ Novo modelo detectado na página {i+1}. Enviado para pendentes.")

                # Salva PDF em pendentes
                caminho_destino = os.path.join(PASTA_PENDENTES, nome_final)
                nova_doc.save(caminho_destino)

                # Salva texto extraído
                with open(os.path.join(PASTA_PENDENTES, f"{nome_final}.txt"), "w", encoding="utf-8") as f:
                    f.write(texto)

                # Aqui futuramente será o envio pelo Twilio
                """
                account_sid = 'SEU_ACCOUNT_SID'
                auth_token = 'SEU_AUTH_TOKEN'
                client = Client(account_sid, auth_token)
                client.messages.create(
                    from_='whatsapp:+14155238886',  # Número do Twilio Sandbox
                    body=f"⚠️ Novo modelo de CTE detectado: {nome_final}",
                    to='whatsapp:+55SEU_NUMERO'
                )
                """
            else:
                # Salva PDF na pasta renomeados
                caminho_destino = os.path.join(PASTA_SAIDA, nome_final)
                nova_doc.save(caminho_destino)
                print(f"✅ Página {i+1} ({modelo_usado}) salva como: {nome_final}")

            nova_doc.close()
