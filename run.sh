#!/bin/bash

export JAVA_HOME=/Users/mihailkarpenko/Library/Java/JavaVirtualMachines/temurin-11.0.30/Contents/Home
export MAJOR_HOME=/Users/mihailkarpenko/major
export PATH=$JAVA_HOME/bin:$MAJOR_HOME/bin:$PATH

source venv/bin/activate
python3 run_benchmark.py "$@"