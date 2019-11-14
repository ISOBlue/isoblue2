#!/usr/bin/env python

from __future__ import print_function
import sqlite3
import time
import ConfigParser as configparser
import sys
import json
import subprocess
import socket
import os

cfgpath = '/opt/isoblue.cfg'
debuglevel = 0
errorcount = 0

# Custom debug level. Set a debug level when calling which will be compared to the system
#   debug level when determining to print or not
def printdebug(lvl=2, *args, **kwargs):
    if lvl <= debuglevel:
        print('DEBUG ' + str(lvl) + ': ', *args, file=sys.stderr, **kwargs)

# Read in the config data. Called every so often to check for updates to the config file by
#   outside services
def readconfig(config, configdict):
    filesread = config.read(cfgpath)
    # Verify config read correctyly
    if filesread[0] != cfgpath:
        print('Could not read config file')
        return -1
    
    # Read in relevant config options
    configdict['isoblue_id'] = config.get('ISOBlue', 'id')
    configdict['dbpath'] = config.get('ISOBlue', 'dbpath')
    configdict['debuglevel'] = config.getint('ISOBlue', 'debuglevel')
    configdict['server'] = config.get('REST', 'server')
    configdict['uri'] = config.get('REST', 'baseuri')
    configdict['verifyssl'] = config.getboolean('REST', 'verifyssl')
    configdict['senddelay'] = config.getint('REST', 'senddelay')
    configdict['batchsize'] = config.getint('REST', 'batchsize')

    return 0

