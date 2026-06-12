#!/bin/bash
tar -czh . | docker build --progress=plain -t sen4x/sen4cap-s1-preprocessor:1.0.0 -
