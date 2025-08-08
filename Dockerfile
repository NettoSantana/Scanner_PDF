# Usar a imagem base do Ubuntu
FROM ubuntu:20.04

# Instalar dependências
RUN apt-get update && \
    apt-get install -y poppler-utils python3 python3-pip python3-venv

# Instalar o PyMuPDF
RUN pip3 install PyMuPDF==1.24.9

# Instalar o requests
RUN pip3 install requests==2.32.4

# Definir o diretório de trabalho
WORKDIR /app

# Copiar os arquivos do projeto
COPY . /app

# Instalar as dependências do Python
RUN python3 -m venv /opt/venv && . /opt/venv/bin/activate && pip install -r requirements.txt

# Comando para rodar o script
CMD ["python3", "renomear_cte_mesma_pasta.py"]
