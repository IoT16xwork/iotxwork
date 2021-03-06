#!/usr/bin/env python

# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.

import random
import time
import sys
from iothub_client import IoTHubClient, IoTHubClientError, IoTHubTransportProvider, IoTHubClientResult
from iothub_client import IoTHubMessage, IoTHubMessageDispositionResult, IoTHubError, DeviceMethodReturnValue
import config as config
#from BME280SensorSimulator import BME280SensorSimulator
import RPi.GPIO as GPIO
import Adafruit_MCP3008
import Adafruit_GPIO.SPI as SPI
import Adafruit_DHT

import re
from CCS811_RPi import CCS811_RPi

# HTTP options
# Because it can poll "after 9 seconds" polls will happen effectively
# at ~10 seconds.
# Note that for scalabilty, the default value of minimumPollingTime
# is 25 minutes. For more information, see:
# https://azure.microsoft.com/documentation/articles/iot-hub-devguide/#messaging
# only used for HTTP
TIMEOUT = 241000
MINIMUM_POLLING_TIME = 9

# messageTimeout - the maximum time in milliseconds until a message times out.
# The timeout period starts at IoTHubClient.send_event_async.
# By default, messages do not expire.
MESSAGE_TIMEOUT = 10000

RECEIVE_CONTEXT = 0
MESSAGE_COUNT = 0
MESSAGE_SWITCH = True
TWIN_CONTEXT = 0
SEND_REPORTED_STATE_CONTEXT = 0
METHOD_CONTEXT = 0
TEMPERATURE_ALERT = 30.0

# global counters
RECEIVE_CALLBACKS = 0
SEND_CALLBACKS = 0
BLOB_CALLBACKS = 0
TWIN_CALLBACKS = 0
SEND_REPORTED_STATE_CALLBACKS = 0
METHOD_CALLBACKS = 0
EVENT_SUCCESS = "success"
EVENT_FAILED = "failed"

# chose HTTP, AMQP or MQTT as transport protocol
PROTOCOL = IoTHubTransportProvider.MQTT

# Hardware SPI configuration:
SPI_PORT   = 0
SPI_DEVICE = 0
mcp = Adafruit_MCP3008.MCP3008(spi=SPI.SpiDev(SPI_PORT, SPI_DEVICE))

ccs811 = CCS811_RPi()



# String containing Hostname, Device Id & Device Key in the format:
# "HostName=<host_name>;DeviceId=<device_id>;SharedAccessKey=<device_key>"
#telemetry = Telemetry()

#if len(sys.argv) < 2:
#   print ( "You need to provide the device connection string as command line arguments." )
#    telemetry.send_telemetry_data(None, EVENT_FAILED, "Device connection string is not provided")
#    sys.exit(0)

def is_correct_connection_string():
    m = re.search("HostName=.*;DeviceId=.*;", CONNECTION_STRING)
    if m:
        return True
    else:
        return False

#CONNECTION_STRING = sys.argv[1]
CONNECTION_STRING = ""

if not is_correct_connection_string():
    print ( "Device connection string is not correct." )
 #   telemetry.send_telemetry_data(None, EVENT_FAILED, "Device connection string is not correct.")
    sys.exit(0)

MSG_TXT = "{\"deviceId\": \"Raspberry Pi - Python\",\"temperature\": %f,\"humidity\": %f,\"sound\": %f,\"soundAmplitude\": %f,\"motion\": %f,\"CO2\": %f}"

GPIO.setmode(GPIO.BCM)
GPIO.setup(config.GPIO_PIN_ADDRESS, GPIO.OUT)

def receive_message_callback(message, counter):
    global RECEIVE_CALLBACKS
    message_buffer = message.get_bytearray()
    size = len(message_buffer)
    print ( "Received Message [%d]:" % counter )
    print ( "    Data: <<<%s>>> & Size=%d" % (message_buffer[:size].decode("utf-8"), size) )
    map_properties = message.properties()
    key_value_pair = map_properties.get_internals()
    print ( "    Properties: %s" % key_value_pair )
    counter += 1
    RECEIVE_CALLBACKS += 1
    print ( "    Total calls received: %d" % RECEIVE_CALLBACKS )
    return IoTHubMessageDispositionResult.ACCEPTED


def send_confirmation_callback(message, result, user_context):
    global SEND_CALLBACKS
    print ( "Confirmation[%d] received for message with result = %s" % (user_context, result) )
    map_properties = message.properties()
    print ( "    message_id: %s" % message.message_id )
    print ( "    correlation_id: %s" % message.correlation_id )
    key_value_pair = map_properties.get_internals()
    print ( "    Properties: %s" % key_value_pair )
    SEND_CALLBACKS += 1
    print ( "    Total calls confirmed: %d" % SEND_CALLBACKS )
    #led_blink()


def device_twin_callback(update_state, payload, user_context):
    global TWIN_CALLBACKS
    print ( "\nTwin callback called with:\nupdateStatus = %s\npayload = %s\ncontext = %s" % (update_state, payload, user_context) )
    TWIN_CALLBACKS += 1
    print ( "Total calls confirmed: %d\n" % TWIN_CALLBACKS )


