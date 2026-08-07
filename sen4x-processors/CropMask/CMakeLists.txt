add_subdirectory(PrincipalComponentAnalysis)
add_subdirectory(MajorityVoting)
add_subdirectory(Trimming)
add_subdirectory(Erosion)
add_subdirectory(SpectralFeaturesExtraction)

install(FILES ../../scripts/CropMask.py ../../scripts/CropMaskFused.py
        DESTINATION usr/bin/
	PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE
        GROUP_READ GROUP_EXECUTE
        WORLD_READ WORLD_EXECUTE)

install(FILES crop-mask.lut
        DESTINATION usr/share/sen2agri)
