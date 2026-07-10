include(../common.pri)

QT -= gui
QT += core dbus sql network

TARGET = sen4x-orchestrator

DESTDIR = bin

CONFIG -= app_bundle

INCLUDEPATH += ../Optional

TEMPLATE = app

adaptor.files = ../dbus-interfaces/org.esa.sen2agri.orchestrator.xml
adaptor.header_flags = -i ../sen4x-common/model.hpp

DBUS_ADAPTORS += adaptor

processors_executor_interface.files = ../dbus-interfaces/org.esa.sen2agri.processorsExecutor.xml
processors_executor_interface.header_flags = -i ../sen4x-common/model.hpp

DBUS_INTERFACES += processors_executor_interface

SOURCES += main.cpp \
    orchestrator.cpp \
    orchestratorworker.cpp \
    eventprocessingcontext.cpp \
    executioncontextbase.cpp \
    processorhandler.cpp \
    processorhandlerhelper.cpp \
    schedulingcontext.cpp \
    tasktosubmit.cpp \
    stepexecutiondecorator.cpp \
    productdetailsbuilder.cpp \
    \
    processor/croptypehandler.cpp \
    processor/cropmaskhandler.cpp \
    processor/compositehandler.cpp \
    processor/compositehandlerindicators.cpp \
    processor/compositehandlers1.cpp \
    processor/genericcompositehandlerbase.cpp \
    processor/ndvihandler.cpp \
    processor/phenondvihandler.cpp \
    processor/maccshdrmeananglesreader.cpp \
    processor/masked_l2a_handler.cpp \
    processor/agricpracticeshandler.cpp \
    processor/grasslandmowinghandler.cpp \
    processor/trex_handler.cpp \
    processor/zarr_handler.cpp \
    processor/s4s_permanent_crop_handler.cpp \
    processor/s4s_croptypemappinghandler.cpp \
    processor/s4c_utils.cpp \
    processor/s4c_markersdb1.cpp \
    processor/s4c_mdb1_dataextract_steps_builder.cpp \
    processor/s4c_croptypehandler.cpp \
    processor/s4c_heterogeneity_handler.cpp \
    processor/s4c_baresoil_handler.cpp \
    processor/s4c_change_detection_handler.cpp \
    processor/s4s_yieldhandler.cpp \
    \
    processor/lairetrhandler_multidt_base.cpp \
    processor/lairetrievalhandler.cpp \
    processor/lairetrievalhandler_l3b.cpp \
    processor/lairetrievalhandler_l3b_new.cpp \
    processor/lairetrievalhandler_l3b_individual.cpp \
    processor/lairetrievalhandler_l3c.cpp \
    processor/lairetrievalhandler_l3d.cpp \
    \
    processor/products/producthelper.cpp \
    processor/products/producthelperfactory.cpp \
    processor/products/productdetails.cpp \
    processor/products/generichighlevelproducthelper.cpp \
    processor/products/l2aproducthelper.cpp \
    processor/products/l3bproducthelper.cpp \
    processor/products/s1l2producthelper.cpp \
    processor/products/maskedl2aproducthelper.cpp \
    processor/products/tilestimeseries.cpp \
    processor/products/lpisinfosextractor.cpp \
    \
    processor/yield/s4s_yield.cpp \
    processor/yield/s4s_yield_features.cpp \
    processor/yield/s4s_yield_features_handler.cpp \
    processor/yield/s4s_yield_handler_new.cpp \
    processor/yield/s4s_yield_su_features_handler.cpp \
    processor/yield/s4s_yield_su_handler_new.cpp \
    \
    http/controller/orchestratorcontroller.cpp \
    adaptor/dbusorchestratoradaptor.cpp \
    adaptor/httporchestratoradaptor.cpp \
    \
    executorclient/executorproxy.cpp \
    executorclient/dbusexecutorproxy.cpp \
    executorclient/httpexecutorproxy.cpp \
    executorclient/executorproxyfactory.cpp \
    processor/s4c_tillage_handler.cpp