def send_reported_state_callback(status_code, user_context):
    global SEND_REPORTED_STATE_CALLBACKS
    print ( "Confirmation for reported state received with:\nstatus_code = [%d]\ncontext = %s" % (status_code, user_context) )
    SEND_REPORTED_STATE_CALLBACKS += 1
    print ( "    Total calls confirmed: %d" % SEND_REPORTED_STATE_CALLBACKS )


def device_method_callback(method_name, payload, user_context):
    global METHOD_CALLBACKS,MESSAGE_SWITCH
    print ( "\nMethod callback called with:\nmethodName = %s\npayload = %s\ncontext = %s" % (method_name, payload, user_context) )
    METHOD_CALLBACKS += 1
    print ( "Total calls confirmed: %d\n" % METHOD_CALLBACKS )
    device_method_return_value = DeviceMethodReturnValue()
    device_method_return_value.response = "{ \"Response\": \"This is the response from the device\" }"
    device_method_return_value.status = 200
    if method_name == "start":
        MESSAGE_SWITCH = True
        print ( "Start sending message\n" )
        device_method_return_value.response = "{ \"Response\": \"Successfully started\" }"
        return device_method_return_value
    if method_name == "stop":
        MESSAGE_SWITCH = False
        print ( "Stop sending message\n" )
        device_method_return_value.response = "{ \"Response\": \"Successfully stopped\" }"
        return device_method_return_value
    return device_method_return_value


def blob_upload_conf_callback(result, user_context):
    global BLOB_CALLBACKS
    print ( "Blob upload confirmation[%d] received for message with result = %s" % (user_context, result) )
    BLOB_CALLBACKS += 1
    print ( "    Total calls confirmed: %d" % BLOB_CALLBACKS )


def iothub_client_init():
    # prepare iothub client
    client = IoTHubClient(CONNECTION_STRING, PROTOCOL)
    client.set_option("product_info", "HappyPath_RaspberryPi-Python")
    if client.protocol == IoTHubTransportProvider.HTTP:
        client.set_option("timeout", TIMEOUT)
        client.set_option("MinimumPollingTime", MINIMUM_POLLING_TIME)
    # set the time until a message times out
    client.set_option("messageTimeout", MESSAGE_TIMEOUT)
    # to enable MQTT logging set to 1
    if client.protocol == IoTHubTransportProvider.MQTT:
        client.set_option("logtrace", 0)
    client.set_message_callback(
        receive_message_callback, RECEIVE_CONTEXT)
    if client.protocol == IoTHubTransportProvider.MQTT or client.protocol == IoTHubTransportProvider.MQTT_WS:
        client.set_device_twin_callback(device_twin_callback, TWIN_CONTEXT)
        client.set_device_method_callback(device_method_callback, METHOD_CONTEXT)
    return client


def print_last_message_time(client):
    try:
        last_message = client.get_last_message_receive_time()
        print ( "Last Message: %s" % time.asctime(time.localtime(last_message)) )
        print ( "Actual time : %s" % time.asctime() )
    except IoTHubClientError as iothub_client_error:
        if iothub_client_error.args[0].result == IoTHubClientResult.INDEFINITE_TIME:
            print ( "No message received" )
        else:
            print ( iothub_client_error )

def DHT_sensor():

    humidity, temperature = Adafruit_DHT.read_retry(11, 4)

    return humidity, temperature

def hub_message():
    soundsensorPin = soundsensor_digital()

    soundsensorAmplitude = soundsensor_analog()

    motionSensor = PIR_message()

    coSensor = CCS811_message()
    
    #humidity, temperature = Adafruit_DHT.read_retry(11, 4)

    humSensor, tempSensor = DHT_sensor()
    
    msg_txt_formatted = MSG_TXT % (tempSensor,humSensor,soundsensorPin, soundsensorAmplitude, motionSensor, coSensor)
    print (msg_txt_formatted)
    message = IoTHubMessage(msg_txt_formatted)
    # optional: assign properties
    message.message_id = "message_%d" % MESSAGE_COUNT
    message.correlation_id = "correlation_%d" % MESSAGE_COUNT
    prop_map = message.properties()
    #prop_map.add("temperatureAlert", "true" if temperature > TEMPERATURE_ALERT else "false")
    return message


def soundsensor_digital():
    soundPin = 7
    
    GPIO.setup(soundPin, GPIO.IN)
                
    if GPIO.input(soundPin) == GPIO.LOW:
        soundsensor=0
    else:
        soundsensor=1
    
    return soundsensor
    
def soundsensor_analog():
 
    soundsensorAmplitude = mcp.read_adc(0)
    if soundsensorAmplitude > 30:
        print('High volume alert')
    
    return soundsensorAmplitude

def MOTION(motionpin):
    print ('Motion Detected!')
    global flag
    flag=1

