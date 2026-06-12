#!/bin/bash
tar -czh . | docker build -t sen4x/sen4cap-grassland-mowing:5.0.0 -
