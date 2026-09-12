otb_create_application(NAME           GenerateLaiMonoDateMaskFlags
  SOURCES        otbGenerateLaiMonoDateMaskFlags.cpp
  LINK_LIBRARIES Sen2AgriProductReaders ${OTB_LIBRARIES})

otb_create_application(NAME           BVLaiNewProcessor
  SOURCES        otbBVLaiNewProcessor.cxx
  LINK_LIBRARIES Sen2AgriProductReaders Sen2AgriCommonUtils ${OTB_LIBRARIES})

target_include_directories(otbapp_BVLaiNewProcessor PRIVATE ../library)

otb_create_application(NAME           CreateAnglesRaster
  SOURCES        otbCreateAnglesRaster.cpp
  LINK_LIBRARIES Sen2AgriProductReaders ${OTB_LIBRARIES})

otb_create_application(NAME           GenerateDomainQualityFlags
  SOURCES        otbGenerateDomainQualityFlags.cxx
  LINK_LIBRARIES Sen2AgriProductReaders ${OTB_LIBRARIES})

install(TARGETS otbapp_GenerateLaiMonoDateMaskFlags DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_BVLaiNewProcessor DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_CreateAnglesRaster DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_GenerateDomainQualityFlags DESTINATION usr/lib/otb/applications/)
