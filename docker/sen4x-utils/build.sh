#!/bin/bash
tar -czh . | docker build --progress=plain -t sen4x/sen4cap-processors-utils:1.0.0 -
