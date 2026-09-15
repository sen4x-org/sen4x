include(${OTB_USE_FILE})

otb_create_application(
  NAME
  OpticalFeatures
  SOURCES
  OpticalFeatures.cpp
  ../Filters/otbCropTypeFeatureExtractionFilter.h
  ../Filters/otbCropTypeFeatureExtractionFilter.txx
  ../Filters/otbTemporalResamplingFilter.h
  ../Filters/otbTemporalResamplingFilter.txx
  ../Filters/CropTypePreprocessing.h
  ../Filters/RedEdgeBandsExtractor.h
  LINK_LIBRARIES
  ${OTB_LIBRARIES}
  MACCSMetadata
  TimeSeriesReader)

include_directories(../../../Common/OTBExtensions)
include_directories(../../../Common/Filters)

install(TARGETS otbapp_OpticalFeatures DESTINATION usr/lib/otb/applications/)

otb_create_application(
  NAME
  OpticalFeaturesRewrite
  SOURCES
  OpticalFeaturesRewrite.cpp
  LINK_LIBRARIES
  ${OTB_LIBRARIES})

set_target_properties(otbapp_OpticalFeaturesRewrite
                      PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)

install(TARGETS otbapp_OpticalFeaturesRewrite
        DESTINATION usr/lib/otb/applications/)