HEADERS += \
    pch.hpp \
    orchestrator.hpp \
    orchestratorworker.hpp \
    executioncontextbase.hpp \
    eventprocessingcontext.hpp \
    processorhandler.hpp \
    processorhandlerhelper.h \
    schedulingcontext.h \
    tasktosubmit.hpp \
    stepexecutiondecorator.h \
    productdetailsbuilder.h \
    \
    processor/croptypehandler.hpp \
    processor/cropmaskhandler.hpp \
    processor/compositehandler.hpp \
    processor/compositehandlerindicators.hpp \
    processor/compositehandlers1.hpp \
    processor/genericcompositehandlerbase.hpp \
    processor/ndvihandler.hpp \
    processor/phenondvihandler.hpp \
    processor/maccshdrmeananglesreader.hpp \
    processor/masked_l2a_handler.hpp \
    processor/agricpracticeshandler.hpp \
    processor/grasslandmowinghandler.hpp \
    processor/trex_handler.hpp \
    processor/zarr_handler.hpp \
    processor/s4s_permanent_crop_handler.hpp \
    processor/s4s_croptypemappinghandler.hpp \
    processor/s4c_utils.hpp \
    processor/s4c_markersdb1.hpp \
    processor/s4c_mdb1_dataextract_steps_builder.hpp \
    processor/s4c_croptypehandler.hpp \
    processor/s4c_heterogeneity_handler.hpp \
    processor/s4c_baresoil_handler.hpp \
    processor/s4c_change_detection_handler.hpp \
    processor/s4s_yieldhandler.hpp \
    \
    processor/lairetrhandler_multidt_base.hpp \
    processor/lairetrievalhandler.hpp \
    processor/lairetrievalhandler_l3b.hpp \
    processor/lairetrievalhandler_l3b_new.hpp \
    processor/lairetrievalhandler_l3b_individual.hpp \
    processor/lairetrievalhandler_l3c.hpp \
    processor/lairetrievalhandler_l3d.hpp \
    \
    processor/products/producthelper.h \
    processor/products/producthelperfactory.h \
    processor/products/productdetails.h \
    processor/products/generichighlevelproducthelper.h \
    processor/products/l2aproducthelper.h \
    processor/products/l3bproducthelper.h \
    processor/products/s1l2producthelper.h \
    processor/products/maskedl2aproducthelper.h \
    processor/products/tilestimeseries.hpp \
    processor/products/lpisinfosextractor.h \
    \
    processor/yield/s4s_yield.hpp \
    processor/yield/s4s_yield_features.hpp \
    processor/yield/s4s_yield_features_handler.hpp \
    processor/yield/s4s_yield_handler_new.hpp \
    processor/yield/s4s_yield_su_features_handler.hpp \
    processor/yield/s4s_yield_su_handler_new.hpp \
    \
    http/controller/orchestratorcontroller.hpp \
    adaptor/dbusorchestratoradaptor.h \
    adaptor/httporchestratoradaptor.h \
    \
    executorclient/executorproxy.hpp \
    executorclient/dbusexecutorproxy.hpp \
    executorclient/httpexecutorproxy.hpp \
    executorclient/executorproxyfactory.h \
    processor/yield/s4s_yield_common.h \
    processor/s4c_tillage_handler.hpp

DISTFILES += \
    ../dbus-interfaces/org.esa.sen2agri.orchestrator.xml \
    dist/org.esa.sen2agri.orchestrator.conf \
    dist/org.esa.sen2agri.orchestrator.service \
    dist/sen2agri-orchestrator.service

target.path = /usr/bin

interface.path = /usr/share/dbus-1/interfaces
interface.files = ../dbus-interfaces/org.esa.sen2agri.orchestrator.xml

dbus-policy.path = /etc/dbus-1/system.d
dbus-policy.files = dist/org.esa.sen2agri.orchestrator.conf

dbus-service.path = /usr/share/dbus-1/system-services
dbus-service.files = dist/org.esa.sen2agri.orchestrator.service

systemd-service.path = /usr/lib/systemd/system
systemd-service.files = dist/sen2agri-orchestrator.service

INSTALLS += target interface dbus-policy dbus-service systemd-service

LIBS += -L$$OUT_PWD/../sen4x-persistence/ -lsen4x-persistence

INCLUDEPATH += $$PWD/../sen4x-persistence
DEPENDPATH += $$PWD/../sen4x-persistence

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-persistence/libsen4x-persistence.a

LIBS += -L$$OUT_PWD/../sen4x-common/ -lsen4x-common

INCLUDEPATH += $$PWD/../sen4x-common
DEPENDPATH += $$PWD/../sen4x-common

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-common/libsen4x-common.a

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


LIBS += -L$$OUT_PWD/../sen4x-http-server-common/ -lsen4x-http-server-common

INCLUDEPATH += $$PWD/../sen4x-http-server-common
DEPENDPATH += $$PWD/../sen4x-http-server-common

PRE_TARGETDEPS += $$OUT_PWD/../sen4x-http-server-common/libsen4x-http-server-common.a
