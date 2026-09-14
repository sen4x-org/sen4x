include(${OTB_USE_FILE})

otb_create_application(
    NAME           ContinuousColorMapping
    SOURCES        ContinuousColorMapping.cxx ContinuousColorMappingFunctor.hxx ContinuousColorMappingFilter.hxx
    LINK_LIBRARIES ${OTB_LIBRARIES})

install(TARGETS otbapp_ContinuousColorMapping DESTINATION usr/lib/otb/applications/)
