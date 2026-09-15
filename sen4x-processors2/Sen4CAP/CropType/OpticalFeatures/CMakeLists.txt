include(${OTB_USE_FILE})

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
