#!/bin/bash
NAME="$1"
shift
./analyze.py $NAME.js $NAME.pck
./transform.py $* $NAME.pck $NAME.json
./prettyprint.js $NAME.json $NAME-out.js

