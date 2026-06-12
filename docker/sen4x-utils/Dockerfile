FROM osgeo/gdal:ubuntu-small-3.6.3

LABEL maintainer="cosmin@c-s.ro" \
    description="Sen4CAP Utils"

RUN apt-get update && \
    apt-get install -y python3-pip && apt-get -y install binutils libproj-dev libgdal-dev  gdal-bin &&  \
    apt-get install -y python3-lxml python3-pip python3-psycopg2 python3-toml && apt-get clean && \
    rm -rf /var/lib/apt/lists/* && python3 -m pip install docker


RUN pip install --upgrade pip

RUN python3 -m pip install pandas numpy scipy lxml pyarrow

RUN pip install pystac==1.10.1 pystac-client==0.7.7

# RUN python3 -m pip install gdal pandas numpy scipy lxml

COPY utility_scripts/stac/* /usr/bin/
COPY utility_scripts/iaas_sen4cap_helpers/general/* /usr/bin/
COPY utility_scripts/iaas_sen4cap_helpers/l3b/l3b_filter_processed_l2a.py /usr/bin/
COPY utility_scripts/iaas_sen4cap_helpers/l3b/l3b_processor_entry.py /usr/bin/
COPY utility_scripts/iaas_sen4cap_helpers/l4x/l4x_processor_entry.py /usr/bin/
COPY stac-search.py /usr/bin/
COPY data-preparation.py /usr/bin/

