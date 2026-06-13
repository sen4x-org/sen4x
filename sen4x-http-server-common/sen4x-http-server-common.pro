include(../common.pri)

QT -= gui
QT += core network sql dbus

TARGET = sen4x-http-server-common
TEMPLATE = lib

CONFIG += staticlib

INCLUDEPATH += ../Optional

SOURCES += \
    qtwebapphttprequest.cpp \
    qtwebapphttpresponse.cpp \
    abstracthttpcontroller.cpp \
    httpserver.cpp \
    qtwebapphttplistener.cpp \
    qtwebapphttprequestmapper.cpp \
    requestmapperbase.cpp \
    abstracthttplistener.cpp

HEADERS += \
    pch.hpp \
    abstracthttprequest.h \
    abstracthttpresponse.h \
    qtwebapphttprequest.h \
    qtwebapphttpresponse.h \
    abstracthttpcontroller.h \
    httpserver.h \
    abstracthttplistener.h \
    qtwebapphttplistener.h \
    qtwebapphttprequestmapper.hpp \
    requestmapperbase.h

QTWEBAPP = -lQtWebApp
CONFIG(debug, debug|release) {
    QTWEBAPP = $$join(QTWEBAPP,,,d)
}

LIBS += -L$$OUT_PWD/../QtWebApp/ $$QTWEBAPP

INCLUDEPATH += $$PWD/../QtWebApp
DEPENDPATH += $$PWD/../QtWebApp

CONFIG(debug, debug|release) {
    LIBQTWEBAPP = $$OUT_PWD/../QtWebApp/libQtWebAppd.so
}
CONFIG(release, debug|release) {
    LIBQTWEBAPP = $$OUT_PWD/../QtWebApp/libQtWebApp.so
}

PRE_TARGETDEPS += $$LIBQTWEBAPP


LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common

INCLUDEPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-common

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a

LIBS += -L$$OUT_PWD/../sen4x-persistence/ -lsen4x-persistence

INCLUDEPATH += $$PWD/../sen4x-persistence
DEPENDPATH += $$PWD/../sen4x-persistence

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-persistence/libsen4x-persistence.a
