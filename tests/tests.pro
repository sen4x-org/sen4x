include(../common.pri)

QT += core testlib dbus
QT -= gui

TARGET = tests

DESTDIR = bin

CONFIG -= app_bundle

TEMPLATE = app

INCLUDEPATH += ../Optional

SOURCES += main.cpp \
    testqstring.cpp \
    serialization.cpp \
    reflector.cpp \
    serialization-ops.cpp \
    schedulertests.cpp \
    testscheduledtaskloader.cpp \
    testorcherstratorproxy.cpp \
    producthandlertests.cpp

# cannot link to scheduler app, the files will be included in this project
SOURCES += ../sen4x-scheduler/taskloader.cpp \
    ../sen4x-scheduler/schedulerapp.cpp \
    ../sen4x-scheduler/taskplanner.cpp \
    ../sen4x-scheduler/orchestratorproxy.cpp \
    ../sen4x-scheduler/resourcereader.cpp \
    ../sen4x-scheduler/runestimator.cpp \
    ../sen4x-orchestrator/processor/products/l2aproducthelper.cpp \
    ../sen4x-orchestrator/processor/products/generichighlevelproducthelper.cpp \
    ../sen4x-orchestrator/processor/products/l3bproducthelper.cpp \
    ../sen4x-orchestrator/processor/products/s1l2producthelper.cpp \
    ../sen4x-orchestrator/processor/products/productdetails.cpp \
    ../sen4x-orchestrator/processor/products/producthelper.cpp \
    ../sen4x-orchestrator/processor/products/producthelperfactory.cpp \
    ../sen4x-orchestrator/processor/products/maskedl2aproducthelper.cpp

LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common

INCLUDEPATH += $$PWD/../sen4x-common
INCLUDEPATH += $$PWD/../sen4x-scheduler
INCLUDEPATH += $$PWD/../sen4x-orchestrator
DEPENDPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-scheduler
DEPENDPATH += $$PWD/../sen4x-orchestrator

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a

adaptor.files = reflector.xml
adaptor.header_flags = -i ../sen4x-common/model.hpp

DBUS_ADAPTORS += adaptor

interface.files = reflector.xml
interface.header_flags = -i ../sen4x-common/model.hpp

DBUS_INTERFACES += interface

orchestrator_interface.files = ../dbus-interfaces/org.esa.sen2agri.orchestrator.xml
orchestrator_interface.header_flags = -i ../sen4x-common/model.hpp

DBUS_INTERFACES += orchestrator_interface

HEADERS += \
    testqstring.hpp \
    serialization.hpp \
    reflector.hpp \
    serialization-ops.hpp \
    pch.hpp \
    schedulertests.h \
    testscheduletaskloader.hpp \
    testorcherstratorproxy.h \
    producthandlertests.h

HEADERS += \
    ../sen4x-scheduler/scheduledtask.hpp \
    ../sen4x-scheduler/taskloader.hpp \
    ../sen4x-scheduler/schedulerapp.hpp \
    ../sen4x-scheduler/taskplanner.hpp \
    ../sen4x-scheduler/resourcereader.hpp \
    ../sen4x-scheduler/orchestratorproxy.hpp \
    ../sen4x-scheduler/runestimator.hpp \
    ../sen4x-orchestrator/processor/products/l2aproducthelper.h \
    ../sen4x-orchestrator/processor/products/generichighlevelproducthelper.h \
    ../sen4x-orchestrator/processor/products/l3bproducthelper.h \
    ../sen4x-orchestrator/processor/products/s1l2producthelper.h \
    ../sen4x-orchestrator/processor/products/producthelper.h \
    ../sen4x-orchestrator/processor/products/producthelperfactory.h \
    ../sen4x-orchestrator/processor/products/maskedl2aproducthelper.h


DISTFILES += \
    reflector.xml
