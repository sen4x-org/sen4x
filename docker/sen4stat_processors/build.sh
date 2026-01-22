#!/bin/bash
tar -czh . | docker build --progress=plain -t sen4stat/processors:1.0.0 -
