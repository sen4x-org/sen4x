include(${OTB_USE_FILE})

add_definitions(-DBOOST_TEST_DYN_LINK)

include_directories(../include)

add_executable(TestTileMetadataWriter TestTileMetadataWriter.cpp)
target_link_libraries(TestTileMetadataWriter
    Sen2AgriPrdMetaWriters
    ${OTB_LIBRARIES}
    "${Boost_LIBRARIES}")
add_test(TestTileMetadataWriter TestTileMetadataWriter)

add_executable(TestProductMetadataWriter TestProductMetadataWriter.cpp)
target_link_libraries(TestProductMetadataWriter
    Sen2AgriPrdMetaWriters
    ${OTB_LIBRARIES}
    "${Boost_LIBRARIES}")
add_test(TestProductMetadataWriter TestProductMetadataWriter)
