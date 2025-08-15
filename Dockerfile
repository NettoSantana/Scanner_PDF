# Base Ubuntu
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dependências do sistema (Poppler + ZBar + Python)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      poppler-utils \
      libzbar0 \
      python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

# Virtualenv padrão do container
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV POPPLER_PATH="/usr/bin"

# Diretório de trabalho
WORKDIR /app

# Instalar dependências Python com cache eficiente
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar o restante do projeto
COPY . /app

# Comando padrão (ajuste se mudar o script principal)
CMD bash -lc 'gunicorn -w 2 -k gthread --threads 4 --timeout 120 -b 0.0.0.0:$PORT server:app'
