add_subdirectory(UpdateSynthesis)
add_subdirectory(WeightCalculation)
add_subdirectory(MaskHandler)
add_subdirectory(CompositeSplitter)
add_subdirectory(DirectionalCorrection)
add_subdirectory(CompositePreprocessing)
add_subdirectory(QuantifyImage)

install(FILES ConfigFiles/bands_mapping_s2.txt
              ConfigFiles/bands_mapping_s2_L8.txt
              ConfigFiles/bands_mapping_L8.txt
              ConfigFiles/bands_mapping_Spot4_L8.txt
              ConfigFiles/bands_mapping_Spot5_L8.txt
              ConfigFiles/bands_mapping_spot5.txt
              ConfigFiles/bands_mapping_spot4.txt
              ConfigFiles/scattering_coeffs_10m.txt
              ConfigFiles/scattering_coeffs_20m.txt
              ConfigFiles/scattering_coeffs_droy_10m.txt
              ConfigFiles/scattering_coeffs_droy_20m.txt
              composite.map 
        DESTINATION usr/share/sen2agri/)