def PIR_setup():
    PIR_PIN = 6 #GPIO6=pin31
    GPIO.setup(PIR_PIN, GPIO.IN)
    global motion
    global flag
    motion=0
    flag=0
    print ('PIR setup ready')

    try:
               GPIO.add_event_detect(PIR_PIN, GPIO.RISING, callback=MOTION)
    except KeyboardInterrupt:
               print ('Quit')
               GPIO.cleanup()

def PIR_message():
    global flag
    global motion
    if flag==1:
        flag=0
        motion=1
    else:
        motion=0
    
    return motion
    
def CCS811_init():
    global statusbyte
#    ccs811 = CCS811_RPi()

    # Do you want to send data to thingSpeak? If yes set WRITE API KEY, otherwise set False
    THINGSPEAK      = False # or type 'YOURAPIKEY'

    # Do you want to preset sensor baseline? If yes set the value here, otherwise set False
    INITIALBASELINE = False

    '''
    MEAS MODE REGISTER AND DRIVE MODE CONFIGURATION
    0b0       Idle (Measurements are disabled in this mode)
    0b10000   Constant power mode, IAQ measurement every second
    0b100000  Pulse heating mode IAQ measurement every 10 seconds
    0b110000  Low power pulse heating mode IAQ measurement every 60
    0b1000000 Constant power mode, sensor measurement every 250ms
    '''
    # Set MEAS_MODE (measurement interval)
    configuration = 0b100000

    # Set read interval for retriveving last measurement data from the sensor
    pause = 60

    print ('Checking hardware ID...')
    hwid = ccs811.checkHWID()
    if hwid == hex(129):
            print ('Hardware ID is correct')
    else:
           print ('Incorrect hardware ID ',hwid, ', should be 0x81')

    #print 'MEAS_MODE:',ccs811.readMeasMode()
    ccs811.configureSensor(configuration)
    print ('MEAS_MODE:',ccs811.readMeasMode())
    print ('STATUS: ',bin(ccs811.readStatus()))
    print ('---------------------------------')
      
    humidity = 50.00
    temperature = 25.00
        
    statusbyte = ccs811.readStatus()
    print ('STATUS: ', bin(statusbyte))

    error = ccs811.checkError(statusbyte)
    if(error):
        print ('ERROR:',ccs811.checkError(statusbyte))


def CCS811_message():   
        global statusbyte     
        if(not ccs811.checkDataReady(statusbyte)):
            print ('No new samples are ready')
           
            
        result = ccs811.readAlg()
        if(not result):
            print ('Invalid result received')
            return 0
        
        baseline = ccs811.readBaseline()
        #print ('eCO2: ',result['eCO2'],' ppm')
        #print ('TVOC: ',result['TVOC'], 'ppb')
        #print ('Status register: ',bin(result['status'])
        #print ('Last error ID: ',result['errorid'])

        #print ('RAW data: ',result['raw'])
        #print ('Baseline: ',baseline)
        
        return result


def iothub_client_upload_sensors():
    try:
        client = iothub_client_init()

        if client.protocol == IoTHubTransportProvider.MQTT:
            print ( "IoTHubClient is reporting state" )
            reported_state = "{\"newState\":\"standBy\"}"
            client.send_reported_state(reported_state, len(reported_state), send_reported_state_callback, SEND_REPORTED_STATE_CONTEXT)

        
 #       telemetry.send_telemetry_data(parse_iot_hub_name(), EVENT_SUCCESS, "IoT hub connection is established")
        while True:
            global MESSAGE_COUNT,MESSAGE_SWITCH
            if MESSAGE_SWITCH:
                # send a few messages every minute
                print ( "IoTHubClient sending %d messages" % MESSAGE_COUNT )
                message_hub=hub_message()
                client.send_event_async(message_hub, send_confirmation_callback, MESSAGE_COUNT)
                print ( "IoTHubClient.send_event_async accepted message [%d] for transmission to IoT Hub." % MESSAGE_COUNT )
                status = client.get_send_status()
                print ( "Send status: %s" % status )
                MESSAGE_COUNT += 1

            time.sleep(config.MESSAGE_TIMESPAN / 1000.0)

    except IoTHubError as iothub_error:
        print ( "Unexpected error %s from IoTHub" % iothub_error )
#        telemetry.send_telemetry_data(parse_iot_hub_name(), EVENT_FAILED, "Unexpected error %s from IoTHub" % iothub_error)
        return
    except KeyboardInterrupt:
        print ( "IoTHubClient sample stopped" )

    print_last_message_time(client)

def usage():
    print ( "Usage: iothub_client_sample.py -p <protocol> -c <connectionstring>" )
    print ( "    protocol        : <amqp, amqp_ws, http, mqtt, mqtt_ws>" )
    print ( "    connectionstring: <HostName=<host_name>;DeviceId=<device_id>;SharedAccessKey=<device_key>>" )

def parse_iot_hub_name():
    m = re.search("HostName=(.*?)\.", CONNECTION_STRING)
    return m.group(1)

if __name__ == "__main__":
    print ( "\nPython %s" % sys.version )
    print ( "IoT Hub Client for Python" )
    CCS811_init()
    PIR_setup()
    iothub_client_upload_sensors()
