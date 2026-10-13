FROM ghcr.io/lnicola/erdy:0.3.0

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    python3-psycopg2 \
    python3-pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python3 /usr/bin/python

RUN python -m pip install --break-system-packages docker

COPY data-preparation.py /usr/bin
COPY compute-tile-bounds.py /usr/bin

COPY check_shp.py /usr/bin
COPY data-preparation-s4s.py /usr/bin
COPY read_shp_cols.py /usr/bin
COPY s4c_l4b_import_config.py /usr/bin
COPY s4c_l4c_export_all_practices.py /usr/bin
COPY s4c_l4c_import_config.py /usr/bin
COPY s4c_l4c_import_practice.py /usr/bin
COPY s4c_mdb3_input_tables.py /usr/bin
COPY t-rex-genconfig.py /usr/bin
COPY sen2agri_import_uploaded_insitu.py /usr/bin
COPY s4s-yield-safy-params-import.py /usr/bin
COPY s4s-yield-su-historical-data-import.py /usr/bin
COPY s4s-admin-units-import.py /usr/bin

