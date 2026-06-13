#!/bin/bash
#set -x #echo on

##
## SCRIPT: BUILD SEN2AGRI APPLICATION
##
##
## SCRIPT STEPS
##     - CREATE DIR TREE: Sen2AgriApp/install, Sen2AgriApp/build and Sen2AgriApp/rpm_binaries
##     - COMPILE AND INSTALL SEN2AGRI APPLICATION
##     - RPM GENERATION FOR COMPILED SEN2AGRI APPLICATION
################################################################################################
###########################CONFIG PART###########################################################
### DEPENDENCIES FOR GENERATED RPM PACKAGES
: ${PLATFORM_INSTALL_DEP:="-d "qt5-qtbase" -d "qt5-qtbase-postgresql""}

### CONFIG PATHS FOR SCRIPT
: ${DEFAULT_DIR:=$(pwd)}
: ${PLATFORM_NAME_DIR:="Sen2AgriApp"}
  VERSION="5.0.35"
: ${INSTALL_DIR:="install"}
: ${RPM_DIR:="rpm_binaries"}
: ${BUILD_DIR:="build"}
: ${WORKING_DIR_INSTALL:=${PLATFORM_NAME_DIR}/${INSTALL_DIR}}
: ${WORKING_DIR_RPM:=${PLATFORM_NAME_DIR}/${RPM_DIR}}
: ${WORKING_DIR_BUILD:=${PLATFORM_NAME_DIR}/${BUILD_DIR}}
: ${SOURCES_DIR_PATH:=""}
: ${APP_INSTALL_PATH:="${DEFAULT_DIR}/${WORKING_DIR_INSTALL}/sen2agri-install"}
: ${INSTAL_CONFIG_FILE}:=""
: ${CONFIGURATION_NAMES}:=""

