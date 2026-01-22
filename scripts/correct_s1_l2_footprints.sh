#!/bin/bash
FOLDER=$1
MYPWD=`pwd`
SCRIPTPATH="$( cd "$(dirname "$0")" ; pwd -P )"

sudo yum install jq -y


if [ "$#" -ne 1 ]; then
    echo "Please provide at least one directory containing products!"
    exit 1
fi

cd $FOLDER

find l2a-s1/ -name '*_AMP.tif' -print0 | while IFS= read -r -d '' line; do IFS='/' read -ra arr <<< $line; ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; gdalinfo -json "$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');" ) | cat | tr '\r\n\t' ' ' >> ~/sql_amp.txt; done;
find l2a-s1/ -name '*_COHE.tif' -print0 | while IFS= read -r -d '' line; do IFS='/' read -ra arr <<< $line; ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; gdalinfo -json "$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');" ) | cat | tr '\r\n\t' ' ' >> ~/sql_cohe.txt; done;


# docker version. Uncomment if needed
#for dir in "$@" ; do
#    cd ${dir}
#    find . -name '*_AMP.tif' -print0 | while IFS= read -r -d '' line; do IFS='/' read -ra arr <<< $line; ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; docker run -t --rm -v ${PWD}:/mnt/data/ osgeo/gdal:ubuntu-full-3.1.2 gdalinfo -json "/mnt/data/$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');" ) | cat | tr '\r\n\t' ' ' >> ~/sql_amp_obj_storage.txt; done;
#    
#    find . -name '*_COHE.tif' -print0 | while IFS= read -r -d '' line; do IFS='/' read -ra arr <<< $line; ( echo "UPDATE product SET geog = st_geogfromtext(TRIM('"; echo 'POLYGON(('; docker run -t --rm -v ${PWD}:/mnt/data/ osgeo/gdal:ubuntu-full-3.1.2 gdalinfo -json "/mnt/data/$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev; echo "))')) WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');"; echo "UPDATE product SET footprint = (SELECT '(' || string_agg(REPLACE(replace(ST_AsText(geom) :: text, 'POINT', ''), ' ', ','), ',') || ')' from ST_DumpPoints(ST_Envelope(geog :: geometry)) WHERE path[2] IN (1, 3)) :: POLYGON WHERE name = TRIM('"; echo ${arr[2]} | rev | cut -c 5- | rev; echo "');" ) | cat | tr '\r\n\t' ' ' >> ~/sql_cohe_obj_storage.txt; done;
#
#done


sudo psql -U postgres -d sen4cap -a -f ~/sql_amp.txt
sudo psql -U postgres -d sen4cap -a -f ~/sql_cohe.txt

sudo psql -U postgres -d sen4cap -a -f ~/sql_amp_obj_storage.txt
sudo psql -U postgres -d sen4cap -a -f ~/sql_cohe_obj_storage.txt

rm ~/sql_amp.txt
rm ~/sql_cohe.txt

cd ${MYPWD}


