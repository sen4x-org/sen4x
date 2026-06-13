include(../common.pri)

QT += core network
QT -= gui

TARGET = sen4x-monitor-agent

DESTDIR = bin

CONFIG   -= app_bundle

TEMPLATE = app

SOURCES += main.cpp \
    stats.cpp \
    monitor.cpp \
    settings.cpp

HEADERS += \
    pch.hpp \
    stats.hpp \
    monitor.hpp \
    settings.hpp

DISTFILES += dist/sen4x-monitor-agent.conf \
    dist/sen4x-monitor-agent.service

LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common

INCLUDEPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-common

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a

target.path = /usr/bin

systemd-service.path = /usr/lib/systemd/system
systemd-service.files = dist/sen2agri-monitor-agent.service

conf.path = /etc/sen2agri
conf.files = dist/sen2agri-monitor-agent.conf

INSTALLS += target systemd-service conf
