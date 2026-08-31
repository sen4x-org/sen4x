include(${OTB_USE_FILE})


otb_create_application(
  NAME           LPISDataSelection
  SOURCES        LPISDataSelection.cxx
                 CountryInfoBase.h CountryInfoBase.cpp
                 CountryInfoFactory.h
                 CzeCountryInfo.h CzeCountryInfo.cpp
                 EspCountryInfo.h EspCountryInfo.cpp
                 ItaCountryInfo.h ItaCountryInfo.cpp
                 LtuCountryInfo.h LtuCountryInfo.cpp
                 NlCountryInfo.h NlCountryInfo.cpp
                 RouCountryInfo.h RouCountryInfo.cpp
                 FraCountryInfo.h FraCountryInfo.cpp
                 DefaultCountryInfo.h DefaultCountryInfo.cpp
  LINK_LIBRARIES ${OTB_LIBRARIES} AgriculturalPracticesCommon MACCSMetadata ${Boost_LIBRARIES})

#if(BUILD_TESTING)
#  add_subdirectory(test)
#endif()

install(TARGETS otbapp_LPISDataSelection DESTINATION usr/lib/otb/applications/)

