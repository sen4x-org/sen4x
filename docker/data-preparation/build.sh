#!/bin/bash
tar -czh . | docker build -t sen4x/data-preparation:0.5 -
