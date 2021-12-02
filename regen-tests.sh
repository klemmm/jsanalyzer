#!/bin/bash

cd benchs
KO="0"
ls -1 *.js |while read A ; do
	echo -n "Testing $A ... "
	../analyze.py "$A" > ../results/$(basename "$A" .js).out
	if [ "$?" != "0" ]; then
		exit 1
	fi
done

