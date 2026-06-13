include(../common.pri)

QT -= gui
QT += dbus sql

TARGET = sen4x-persistence
TEMPLATE = lib

CONFIG += staticlib

INCLUDEPATH += ../Optional

SOURCES += \
    persistencemanager.cpp \
    dbprovider.cpp \
    sql_error.cpp \
    sqldatabaseraii.cpp \
    settings.cpp \
    serializedevent.cpp \
    credential_utils.cpp

HEADERS += \
    persistencemanager.hpp \
    dbprovider.hpp \
    sql_error.hpp \
    pch.hpp \
    sqldatabaseraii.hpp \
    asyncdbustask.hpp \
    settings.hpp \
    serializedevent.hpp \
    credential_utils.hpp

DISTFILES += dist/sen2agri.conf

LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common

INCLUDEPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-common

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a

conf.path = /etc/sen2agri
conf.files = dist/sen2agri.conf

INSTALLS += conf
