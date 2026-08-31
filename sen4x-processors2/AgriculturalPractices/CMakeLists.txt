add_subdirectory(Common)
add_subdirectory(DataExtraction)
add_subdirectory(TimeSeriesAnalysis)
add_subdirectory(LPISDataSelection)

install(FILES ConfigFiles/S4C_L4C_Default_Config.cfg
        DESTINATION usr/share/sen2agri/S4C_L4C_Configurations)

