#!/bin/sh

if [ "${1}" == "pre" ]; then
	# Do the thing you want before suspend here, e.g.:
	# kill -9 `ps ax | awk '[f]fmpeg { print $1 }'`
	systemctl stop rtsp-start@128.46.213.4
	systemctl stop rtsp-start@128.46.213.6
elif [ "${1}" == "post" ]; then
	# Do the thing you want after resume here, e.g.:
	systemctl restart rtsp-start@128.46.213.4
	systemctl restart rtsp-start@128.46.213.6
fi
