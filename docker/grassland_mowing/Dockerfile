FROM osgeo/gdal:ubuntu-full-3.4.1

LABEL maintainer="cosmin@c-s.ro" \
    description="Grassland mowing scripts"

RUN apt-get update && \
    apt-get install -y python3-pip && apt-get -y install binutils libproj-dev libgdal-dev  gdal-bin &&  \
    apt-get install -y python3-lxml python3-pip python3-psycopg2 python3-toml && apt-get clean && \
    rm -rf /var/lib/apt/lists/* && python3 -m pip install docker

RUN python3 -m pip install pandas~=1.3 numpy~=1.20 scipy~=1.5.3 lxml~=4.6.2 pyarrow~=5.0.0 scikit-learn mlxtend rasterio rioxarray shapely

COPY GrasslandMowing /usr/share/sen2agri/S4C_L4B_GrasslandMowing/Bin/
COPY GrasslandMowing/bin /usr/share/sen2agri/S4C_L4B_GrasslandMowing/Bin/

COPY generate_grassland_mowing_input_shp_wrp.py /usr/bin/
COPY s4c-l4b-extract-products-wrp.py /usr/bin/


