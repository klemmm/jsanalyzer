#!/bin/bash
ROOT_DIR="$(cd "$(dirname "$0")" && pwd -P)"

NAME="$1"
shift
$ROOT_DIR/analyze.py $NAME.js $NAME.pck
$ROOT_DIR/transform.py $* $NAME.pck $NAME.json
node --stack-size=1000000 $ROOT_DIR/prettyprint.js $NAME.json $NAME-out.js

