#!/bin/bash
tar -czh . | docker build -t sen4x/data-preparation:0.4 -
# docker build -f Dockerfile.isect -t sen4cap/data-preparation:0.4-isect .
