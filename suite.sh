#!/bin/bash
NAME="$1"
shift
./transform.py $* $NAME.pck $NAME.json
./prettyprint.js $NAME.json $NAME-out.js

