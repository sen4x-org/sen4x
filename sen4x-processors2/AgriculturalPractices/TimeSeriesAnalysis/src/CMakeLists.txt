include(${OTB_USE_FILE})


otb_create_application(
  NAME           TimeSeriesAnalysis
  SOURCES        otbTimeSeriesAnalysis.cpp
                 TimeSeriesAnalysisTypes.h
                 TimeSeriesAnalysisUtils.h
                 StatisticsInfosReaderBase.h
                 StatisticsInfosReaderFactory.h
                 StatisticsInfosReaderFactory.cpp
                 StatisticsInfosFolderFilesReader.h
                 StatisticsInfosFolderFilesReader.cpp
                 StatisticsInfosXmlReader.cpp
                 StatisticsInfosXmlReader.h
                 StatisticsInfosSingleCsvReader.h
                 StatisticsInfosSingleCsvReader.cpp
                 Markers1CsvReader.h
                 Markers1CsvReader.cpp
                 TsaCSVWriter.h
                 TsaCSVWriter.cpp
                 TsaPlotsWriter.h
                 TsaPlotsWriter.cpp
                 TsaContinuousFileWriter.h
                 TsaContinuousFileWriter.cpp
                 TsaDebugPrinter.h
                 TsaDebugPrinter.cpp
                 TsaPrevPrdReader.h
                 TsaPrevPrdReader.cpp
                 TsaEfaAnalysisBase.h
                 TsaEfaAnalysisBase.cpp
                 TsaDataPreProcessor.h
                 TsaDataPreProcessor.cpp
                 TsaDataExtractor.h
                 TsaDataExtractor.cpp
                 TsaHelperFunctions.h
                 TsaHandlerBase.h
                 TsaHandlerBase.cpp
                 TsaCatchCropAnalysisHandler.h
                 TsaCatchCropAnalysisHandler.cpp
                 TsaFallowAnalysisHandler.cpp
                 TsaFallowAnalysisHandler.h
                 TsaNfcAnalysisHandler.h
                 TsaNfcAnalysisHandler.cpp
                 TsaHarvestOnlyAnalysisHandler.cpp
                 TsaHarvestOnlyAnalysisHandler.h
                 TsaTillageAnalysisHandler.cpp
                 TsaTillageAnalysisHandler.h

  LINK_LIBRARIES ${OTB_LIBRARIES} AgriculturalPracticesCommon MACCSMetadata Sen2AgriPrdMetaWriters ${Boost_LIBRARIES} GSL::gsl EXPAT::EXPAT)

#if(BUILD_TESTING)
#  add_subdirectory(test)
#endif()

install(TARGETS otbapp_TimeSeriesAnalysis DESTINATION usr/lib/otb/applications/)
