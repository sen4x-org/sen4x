include(${OTB_USE_FILE})

set(AgriculturalPracticesCommon_HEADERS
    include/AttributeEntry.h
    include/CommonDefs.h
    include/CommonFunctions.h
    include/DataSource.h
    include/DataSourceFactory.h
    include/DeclarationsInfoBase.h
    include/GSAAAttributesTablesReaderBase.h
    include/GSAAAttributesTablesReaderFactory.h
    include/GSAACsvAttributesTablesReader.h
    include/GSAAShpAttributesTablesReader.h
    include/PostgisDataSource.h
    include/PracticeCsvReader.h
    include/PracticeReaderBase.h
    include/PracticeReaderFactory.h
    include/PracticeShpReader.h
    include/ShpDataSource.h
)

set(AgriculturalPracticesCommon_SOURCES
    src/DeclarationsInfoBase.cpp
    src/GSAAAttributesTablesReaderFactory.cpp
    src/GSAACsvAttributesTablesReader.cpp
    src/GSAAShpAttributesTablesReader.cpp
    src/PracticeCsvReader.cpp
    src/PracticeReaderFactory.cpp
    src/PracticeShpReader.cpp
)

add_library(AgriculturalPracticesCommon OBJECT ${AgriculturalPracticesCommon_HEADERS} ${AgriculturalPracticesCommon_SOURCES})

set_target_properties(AgriculturalPracticesCommon PROPERTIES POSITION_INDEPENDENT_CODE ON)

target_include_directories(AgriculturalPracticesCommon PUBLIC include)

target_link_libraries(AgriculturalPracticesCommon PUBLIC
    ${OTB_LIBRARIES}
    Sen2AgriCommonUtils
    ${Boost_LIBRARIES}
)
