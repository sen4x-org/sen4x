#!/bin/bash
set -e

cd sen4x/packaging
rm -f Sen2AgriRPM/sen2agri-app-*.rpm

mkdir -p Sen2AgriRPM

./Sen2AgriAppBuild.sh

mv Sen2AgriApp/rpm_binaries/*.rpm \
   Sen2AgriRPM
