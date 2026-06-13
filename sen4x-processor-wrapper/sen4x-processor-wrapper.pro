include(../common.pri)

QT += core network
QT -= gui

TARGET = sen4x-processor-wrapper

DESTDIR = bin

CONFIG -= app_bundle

TEMPLATE = app

SOURCES += \
    commandinvoker.cpp \
    main.cpp \
    processorwrapper.cpp \
    simpleudpinfosclient.cpp \
    simpletcpinfosclient.cpp

HEADERS += \
    abstractexecinfosprotclient.h \
    applicationclosinglistener.h \
    commandinvoker.h \
    icommandinvokerlistener.h \
    processorwrapper.h \
    simpleudpinfosclient.h \
    pch.hpp \
    simpletcpinfosclient.h

target.path = /usr/bin

INSTALLS += target

LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common

INCLUDEPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-common

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a
