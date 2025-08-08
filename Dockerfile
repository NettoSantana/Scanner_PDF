# Usar a imagem base do Ubuntu
FROM ubuntu:20.04

# Instalar dependências
RUN apt-get update && \
    apt-get install -y poppler-utils python3 python3-pip python3-venv

# Verificar a instalação do Poppler
RUN pdftoppm -v

# Instalar as dependências Python
RUN pip3 install PyMuPDF==1.24.9
RUN pip3 install requests==2.32.4
RUN pip3 install python-dotenv==1.0.1

# Definir o diretório de trabalho
WORKDIR /app

# Copiar os arquivos do projeto
COPY . /app

# Instalar as dependências do Python
RUN python3 -m venv /opt/venv && . /opt/venv/bin/activate && pip install -r requirements.txt

# Comando para rodar o script
CMD ["python3", "renomear_cte_mesma_pasta.py"]
