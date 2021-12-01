#!/bin/bash

cd benchs
ls -1 *.js |while read A ; do
	echo -n "Testing $A ... "
	../analyze.py "$A" > tmp
	if [ "$?" != "0" ]; then
		exit 1
	fi
	diff -q tmp ../results/$(basename "$A" .js).out >/dev/null 2>&1
	if [ "$?" == "0" ]; then
		echo "OK"
	else
		echo "KO"
	fi
done
rm tmp

