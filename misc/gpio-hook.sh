#!/bin/sh

if [ "${1}" == "pre" ]; then
	# Do the thing you want before suspend here, e.g.:
	# kill -9 `ps ax | awk '[f]fmpeg { print $1 }'`
	echo 0 > /sys/class/gpio/gpio37/value
elif [ "${1}" == "post" ]; then
	# Do the thing you want after resume here, e.g.:
	echo 1 > /sys/class/gpio/gpio37/value
fi
