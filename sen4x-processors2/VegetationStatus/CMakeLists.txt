add_subdirectory(otb-bv/src)
add_subdirectory(QuantifyImage)

install(FILES lai.map
        DESTINATION usr/share/sen2agri)

install(FILES ConfigFiles/Lai_Bands_Cfgs.cfg
              ConfigFiles/Lai_Bands_S2.cfg
              ConfigFiles/Lai_Bands_L8.cfg
              ConfigFiles/Lai_Bands_Cfgs_Belcam.cfg
              ConfigFiles/Lai_Bands_S2_Belcam_rededge.cfg
              ConfigFiles/Lai_Bands_S2_Belcam_allbands.cfg
              ConfigFiles/Lai_Bands_L8_Belcam.cfg
              ConfigFiles/Algo_S2_V2.0_SL2T_rededge_LAI.txt
              ConfigFiles/Algo_S2_V2.0_SL2T_rededge_FAPAR.txt
              ConfigFiles/Algo_S2_V2.0_SL2T_rededge_FCOVER.txt
              ConfigFiles/Algo_S2_V2.0_SL2T_allbands_LAI.txt
              ConfigFiles/Algo_S2_V2.0_SL2T_allbands_FAPAR.txt
              ConfigFiles/Algo_S2_V2.0_SL2T_allbands_FCOVER.txt
              ConfigFiles/Algo_LANDSAT8OLI_LAI.txt
              ConfigFiles/Algo_LANDSAT8OLI_FAPAR.txt
              ConfigFiles/Algo_LANDSAT8OLI_FCOVER.txt
        DESTINATION usr/share/sen2agri/)
