include(${OTB_USE_FILE})

include_directories(../../../../AgriculturalPractices/Common/include)


otb_create_application(
  NAME           Markers1Extractor
  SOURCES        otbMarkers1Extractor.cxx
                 otbPersistentSamplingFilterBase.h
                 otbPersistentSamplingFilterBase.txx
                 otbOGRDataToClassStatisticsFilter.h
                 otbOGRDataToClassStatisticsFilter.txx
                 otbMaskedIteratorDecorator.h
                 otbMaskedIteratorDecorator.txx
                 otbStopwatch.h
                 otbStopwatch.cxx
                 otbMarkers1CsvWriter.h
                 otbMarkers1CsvWriter.txx

  LINK_LIBRARIES ${OTB_LIBRARIES} MACCSMetadata Sen2AgriProductReaders ${Boost_LIBRARIES} Sen2AgriCommonUtils
)

otb_create_application(
  NAME           Markers1CsvMerge
  SOURCES        otbMarkers1CsvMerge.cxx

  LINK_LIBRARIES ${OTB_LIBRARIES} ${Boost_LIBRARIES} Sen2AgriCommonUtils
)

otb_create_application(
  NAME           Markers2Extractor
  SOURCES        otbMarkers2Extractor.cxx

  LINK_LIBRARIES ${OTB_LIBRARIES} ${Boost_LIBRARIES} Sen2AgriCommonUtils
)

otb_create_application(
  NAME           MdbFromLabelImage
  SOURCES        otbMdbFromLabelImage.cxx
                 otbMarkersFromLabelImageFilter.h
                 otbMarkersFromLabelImageFilter.hxx

  LINK_LIBRARIES ${OTB_LIBRARIES} MACCSMetadata Sen2AgriProductReaders ${Boost_LIBRARIES} Sen2AgriCommonUtils
)

install(TARGETS otbapp_Markers1Extractor DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_Markers1CsvMerge DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_Markers2Extractor DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_MdbFromLabelImage DESTINATION usr/lib/otb/applications/)
