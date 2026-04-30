#!/bin/bash
tar -czh . | docker build -t sen4x/data-preparation-new:0.1 -
