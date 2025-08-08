# Use uma imagem base do Ubuntu
FROM ubuntu:20.04

# Atualize os pacotes e instale o Poppler
RUN apt-get update && apt-get install -y poppler-utils python3 python3-pip python3-venv

# Defina o diretório de trabalho
WORKDIR /app

# Copie os arquivos do projeto para o diretório de trabalho
COPY . /app

# Instale as dependências do Python
RUN python3 -m venv /opt/venv && . /opt/venv/bin/activate && pip install -r requirements.txt

# Defina o comando para rodar o script Python
CMD ["python3", "renomear_cte_mesma_pasta.py"]
