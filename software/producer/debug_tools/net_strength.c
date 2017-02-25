/*
 * Modem Signal Strength Message Kafka Producer 
 *
 * Author: Yang Wang <wang701@purdue.edu>
 *
 * Copyright (C) 2017 Purdue University
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to
 * deal in the Software without restriction, including without limitation the
 * rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
 * sell copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
 * IN THE SOFTWARE.
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <signal.h>
#include <stdbool.h>
#include <errno.h>

#include <sys/time.h>

#include <avro.h>
#include <librdkafka/rdkafka.h>

static char key[100];
static char *brokers = "localhost:9092";
static char *command = "qmicli -p -d /dev/cdc-wdm0 --nas-get-signal-strength | \
												head -n 3 | tail -n 1 | sed \"s/^.*'\\([-0-9]*\\) dBm'[^']*$/\\1/\"";

const char D_NS_SCHEMA[] =
"{\"type\":\"record\",\
  \"name\":\"dns\",\
  \"fields\":[\
	{\"name\": \"timestamp\", \"type\": \"double\"},\
	{\"name\": \"strength\", \"type\": \"int\"}]}";

/* Timer handler */
void timer_handler(int signum) {
	/* Kafka static variables */
	static rd_kafka_t *rk = NULL;
	static rd_kafka_topic_t *rkt = NULL;
	static rd_kafka_conf_t *conf = NULL;
	static rd_kafka_topic_conf_t *topic_conf = NULL;
	static char errstr[512];

	/* Avro static variables */
	static avro_writer_t writer = NULL;
	static avro_schema_t d_ns_schema = NULL;
	static avro_datum_t d_ns = NULL;
	static char buf[20];

	/* timeval struct */
	struct timeval tp;
	double timestamp;

	/* Network strength file variables */
	static int ns;
	static FILE *fn;

	/* Broker conf */
	if (conf == NULL) {
		conf = rd_kafka_conf_new();
		/* Kafka conf */
		rd_kafka_conf_set(conf, "batch.num.messages", "20000", errstr,
				sizeof(errstr));
		rd_kafka_conf_set(conf, "queue.buffering.max.messages", "1000000", errstr,
				sizeof(errstr));
		rd_kafka_conf_set(conf, "queue.buffering.max.ms", "1", errstr,
				sizeof(errstr));
		rd_kafka_conf_set(conf, "log.connection.close", "false", errstr,
				sizeof(errstr));
	}

	/* Kafka topic conf */
	if (topic_conf == NULL) {
		topic_conf = rd_kafka_topic_conf_new();
		rd_kafka_topic_conf_set(topic_conf, "request.required.acks", "0", errstr,
				sizeof(errstr));
	}

	/* Create Kafka producer */
	if (rk == NULL) {
		if (!(rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf, errstr, sizeof(errstr)))) {
			fprintf(stderr, "%% Failed to create new producer: %s\n", errstr);
		}
	}
	
	if (rd_kafka_brokers_add(rk, brokers) == 0) {
		fprintf(stderr, "%% No valid brokers specified\n");
		exit(EXIT_FAILURE);
	}

	if (rkt == NULL) {
		/* Create new Kafka topic */
		rkt = rd_kafka_topic_new(rk, "debug", topic_conf);
	}

	/* Initialize the schema structure from JSON */
	if (d_ns_schema == NULL) {
		if (avro_schema_from_json_literal(D_NS_SCHEMA, &d_ns_schema)) {
			fprintf(stderr, "Unable to parse d_ns schema\n");
			exit(EXIT_FAILURE);
		}
	}

	/* Create avro writer */
	if (writer == NULL) {
		writer = avro_writer_memory(buf, sizeof(buf));
	}

	/* Create avro record based on the schema */
	if (d_ns == NULL) { 
		d_ns = avro_record(d_ns_schema);
	}

	/* Get UNIX timestamp */
	gettimeofday(&tp, NULL);
	timestamp = tp.tv_sec + tp.tv_usec / 1000000.0;

	/* Get the network strength from command */
	fn = popen(command, "r");
	if (fn != NULL) {
		fscanf(fn, "%d", &ns);
	} else {
		perror("fn");
		exit(EXIT_FAILURE);
	}

#if DEBUG
	printf("%f: network strength is %d\n", timestamp, ns);
	fflush(stdout);
#endif

	if (ns < -100) {
		printf("%f: Network strength %d dBm doesn't make sense! Something WRONG!\n",
				timestamp, ns);
	}

	avro_datum_t ts_datum = avro_double(timestamp);
	avro_datum_t ns_datum = avro_int32(ns);

	if (avro_record_set(d_ns, "timestamp", ts_datum)
		|| avro_record_set(d_ns, "strength", ns_datum)) {
		fprintf(stderr, "Unable to set record to d_msg_rate\n");
		exit(EXIT_FAILURE);
	}

	if (avro_write_data(writer, d_ns_schema, d_ns)) {
		fprintf(stderr, "unable to write d_ns datum to memory\n");
		exit(EXIT_FAILURE);
	}

	if (rd_kafka_produce(rkt, RD_KAFKA_PARTITION_UA, RD_KAFKA_MSG_F_COPY,
			buf, avro_writer_tell(writer), key, strlen(key), NULL) == -1) {
		fprintf(stderr, "%% Failed to produce to topic %s "
						"partition %i: %s\n",
						rd_kafka_topic_name(rkt), RD_KAFKA_PARTITION_UA,
						rd_kafka_err2str(rd_kafka_last_error()));
		rd_kafka_poll(rk, 0);
	}

	rd_kafka_poll(rk, 0);

	/* Decrement all our references to prevent memory from leaking */
	avro_datum_decref(ts_datum);
	avro_datum_decref(ns_datum);

	/* Reset the writer */
	avro_writer_reset(writer);
}

int main(int argc, char *argv[]) {
	if (argv[1] == NULL) {
		fprintf(stderr, "You need to supply ISOBlue ID file\n");
		return EXIT_FAILURE;
	}

	/* fp for opening uuid file */
	FILE *fp;
	char *id = 0;
	long length;

	/* Timer stuff variables */
	struct sigaction sa;
	struct itimerval timer;

	/* Get the id */
	fp = fopen(argv[1], "r");
	if (fp) {
		fseek(fp, 0, SEEK_END);
		length = ftell(fp);
		fseek(fp, 0, SEEK_SET);
		id = malloc(length);
		if (id) {
			fread(id, 1, length, fp);
			if (id[length - 1] == '\n') {
				id[--length] = '\0';
			}
		}
		fclose(fp);
	} else {
		perror("ISOBlue ID file");
		return EXIT_FAILURE;
	}

	/* Create the key */
	strcpy(key, "ns");
	strcat(key, ":");
	strcat(key, id);

	/* Install timer_handler as the signal handler for SIGALRM. */
	memset (&sa, 0, sizeof(sa));
	sa.sa_handler = &timer_handler;
	sigaction(SIGALRM, &sa, NULL);

	/* Configure the timer to expire after 1 min... */
	timer.it_value.tv_sec = 60;
	timer.it_value.tv_usec = 0;
	/* ... and every 1 min after that. */
	timer.it_interval.tv_sec = 60;
	timer.it_interval.tv_usec = 0;

	/* Start a real timer. It counts down whenever this process is
	 * executing. */
	setitimer(ITIMER_REAL, &timer, NULL);

	while (1) {
		sleep(1);
	}

	return EXIT_SUCCESS;
}