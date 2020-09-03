#!/bin/bash
while true; do
	python3 ./canadian_reads.py
	echo "Python3 script error, sleeping 60 seconds and call it again"
	sleep 60s
done
