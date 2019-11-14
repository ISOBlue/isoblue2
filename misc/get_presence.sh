#!/bin/sh

# systemctl services to check
services=( oada_upload heartbeat gps_log )
failed=0

for service in ${services[@]}
do
	echo "Checking $service"
	systemctl is-active $service --quiet
	exitcode=$?
	if [ $exitcode != 0 ]
	then
		echo "WARNING: $service is not active"
		failed=1
	fi
done	


if [ $failed == 0 ]; then
	echo "All services ok"
	echo 0 > /sys/class/leds/LED_4_RED/brightness
	echo 255 > /sys/class/leds/LED_4_GREEN/brightness
else
	echo "1 or more services were not active"
	echo 0 > /sys/class/leds/LED_4_GREEN/brightness
	echo 255 > /sys/class/leds/LED_4_RED/brightness
fi
