#!/bin/bash

if [ "$#" -eq 0 ]; then
    echo "Please provide the site id!"
    exit 1
fi


SITE_ID=$1
MYPWD=`pwd`
SCRIPTPATH="$( cd "$(dirname "$0")" ; pwd -P )"
DB_NAME="sen4stat"

sudo yum install jq -y

if [ "$#" -eq 2 ]; then
    DB_NAME=$2
fi

cur_date=$(date '+%Y%m%d_%H%M%S')

echo "Using DB = ${DB_NAME} and site id = ${SITE_ID} ..."

res_init=(`psql -U admin ${DB_NAME} -tAq -c "select full_path from product where site_id = ${SITE_ID} and product_type_id = 10"`); for line in "${res_init[@]}" ; do ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; gdalinfo -json "$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE full_path = TRIM('"; echo "$line" ; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE full_path = TRIM('"; echo "$line"; echo "');" ) | cat | tr '\r\n\t' ' '; done >> ~/sql_amp_$cur_date.txt

res_init=(`psql -U admin ${DB_NAME} -tAq -c "select full_path from product where site_id = ${SITE_ID} and product_type_id = 11"`); for line in "${res_init[@]}" ; do ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; gdalinfo -json "$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE full_path = TRIM('"; echo "$line" ; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE full_path = TRIM('"; echo "$line"; echo "');" ) | cat | tr '\r\n\t' ' '; done >> ~/sql_cohe_$cur_date.txt



# docker version. Uncomment if needed
#for dir in "$@" ; do
#    cd ${dir}
#    find . -name '*_AMP.tif' -print0 | while IFS= read -r -d '' line; do IFS='/' read -ra arr <<< $line; ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; docker run -t --rm -v ${PWD}:/mnt/data/ osgeo/gdal:ubuntu-full-3.1.2 gdalinfo -json "/mnt/data/$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');" ) | cat | tr '\r\n\t' ' ' >> ~/sql_amp_obj_storage.txt; done;
#    
#    find . -name '*_COHE.tif' -print0 | while IFS= read -r -d '' line; do IFS='/' read -ra arr <<< $line; ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; docker run -t --rm -v ${PWD}:/mnt/data/ osgeo/gdal:ubuntu-full-3.1.2 gdalinfo -json "/mnt/data/$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');" ) | cat | tr '\r\n\t' ' ' >> ~/sql_cohe_obj_storage.txt; done;
#
#done

echo "Do you want to update product footprints (Y/[N])?"
read DoUpdate

if [[ $DoUpdate == "y" || $DoUpdate == "Y" ]] ; then
    sudo psql -U postgres -d ${DB_NAME} -a -f ~/sql_amp_$cur_date.txt
    sudo psql -U postgres -d ${DB_NAME} -a -f ~/sql_cohe_$cur_date.txt

    # sudo psql -U postgres -d ${DB_NAME} -a -f ~/sql_amp_obj_storage.txt
    # sudo psql -U postgres -d ${DB_NAME} -a -f ~/sql_cohe_obj_storage.txt

    echo "Do you want to remove the sql command files (Y/[N])?"
    read DoRemove

    if [[ $DoUpdate == "y" || $DoUpdate == "Y" ]] ; then
        rm ~/sql_amp_$cur_date.txt
        rm ~/sql_cohe_$cur_date.txt
    fi
fi 

cd ${MYPWD}





