#!/bin/bash
NAME="$1"
shift
./transform.py $* $NAME.pck $NAME.json
ulimit -s unlimited
node --stack-size=1000000 ./prettyprint.js $NAME.json $NAME-out.js
