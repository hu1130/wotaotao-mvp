# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    APP_HOME=/app

WORKDIR ${APP_HOME}

RUN sed -i \
        -e 's|https://mirrors.tuna.tsinghua.edu.cn/debian-security|http://mirrors.cloud.aliyuncs.com/debian-security|g' \
        -e 's|https://mirrors.tuna.tsinghua.edu.cn/debian|http://mirrors.cloud.aliyuncs.com/debian|g' \
        -e 's|http://deb.debian.org/debian-security|http://mirrors.cloud.aliyuncs.com/debian-security|g' \
        -e 's|http://deb.debian.org/debian|http://mirrors.cloud.aliyuncs.com/debian|g' \
        -e 's|http://security.debian.org/debian-security|http://mirrors.cloud.aliyuncs.com/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        gcc \
        g++ \
        libasound2 \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libsndfile1 \
        libsdl2-2.0-0 \
        libv4l-0 \
        libxext6 \
        libxrender1 \
        make \
        nodejs \
        npm \
        portaudio19-dev \
        v4l-utils \
    && rm -rf /var/lib/apt/lists/*

ARG REQUIREMENTS_FILE=requirements.txt
ARG PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
COPY ${REQUIREMENTS_FILE} ./requirements.txt
RUN pip install -r requirements.txt -i ${PYPI_INDEX_URL}

COPY avatar/package*.json ./avatar/
RUN cd avatar \
    && npm config set registry https://registry.npmmirror.com \
    && npm ci --omit=dev

# Shared modules are copied first; server role adapters and divergent modules
# overlay them in the final runtime tree.
COPY --from=shared_runtime . ./
COPY . .

RUN mkdir -p cache avatar/cache employees knowledge_base

EXPOSE 8000 3456

FROM runtime AS api
CMD ["python", "api_server.py"]

FROM runtime AS avatar
WORKDIR /app/avatar
CMD ["node", "server.js"]

FROM runtime AS recognizer
CMD ["python", "app.py"]
