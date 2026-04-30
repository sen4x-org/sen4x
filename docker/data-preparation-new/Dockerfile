FROM ghcr.io/lnicola/erdy:0.3.0

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    python3-psycopg2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY data-preparation.py /usr/bin
