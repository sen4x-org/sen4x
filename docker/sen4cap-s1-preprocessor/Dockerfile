FROM sen4x/snap:13-ubuntu-24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Minimal runtime deps:
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gcc \
      g++ \
      libgeos-dev \
      libpq-dev \
      build-essential \
      openjdk-21-jre-headless \
      gdal-bin \
      ca-certificates \
      unzip \
      git \
      python3 \
      python3-pip \
      python3-venv

# Java environment
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

RUN mkdir -p /root/.snap

# RUN mkdir -p /mnt/archive/v1/l2a-s1 \
#              /mnt/archive/s1_preprocessing_work_dir \
#              /mnt/archive/repository

WORKDIR /app

# COPY . .
COPY requirements.txt .

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir \
    git+https://github.com/pbrotoisworo/s1-tops-split-analyzer.git@4c0cc3af876499ace32fe3cde7d3f3d05df06a46 && \
    sed -i "s/(?:a|b)/(?:a|b|c|d)/g" \
    /opt/venv/lib/python3.12/site-packages/stsa/stsa.py

RUN pip install --no-cache-dir -r requirements.txt

COPY sen4cap-preprocessing-standalone-v1.jar /app/app.jar
COPY s1_preprocessor.py /usr/bin/
COPY autocrop-raster.py /usr/bin/

ENTRYPOINT []
