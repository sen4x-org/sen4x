include(../common.pri)

QT -= gui
QT += core dbus sql network

DESTDIR = bin

CONFIG += console
CONFIG -= app_bundle

INCLUDEPATH += ../Optional

TEMPLATE = app

TARGET = sen4x-scheduler

SOURCES += main.cpp \
    taskloader.cpp \
    schedulerapp.cpp \
    taskplanner.cpp \
    orchestratorproxy.cpp \
    resourcereader.cpp \
    runestimator.cpp \
    databasetaskloader.cpp \
    dbusorchestratorproxy.cpp \
    httporchestratorproxy.cpp

#adaptor.files = ../dbus-interfaces/org.esa.sen2agri.orchestrator.xml
#adaptor.header_flags = -i ../sen4x-common/model.hpp

#DBUS_ADAPTORS += adaptor

orchestrator_interface.files = ../dbus-interfaces/org.esa.sen2agri.orchestrator.xml
orchestrator_interface.header_flags = -i ../sen4x-common/model.hpp

DBUS_INTERFACES += orchestrator_interface

DISTFILES += \
    dist/sen2agri-scheduler.service

LIBS += -L$$OUT_PWD/../sen4x-persistence/ -lsen4x-persistence
LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common


INCLUDEPATH += $$PWD/../sen4x-common
INCLUDEPATH += $$PWD/../sen4x-persistence
DEPENDPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-persistence

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a
PRE_TARGETDEPS += $$OUT_PWD/../sen4x-persistence/libsen4x-persistence.a

target.path = /usr/bin

systemd-service.path = /usr/lib/systemd/system
systemd-service.files = dist/sen2agri-scheduler.service

INSTALLS += target systemd-service

HEADERS += \
    pch.hpp \
    scheduledtask.hpp \
    taskloader.hpp \
    schedulerapp.hpp \
    taskplanner.hpp \
    resourcereader.hpp \
    orchestratorproxy.hpp \
    runestimator.hpp \
    databasetaskloader.hpp \
    dbusorchestratorproxy.hpp \
    httporchestratorproxy.hpp
