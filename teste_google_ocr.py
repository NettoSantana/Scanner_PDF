import os
import shutil
import re
import requests
import xml.etree.ElementTree as ET
from pdf2image import convert_from_path
from PIL import Image
from pyzbar.pyzbar import decode

# Caminhos
PASTA_ENTRADAS = 'entradas'
PASTA_SAIDA = 'renomeados'
POPLER_PATH = r'C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\ScannerOCR\Release-24.08.0-0\poppler-24.08.0\Library\bin'

# Cria pasta de saída se não existir
os.makedirs(PASTA_SAIDA, exist_ok=True)

# Lista PDFs na pasta de entrada
pdfs = [f for f in os.listdir(PASTA_ENTRADAS) if f.lower().endswith('.pdf')]

if not pdfs:
    print("❌ Nenhum arquivo PDF encontrado na pasta 'entradas'.")
    exit(1)

for nome_arquivo in pdfs:
    caminho_pdf = os.path.join(PASTA_ENTRADAS, nome_arquivo)
    print(f"\n📄 Lendo PDF: {nome_arquivo}")

    paginas = convert_from_path(caminho_pdf, dpi=600, poppler_path=POPLER_PATH)
    codigo_detectado = None

    for i, pagina in enumerate(paginas):
        caminho_imagem = f'pagina_temp_{i}.png'
        pagina.save(caminho_imagem, 'PNG')

        print(f"🔍 Verificando página {i + 1}...")
        imagem = Image.open(caminho_imagem)
        codigos = decode(imagem)

        if codigos:
            conteudo = codigos[0].data.decode('utf-8').strip()
            codigo_detectado = conteudo
            print(f"✅ Código detectado: {conteudo}")
            os.remove(caminho_imagem)
            break

        os.remove(caminho_imagem)

    if not codigo_detectado:
        print("❌ Nenhum QR Code ou código de barras encontrado. Arquivo ignorado.")
        continue

    try:
        # Baixa conteúdo da URL (esperado: XML com sujeira)
        resposta = requests.get(codigo_detectado)
        resposta.encoding = 'utf-8'
        xml = resposta.text.strip()

        # Tenta localizar início real do XML
        inicio = xml.find("<GerarNfseResposta")
        if inicio == -1:
            raise ValueError("Tag <GerarNfseResposta> não encontrada.")
        
        xml_limpo = xml[inicio:]

        # Remove caracteres ilegais invisíveis
        xml_limpo = re.sub(r'[^\x09\x0A\x0D\x20-\xFF]', '', xml_limpo)

        # Faz parse do XML limpo
        ns = {'ns': 'http://www.abrasf.org.br/nfse.xsd'}
        root = ET.fromstring(xml_limpo)

        # Extrai nome do prestador
        prestador = root.find('.//ns:PrestadorServico/ns:RazaoSocial', ns)
        nome_prestador = prestador.text if prestador is not None else 'DESCONHECIDO'
        nome_prestador = re.sub(r'\W+', '_', nome_prestador).strip('_')

        # Extrai número da nota
        numero = root.find('.//ns:InfNfse/ns:Numero', ns)
        numero_nf = numero.text if numero is not None else '000'

        # Monta nome final
        nome_arquivo_final = f"{nome_prestador}_NF_{numero_nf}.pdf"
        destino_pdf = os.path.join(PASTA_SAIDA, nome_arquivo_final)

        shutil.copy(caminho_pdf, destino_pdf)
        print(f"📂 Arquivo salvo como: {nome_arquivo_final}")

    except Exception as e:
        print(f"⚠️ Erro ao processar XML da URL: {e}")
        print("❌ Arquivo ignorado.")

print("\n🏁 Todos os arquivos foram processados.")
