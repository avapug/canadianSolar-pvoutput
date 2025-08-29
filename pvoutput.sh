#!/bin/bash
while true; do
	/root/zappi-env/bin/python3 -u /root/pvoutput/pvoutput.py
	echo "Python script error, sleeping 60 seconds and call it again"
	sleep 60s
done
