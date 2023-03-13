#!/bin/bash
NAME="$1"
shift
./analyze.py $NAME.js $NAME.pck
./transform.py $* $NAME.pck $NAME.json
node --stack-size=1000000 ./prettyprint.js $NAME.json $NAME-out.js

