#!/bin/sh

if [ "${1}" == "pre" ]; then
	# Do the thing you want before suspend here, e.g.:
	systemctl stop mirror
	systemctl stop zookeeper
	systemctl stop gps-log@remote
	systemctl stop gps-log@gps
	sync
elif [ "${1}" == "post" ]; then
	# Do the thing you want after resume here, e.g.:
	systemctl restart zookeeper
	systemctl restart mirror
  systemctl restart gps-log@remote
  systemctl restart gps-log@gps
	systemctl restart gps-log-watchdog
fi
