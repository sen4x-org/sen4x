#!/bin/bash

if [ "$#" -ne 1 ]; then
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

echo "Using DB = ${DB_NAME} and site id = ${SITE_ID} ..."

res_init=(`psql -U admin ${DB_NAME} -tAq -c "select full_path from product where site_id = ${SITE_ID} and product_type_id in (10, 11)"`); for line in "${res_init[@]}" ; do ( gdalinfo -json "$line" | jq -r '.wgs84Extent.coordinates[][]' | tr -s "[," " " | tr "]" "," | xargs | rev | cut -c 2- | rev ) ; done


cd ${MYPWD}





