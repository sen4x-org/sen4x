TEMPLATE = subdirs

SUBDIRS += sen4x-common \
    sen4x-persistence \
    sen4x-archiver \
    sen4x-http-server-common \
    sen4x-executor \
    sen4x-orchestrator \
    sen4x-http-listener \
    sen4x-monitor-agent \
    sen4x-processor-wrapper \
    sen4x-scheduler \
    QtWebApp \
    tests

sen4x-persistence.depends = sen4x-common
sen4x-archiver.depends = sen4x-common sen4x-persistence
sen4x-executor.depends = sen4x-common sen4x-persistence sen4x-http-server-common
sen4x-orchestrator.depends = sen4x-common sen4x-persistence sen4x-http-server-common
sen4x-http-listener.depends = sen4x-common sen4x-persistence QtWebApp
sen4x-http-server-common.depends = sen4x-common sen4x-persistence QtWebApp
sen4x-monitor-agent.depends = sen4x-common
sen4x-scheduler.depends = sen4x-common sen4x-persistence
sen4x-processor-wrapper.depends = sen4x-common
tests.depends = sen4x-common sen4x-scheduler sen4x-persistence
