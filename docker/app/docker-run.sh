#!/bin/sh
docker build \
    -t sen4x-app-build \
    .

docker run -i --rm \
       -v $PWD/../..:/sen4x:z \
       -v $PWD/entry.sh:/entry.sh:z \
       -u $(id -u):$(id -g) \
       sen4x-app-build /entry.sh
