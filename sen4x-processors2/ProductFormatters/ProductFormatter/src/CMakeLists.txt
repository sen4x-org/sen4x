include(${OTB_USE_FILE})



otb_create_application(
  NAME           ProductFormatter
  SOURCES        ProductFormatter.cpp
  LINK_LIBRARIES ${OTB_LIBRARIES} Sen2AgriProductReaders Sen2AgriPrdMetaWriters Sen2AgriCommonUtils Sen2AgriXmlUtils ${Boost_LIBRARIES})

install(TARGETS otbapp_ProductFormatter DESTINATION usr/lib/otb/applications/)
