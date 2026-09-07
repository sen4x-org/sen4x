FROM docker.io/sen4x/otb:9.1.1 AS builder
RUN apt-get update && \
    apt-get dist-upgrade -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

FROM builder AS build
COPY src /src
RUN --mount=type=cache,target=/build \
    mkdir -p /build && \
    cd /build && \
    cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo /src && \
    cmake --build . --parallel $(nproc) && \
    cmake --install . --prefix /install

FROM docker.io/sen4x/otb:9.1.1
RUN apt-get update && \
    apt-get dist-upgrade -y && \
    apt-get install -y --no-install-recommends \
        python3-lxml \
        python3-pip \
        python3-psycopg2 && \
    curl -LO https://packages.apache.org/artifactory/arrow/ubuntu/apache-arrow-apt-source-latest-noble.deb && \
    apt-get install -y --no-install-recommends ./apache-arrow-apt-source-latest-noble.deb && \
    rm apache-arrow-apt-source-latest-noble.deb && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libarrow-dev \
        libarrow-acero-dev \
        libarrow-compute-dev \
        libarrow-dataset-dev \
        libparquet-dev \
        libfontconfig1-dev \
        libfribidi-dev \
        libharfbuzz-dev \
        libcurl4-openssl-dev libssl-dev libfreetype6-dev libpng-dev libtiff5-dev libjpeg-dev libwebp-dev gfortran liblapack-dev libopenblas-dev libuv1-dev \
        libxml2-dev \
        r-base \
        r-cran-assertthat \
        r-cran-caret \
        r-cran-cpp11 \
        r-cran-e1071 \
        r-cran-dbscan \
        r-cran-dplyr \
        r-cran-fnn \
        r-cran-gsubfn \
        r-cran-igraph \
        r-cran-ranger \
        r-cran-readr \
        r-cran-catools \
        r-cran-tidyverse \
        r-cran-data.table && \
    python3 -m pip install --break-system-packages pyarrow~=25.0.0 && \
    echo "install.packages(c('arrow', 'smotefamily'), Ncpus = $(nproc), repos = c(CRAN = 'https://cran.rstudio.com'))" | LIBARROW_BINARY=true Rscript - && \
    apt-get purge -y --autoremove \
        libfontconfig1-dev \
        libxml2-dev \
        python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=build /install/bin/* /app/otb/bin/
COPY --from=build /install/usr/bin/* /usr/bin/
COPY --from=build /install/usr/lib/otb/applications/* /app/otb/lib/otb/applications/
COPY --from=build /install/usr/lib/*.so /app/otb/lib/
COPY --from=build /install/usr/share/sen2agri/ /usr/share/sen2agri/

COPY crop-type-wrapper.py /usr/bin/
COPY crop-type-parcels.py /usr/bin/
COPY extract-parcels.py /usr/bin/
COPY merge-sar.py /usr/bin/
COPY csv_to_ipc.py /usr/bin/
COPY crop_type.R /usr/bin/
COPY agric_practices_data_extraction.py /usr/bin/
COPY agric_practices_data_extraction.sh /usr/bin/
COPY agric_practices_merge_files.py /usr/bin/
COPY agric_practices_merge_files.sh /usr/bin/
COPY agric_practices_tsa.sh /usr/bin/
COPY extract_practices_infos.sh /usr/bin/
COPY launch_agric_practices.sh /usr/bin/

# TODO(lnicola): try this again when OTB supports Ubuntu 26
# FROM docker.io/sen4x/otb:9.1.1_ubuntu26 AS builder
# RUN apt-get update && \
#     apt-get dist-upgrade -y && \
#     apt-get clean && \
#     rm -rf /var/lib/apt/lists/*

# FROM builder AS build
# COPY src /src
# RUN --mount=type=cache,target=/build \
#     mkdir -p /build && \
#     cd /build && \
#     cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo /src && \
#     cmake --build . --parallel $(nproc) && \
#     cmake --install . --prefix /install

# FROM docker.io/sen4x/otb:9.1.1_ubuntu26
# RUN apt-get update && \
#     apt-get dist-upgrade -y && \
#     apt-get install -y --no-install-recommends \
#         python3-lxml \
#         python3-psycopg2 \
#         python3-pyarrow \
#         libarrow-dev \
#         libarrow-acero-dev \
#         libarrow-dataset-dev \
#         libparquet-dev \
#         r-base \
#         r-cran-assertthat \
#         r-cran-arrow \
#         r-cran-caret \
#         r-cran-cpp11 \
#         r-cran-e1071 \
#         r-cran-fnn \
#         r-cran-dbscan \
#         r-cran-dplyr \
#         r-cran-gsubfn \
#         r-cran-igraph \
#         r-cran-ranger \
#         r-cran-readr \
#         r-cran-catools \
#         r-cran-tidyverse \
#         r-cran-data.table && \
#     echo "install.packages('smotefamily', Ncpus = $(nproc), repos = c(CRAN = 'https://cran.rstudio.com'))" | Rscript - && \
#     apt-get purge -y --autoremove \
#         libxml2-dev && \
#     apt-get clean && \
#     rm -rf /var/lib/apt/lists/*

# COPY --from=build /install/bin/* /app/otb/bin/
# COPY --from=build /install/usr/bin/* /usr/bin/
# COPY --from=build /install/usr/lib/otb/applications/* /app/otb/lib/otb/applications/
# COPY --from=build /install/usr/lib/*.so /app/otb/lib/

# COPY crop-type-wrapper.py /usr/bin/
# COPY crop-type-parcels.py /usr/bin/
# COPY extract-parcels.py /usr/bin/
# COPY merge-sar.py /usr/bin/
# COPY csv_to_ipc.py /usr/bin/
# COPY crop_type.R /usr/bin/
# COPY agric_practices_data_extraction.py /usr/bin/
# COPY agric_practices_data_extraction.sh /usr/bin/
# COPY agric_practices_merge_files.py /usr/bin/
# COPY agric_practices_merge_files.sh /usr/bin/
# COPY agric_practices_tsa.sh /usr/bin/
# COPY extract_practices_infos.sh /usr/bin/
# COPY launch_agric_practices.sh /usr/bin/
