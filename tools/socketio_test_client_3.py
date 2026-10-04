import sys
import time
import socketio

sio = socketio.Client()

@sio.event
def connect():
    print('connected')

@sio.on('pytest_output')
def on_output(data):
    print('OUT:', data)

@sio.on('pytest_result')
def on_result(data):
    print('RES:', data)

@sio.on('batch_report')
def on_batch(data):
    print('BATCH:', data)

@sio.on('test_result')
def on_test_result(data):
    print('TEST_RESULT:', data)

@sio.event
def disconnect():
    print('disconnected')

if __name__ == '__main__':
    sio.connect('http://127.0.0.1:5000')
    time.sleep(1)
    # single test
    print('emit single left_leg')
    sio.emit('run_test', {'target': 'left_leg', 'use_pytest': True})
    time.sleep(2)
    # batch
    print('emit batch')
    sio.emit('run_batch', {'use_pytest': True})
    # wait for batch to finish
    time.sleep(6)
    sio.disconnect()
