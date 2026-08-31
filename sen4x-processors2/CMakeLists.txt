cmake_minimum_required(VERSION 3.11)
project(sen2agri-processors-re)

find_package(OTB CONFIG REQUIRED)
find_package(Boost CONFIG REQUIRED COMPONENTS filesystem serialization unit_test_framework)
find_package(CURL CONFIG REQUIRED)

add_subdirectory(Common)
add_subdirectory(Sen4CAP)
add_subdirectory(Sen4Stat)
add_subdirectory(TimeSeriesReader)
add_subdirectory(ProductReaders)
add_subdirectory(merge-statistics)
add_subdirectory(ProductFormatters)