# Check for internet. Pings cloudflare's DNS server
def internet(host="1.1.1.1", port=80, timeout=3):
    """
    Host: 1.1.1.1 (one.one.one.one: Cloudflare DNS server)
    OpenPort: 80/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        printdebug(2, ex)
        return False

# Boot the OADA cache
def bootcache(configdict, wait, readfd, writefd):
    if configdict['verifyssl']:
        cache = subprocess.Popen(['/opt/bin/oada-cache-wrapper/oada-cache-wrapper.js', '-r', str(readfd), '-w', str(writefd)])
    else:
        cache = subprocess.Popen(['/opt/bin/oada-cache-wrapper/oada-cache-wrapper.js', '-r', str(readfd), '-w', str(writefd)], env={'NODE_TLS_REJECT_UNAUTHORIZED': '0'})

    # Give OADA cache time to boot
    time.sleep(5)
    
    return cache


if __name__ == "__main__":

    # Setup config parser
    config = configparser.RawConfigParser()
    
    # Read config file into a dict to avoid global vars
    configdict = {}
    if readconfig(config, configdict) == -1:
        exit(-1)
    
    debuglevel = configdict['debuglevel']    
    printdebug(2, 'Config: ' + str(configdict))

    # Connect to database
    db = sqlite3.connect(configdict['dbpath'])

    # If the default table does not exist, create it
    db.cursor().execute('CREATE TABLE IF NOT EXISTS sendqueue(id INTEGER PRIMARY KEY, time INTEGER, topic TEXT, data TEXT, sent INTEGER)')
    db.cursor().execute('CREATE INDEX IF NOT EXISTS sentidx ON sendqueue(sent) WHERE sent IS NOT 1')
    db.cursor().execute('PRAGMA journal_mode=WAL')

    # Commit changes
    db.commit()

    # Launch OADA Cache and prep
    cacheread, restwrite = os.pipe()
    restread, cachewrite = os.pipe()
    cache = bootcache(configdict, 5, cacheread, cachewrite)

    # Create open file objects for fds for communication with oada-cache
    printdebug(2, 'cache read fd: ', cacheread, ' Write fd: ', cachewrite)
    printdebug(2, 'rest read fd: ', restread, ' Writefd: ', restwrite)
    #restreadobj = os.fdopen(restread, 'r')
    restwriteobj = os.fdopen(restwrite, 'w')

    # Except Ctrl-C for graceful shutdown
    try:
        while 1:
            # Update config from config file
            printdebug(2, 'Updating config file')
            if readconfig(config, configdict) == -1:
                printdebug(1, 'Could not read config file for updates')

            # Batched uploads will be sorted into buckets using upload uri as the key
            uploaddata = {}
            # list of db indicies we are sending. Used later to update the db of successful sends
            uploadindicies = {}

            # Grab N rows, N being maximum batch size
            printdebug(2, 'Querying unsent messages, limiting to ', configdict['batchsize'])
            unsent = db.cursor().execute('SELECT * FROM sendqueue WHERE sent IS NOT 1 ORDER BY time DESC LIMIT ?', (str(configdict['batchsize']),))
            printdebug(2, 'Batching requests')
            for row in unsent:
                dbindex = str(row[0])
                uri = str(row[2])
                data = str(row[3])

                # If we have already seen the uri added it to that bucket
                if uploaddata.has_key(uri):
                    uploaddata[uri] = uploaddata[uri] + ',' + data
                    uploadindicies[uri].append(dbindex)

                # If we have not seen this uri, create another bucket
                else:
                    uploaddata[uri] = data
                    uploadindicies[uri] = [dbindex]
                
             
            if len(uploaddata) == 0:
                printdebug(1, 'Nothing to send. Sleeping for 1s and then rechecking')
                time.sleep(1)
                continue
   
            # Check for internet. If not exists, wait 5 seconds and try again
            # If there is still no connection, refresh batch to send and try again
            printdebug(2, 'Checking internet connection')
            if not internet():
                printdebug(2, 'Internet connection not detected. Sleeping 5s and trying again')
                time.sleep(5)
                if not internet():
                    printdebug(1, 'Internet connection not detected. Sleeping 5s and then rebuilding batch to try again')
                    time.sleep(5)
                    continue

            # Upload buckets. Still very much in development
            for uri in uploaddata:
                # Create JSON string of data we want to send
                datastr = '{"sec-index":{' + uploaddata[uri] + '}}'
                printdebug(1, 'Attempting to send ', len(uploadindicies[uri]), ' data point(s) with a single request:')
                printdebug(3, 'Data to send: `', datastr, '`')

                # Create json object from json string. This can be very long so only print it out if the debug level is very verbose
                datajson = json.loads(datastr)
                printdebug(3, 'jsonified data to send: ', datajson)
              
                printdebug(3, datastr)

                # Package data for passing to oada cache
                tocache = '{"path":"' + uri + '","data":' + datastr + '}'
                printdebug(3, tocache)

                # Check if cache is still running, restart if not
                if cache.poll() is not None:
                    # Ensure that cache is actually dead
                    cache.kill()
                    time.sleep(1)
                    cache = bootcache(configdict, 10, cacheread, cachewrite)

                # Send of OADA cache for processing
                #restwriteobj.write(tocache + '\n')
                os.write(restwrite, tocache + '\n')
                
                printdebug(2, 'Write complete, awaiting cache response')

                # Read Resonse from OADA cache
                #result = restreadobj.readline()
                result = os.read(restread, 8)
                
                # If send was successful, mark all indicies as sent and move on
                if 'Success' == ' '.join(result.split()):
                    printdebug(1, 'Send successful with response: `', repr(result),'`')
                    printdebug(1, 'Updating ', len(uploadindicies[uri]), ' indicies as successfully sent')
                    # Mark all sent indicies as sent
                    for index in uploadindicies[uri]:
                        db.cursor().execute('UPDATE sendqueue SET sent = 1 where id = ?', (index,) )
                    db.commit()
                    errorcount = 0
                    printdebug(2, 'Update finished')
                else:
                    # If failed, skip and try again alter. If error count starts to grow, restart cache
                    printdebug(1, 'Send failed. Cache response: `', result+ '`')
                    errorcount = errorcount + 1

                    if errorcount >= 10:
                        printdebug(0, 'OADA Cache is not behaving. Restarting Cache')
                        cache.kill()
                        time.sleep(1)
                        cache = bootcache(configdict, 10, cacheread, cachewrite)

                        # Read through junk that may be in the buffer
                        #cache.stdout.seek(0,2)
                    
                    # If it is still not working, something is seriously wrong. Exit and let systemd try to restart everything
                    if errorcount >= 15:
                        printdebug(0, 'OADA Cache is still not behaving. Exiting so systemd can restart service')
                        exit(1)

            if configdict['senddelay'] > 0:
                # If we are trying to slow down the sends, sleep for the specified amount of time
                printdebug(2, "Sleeping for ", configdict['senddelay'], "s before the next send per config file")
                time.sleep(configdict['senddelay'])
 

    except KeyboardInterrupt:
        # Close connection to db
        db.close()
