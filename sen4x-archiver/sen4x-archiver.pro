include(../common.pri)

QT       += core dbus sql

QT       -= gui

TARGET = sen4x-archiver
CONFIG   += console
CONFIG   -= app_bundle

TEMPLATE = app

DESTDIR = bin

INCLUDEPATH += ../Optional

SOURCES += main.cpp \
    archivermanager.cpp

HEADERS += \
    archivermanager.hpp \
    pch.hpp

DISTFILES +=

LIBS += -L$$OUT_PWD/../sen4x-persistence/ -lsen4x-persistence

INCLUDEPATH += $$PWD/../sen4x-persistence
DEPENDPATH += $$PWD/../sen4x-persistence

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-persistence/libsen4x-persistence.a

LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common

INCLUDEPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-common

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a