################################################################################################
function load_configuration_names()
{
    if [ ! -f "${INSTAL_CONFIG_FILE}" ] ; then
        echo "The config file ${INSTAL_CONFIG_FILE} does not exist! Exiting ..."
        exit 1
    fi

    ALL_CFG_VALUES=($(awk '/\[/{prefix=$0; next} $1{print prefix $0}' ${INSTAL_CONFIG_FILE}))
    if [ ${#ALL_CFG_VALUES[@]} -eq 0 ] ; then
        echo "Couldn't load the config file ${INSTAL_CONFIG_FILE}! Exiting ..."
        exit 1
    fi

    CONFIGURATION_NAMES=()
    # now check the profile and the configuration keys from the active configuration
    for element in "${ALL_CFG_VALUES[@]}"
    do
        if [[ $element == "["*"]CONFIGURATION_NAME"* ]] ; then
            # just check that the current profile is correctly defined and supported
            CONFIGURATION_NAME=$(cut -d "=" -f2 <<< "$element")
            if [ ! -z ${CONFIGURATION_NAME} ] ; then
                CONFIGURATION_NAMES+=(${CONFIGURATION_NAME})
            fi
        fi
    done

    # TODO : Forcing to only Sen2Agri for faster build
    CONFIGURATION_NAMES=()
    # Check services archive name was defined
    if [ ${#CONFIGURATION_NAMES[@]} -eq 0 ] ; then
        echo "No configuration names found ... defaulting to sen2agri ..."
        CONFIGURATION_NAMES+=("sen2agri")
    fi

    echo "CONFIGURATION_NAMES = ${CONFIGURATION_NAMES[@]}"
}

#-----------------------------------------------------------#
function get_SEN2AGRI_sources()
{
   ## build script will reside to sen2agri/packaging
   #get script path
   script_path=$(dirname $0)

   ##go in the folder sen2agri/packaging and exit up one folder into the source root dir sen2agri
   cd $script_path
   cd ..

   #save the sources path
   SOURCES_DIR_PATH=$(pwd)
   INSTAL_CONFIG_FILE="${SOURCES_DIR_PATH}"/install_platform/config_files/install_config.conf
   load_configuration_names
}
#-----------------------------------------------------------#
function compile_SEN2AGRI_app()
{
   #create a build directory
   mkdir -p ${DEFAULT_DIR}/${WORKING_DIR_BUILD}/sen2agri-build
   cd ${DEFAULT_DIR}/${WORKING_DIR_BUILD}/sen2agri-build

   ##compile the sources
   qmake-qt5 $SOURCES_DIR_PATH
   make -j$(nproc)

   ##install
   INSTALL_ROOT=${APP_INSTALL_PATH} make install
}
#-----------------------------------------------------------#
function build_SEN2AGRI_app_RPM_Package()
{
   if [ -d ${APP_INSTALL_PATH}/usr_sen2agri ] ; then
      rm -fR ${APP_INSTALL_PATH}/usr_sen2agri
   fi
   if [ -d ${APP_INSTALL_PATH}/etc_sen2agri ] ; then
      rm -fR ${APP_INSTALL_PATH}/etc_sen2agri
   fi
   mv ${APP_INSTALL_PATH}/usr ${APP_INSTALL_PATH}/usr_sen2agri
   mv ${APP_INSTALL_PATH}/etc ${APP_INSTALL_PATH}/etc_sen2agri


   for CONFIGURATION_NAME in ${CONFIGURATION_NAMES[@]} ; do
       cp -fR ${APP_INSTALL_PATH}/usr_sen2agri ${APP_INSTALL_PATH}/usr
       cp -fR ${APP_INSTALL_PATH}/etc_sen2agri ${APP_INSTALL_PATH}/etc

       ##create a temporary dir
       mkdir -p ${DEFAULT_DIR}/${WORKING_DIR_RPM}/tmp_app

       ###########################################
       #SEN4X-SERVICES
       ###########################################
       ##sen2agri-services will be installed in folder : usr/share/sen2agri/sen2agri-services
       mkdir -p ${APP_INSTALL_PATH}/usr/share/sen2agri/${CONFIGURATION_NAME}-services
       ##sen2agri-services services will be installed in folder : usr/lib/systemd/system
       mkdir -p ${APP_INSTALL_PATH}/usr/lib/systemd/system
       cp -f ${SOURCES_DIR_PATH}/sen2agri-services/dist/* ${APP_INSTALL_PATH}/usr/lib/systemd/system
       ## Added era5 downloader services
       mkdir -p ${APP_INSTALL_PATH}/usr/share/sen2agri/era5-downloader
       cp -f ${SOURCES_DIR_PATH}/era5-downloader/weather_launcher.py ${APP_INSTALL_PATH}/usr/share/sen2agri/era5-downloader
       cp -f ${SOURCES_DIR_PATH}/era5-downloader/dist/* ${APP_INSTALL_PATH}/usr/lib/systemd/system

       if [ "$CONFIGURATION_NAME" != "sen2agri" ] ; then
           # We just rename the files but do not fill them, leaving this in the charge of the installer
           find ${APP_INSTALL_PATH}/etc/sen2agri/ -name "sen2agri*.conf" -exec basename {} ';' | while read name
           do
              newname=${CONFIGURATION_NAME}"$(echo "$name" | cut -c9-)"
              mv "${APP_INSTALL_PATH}/etc/sen2agri/${name}" "${APP_INSTALL_PATH}/etc/sen2agri/${newname}"
           done
           find ${APP_INSTALL_PATH}/usr/lib/systemd/system/ -name "sen2agri*" -exec basename {} ';' | while read name
           do
              newname=${CONFIGURATION_NAME}"$(echo "$name" | cut -c9-)"
              mv "${APP_INSTALL_PATH}/usr/lib/systemd/system/${name}" "${APP_INSTALL_PATH}/usr/lib/systemd/system/${newname}"
           done
           find ${APP_INSTALL_PATH}/usr/bin/ -name "sen2agri*" -exec basename {} ';' | while read name
           do
              newname=${CONFIGURATION_NAME}"$(echo "$name" | cut -c9-)"
              mv "${APP_INSTALL_PATH}/usr/bin/${name}" "${APP_INSTALL_PATH}/usr/bin/${newname}"
           done
        fi

       ##build RPM package
       fpm -s dir -t rpm -n ${CONFIGURATION_NAME}-app -C ${APP_INSTALL_PATH}/ ${PLATFORM_INSTALL_DEP} \
           -v $VERSION \
           --workdir ${DEFAULT_DIR}/${WORKING_DIR_RPM}/tmp_app \
           --config-files etc \
           -p ${DEFAULT_DIR}/${WORKING_DIR_RPM}/${CONFIGURATION_NAME}-app-VERSION.centos7.ARCH.rpm \
           usr etc

       #remove temporary dir
       rm -rf ${DEFAULT_DIR}/${WORKING_DIR_RPM}/tmp_app
       rm -rf ${APP_INSTALL_PATH}/usr
       rm -rf ${APP_INSTALL_PATH}/etc
    done
}

#-----------------------------------------------------------#
function build_dir_tree()
{
   ##go to default dir
   cd ${DEFAULT_DIR}

   ##create platform dir
   if [ ! -d ${PLATFORM_NAME_DIR} ]; then
      mkdir -p ${PLATFORM_NAME_DIR}
   fi

   ##go into platform dir
   cd ${PLATFORM_NAME_DIR}

   ##create install dir
   if [ ! -d ${INSTALL_DIR} ]; then
      mkdir -p ${INSTALL_DIR}
   fi

   ##create rpm dir
   if [ ! -d ${RPM_DIR} ]; then
      mkdir -p ${RPM_DIR}
   fi

   ##create build dir
   if [ ! -d ${BUILD_DIR} ]; then
      mkdir -p ${BUILD_DIR}
   fi

   ##exit from platform dir
   cd ..
}

###########################################################
#####  SEN2AGRI APP install and RPM generation       ######
###########################################################
##create folder tree: build, install and rpm
build_dir_tree

##get sources path
get_SEN2AGRI_sources
#################################################################
#####  SEN2AGRIAPP SERVICES build, install and RPM generation  ##
#################################################################
## SEN2AGRI app sources compile and install
compile_SEN2AGRI_app

##create RPM package
build_SEN2AGRI_app_RPM_Package
