#!/bin/sh
rm -f sen4x-archiver/pch.hpp
grep -Rh "^#include <" sen4x-archiver | LC_ALL=C sort -u > sen4x-archiver/pch.hpp

rm -f sen4x-common/pch.hpp
grep -Rh "^#include <" sen4x-common | LC_ALL=C sort -u > sen4x-common/pch.hpp

rm -f sen4x-executor/pch.hpp
grep -Rh "^#include <" sen4x-executor | LC_ALL=C sort -u > sen4x-executor/pch.hpp

rm -f sen4x-http-listener/pch.hpp
grep -Rh "^#include <" sen4x-http-listener | LC_ALL=C sort -u > sen4x-http-listener/pch.hpp

rm -f sen4x-orchestrator/pch.hpp
grep -Rh "^#include <" sen4x-orchestrator | LC_ALL=C sort -u > sen4x-orchestrator/pch.hpp

rm -f sen4x-persistence/pch.hpp
grep -Rh "^#include <" sen4x-persistence | LC_ALL=C sort -u > sen4x-persistence/pch.hpp

rm -f sen4x-processor-wrapper/pch.hpp
grep -Rh "^#include <" sen4x-processor-wrapper | LC_ALL=C sort -u > sen4x-processor-wrapper/pch.hpp

rm -f tests/pch.hpp
grep -Rh "^#include <" tests | LC_ALL=C sort -u > tests/pch.hpp
