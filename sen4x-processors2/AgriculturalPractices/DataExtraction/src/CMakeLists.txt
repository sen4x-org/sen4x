include(${OTB_USE_FILE})

include_directories(../../../Filters)

otb_create_application(
  NAME           AgricPractDataExtraction
  SOURCES        otbAgricPractDataExtraction.cxx
                 otbPersistentSamplingFilterBase.h
                 otbPersistentSamplingFilterBase.txx
                 otbOGRDataToClassStatisticsFilter.h
                 otbOGRDataToClassStatisticsFilter.txx
                 otbMaskedIteratorDecorator.h
                 otbMaskedIteratorDecorator.txx
                 otbAgricPractDataExtrFileWriter2.h
                 otbAgricPractDataExtrFileWriter2.txx
                 DeclarationsInfo.h
                 DeclarationsInfo.cpp

  LINK_LIBRARIES ${OTB_LIBRARIES} AgriculturalPracticesCommon MACCSMetadata Sen2AgriPrdMetaWriters ${Boost_LIBRARIES} Sen2AgriCommonUtils EXPAT::EXPAT)

otb_create_application(
  NAME           AgricPractMergeDataExtractionFiles
  SOURCES        otbAgricPractMergeDataExtractionFiles.cxx
  LINK_LIBRARIES ${OTB_LIBRARIES} AgriculturalPracticesCommon MACCSMetadata ${Boost_LIBRARIES} EXPAT::EXPAT)

set_target_properties(otbapp_AgricPractMergeDataExtractionFiles
                      PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)

otb_create_application(
  NAME           IndexAgricPracticesXml
  SOURCES        otbIndexAgricPracticesXml.cxx
  LINK_LIBRARIES ${OTB_LIBRARIES} AgriculturalPracticesCommon MACCSMetadata ${Boost_LIBRARIES})

#otb_create_application(
#  NAME           AgricPracticesXmlToTxtFiles
#  SOURCES        CommonFunctions.h otbAgricPracticesXmlToTxtFiles.cxx
#  LINK_LIBRARIES ${OTBExtensions} ${OTB_LIBRARIES} ${OTBCommon_LIBRARIES} ${OTBITK_LIBRARIES} MACCSMetadata ${Boost_LIBRARIES})

#if(BUILD_TESTING)
#  add_subdirectory(test)
#endif()

install(TARGETS otbapp_AgricPractDataExtraction DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_AgricPractMergeDataExtractionFiles DESTINATION usr/lib/otb/applications/)
install(TARGETS otbapp_IndexAgricPracticesXml DESTINATION usr/lib/otb/applications/)
#install(TARGETS otbapp_AgricPracticesXmlToTxtFiles DESTINATION usr/lib/otb/applications/)
