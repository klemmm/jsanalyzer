#!/bin/bash

cd benchs
KO="0"
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
		KO="$(($KO + 1))"
	fi
done
rm tmp
echo "Number of tests failed: $KO"

