include(${OTB_USE_FILE})

otb_create_application(
  NAME           QuantifyImage
  SOURCES        QuantifyImage.cpp
  LINK_LIBRARIES ${OTB_LIBRARIES} Sen2AgriProductReaders Sen2AgriCommonUtils)

install(TARGETS otbapp_QuantifyImage DESTINATION usr/lib/otb/applications/)
