#!/bin/bash

prd_paths_file="all_sites_s1_products.txt"
results_file="products_with_only_no_data.txt"
touch $results_file
echo "" > $results_file

psql -U admin sen4cap -AXqtc "select full_path from product where satellite_id = 3 and site_id in (16, 20, 22)" > "${prd_paths_file}"

while read p; do
  #p="/mnt/archive/crete23/l2a-s1/SEN4CAP_L2A_S16_V20230428T162314_20230416T162248_VV_102/SEN4CAP_L2A_S16_V20230428T162314_20230416T162248_VV_102_COHE.tif"
  # echo "$p"

  gdal_stats=$(gdalinfo -json -stats $p)
  # echo "$gdal_stats"
  
  if [[ $gdal_stats == *"\"STATISTICS_MAXIMUM\":\"0\""* ]] && [[ $gdal_stats == *"\"STATISTICS_MEAN\":\"0\""* ]] && 
     [[ $gdal_stats == *"\"STATISTICS_MINIMUM\":\"0\""* ]] && [[ $gdal_stats == *"\"STATISTICS_STDDEV\":\"0\""* ]] ; then 
    echo "Product $p statistics are 0"
    echo "$p" >> $results_file
  fi
  
done <"${prd_paths_file}"