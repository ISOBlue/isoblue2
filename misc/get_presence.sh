#!/bin/sh

cnt1=`ps aux | grep --regexp="[r]est_service.*" | wc -l`
cnt2=`ps aux | grep --regexp="[r]est_gps_log.*" | wc -l`

if [ $cnt1 -eq 1 ] && [ $cnt2 -eq 1 ]; then
	echo 0 > /sys/class/leds/LED_4_RED/brightness
	echo 255 > /sys/class/leds/LED_4_GREEN/brightness
else
	echo 0 > /sys/class/leds/LED_4_GREEN/brightness
	echo 255 > /sys/class/leds/LED_4_RED/brightness
fi
