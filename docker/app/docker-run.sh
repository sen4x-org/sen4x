#!/bin/sh
docker build \
    -t sen4x-app-build \
    .

docker run -it --rm \
       -v $PWD/../..:/sen4x:z \
       -v $PWD/entry.sh:/entry.sh:z \
       sen4x-app-build /entry.sh

sudo chown $USER:$USER ../../packaging/Sen2AgriRPM/sen2agri-app-*.rpm
