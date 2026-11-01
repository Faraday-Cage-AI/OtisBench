"""Persistent JSONL decisions for engineering and long-horizon factory agents."""
import json
import math
import os
import selectors
import shlex
import subprocess
import time


class DecisionAgent:
    def __init__(self,command,timeout=120,max_reply_bytes=100000):
        if not math.isfinite(timeout) or timeout<=0:raise ValueError('timeout must be finite and positive')
        if type(max_reply_bytes) is not int or not 1<=max_reply_bytes<=8000000:raise ValueError('invalid reply byte limit')
        self.command=command;self.timeout=timeout;self.max_reply_bytes=max_reply_bytes;self.process=None;self.buffer=b''

    def __enter__(self):
        self.process=subprocess.Popen(shlex.split(self.command),stdin=subprocess.PIPE,stdout=subprocess.PIPE,bufsize=0)
        os.set_blocking(self.process.stdin.fileno(),False)
        self.selector=selectors.DefaultSelector();self.selector.register(self.process.stdout,selectors.EVENT_READ)
        return self

    def decide(self,track,payload):
        if self.process.poll() is not None:raise ValueError('decision agent exited')
        message=json.dumps(dict(type='decision',protocol='faraday-manufacturing/1',track=track,payload=payload)).encode()+b'\n'
        deadline=time.monotonic()+self.timeout;offset=0
        with selectors.DefaultSelector() as writer:
            writer.register(self.process.stdin,selectors.EVENT_WRITE)
            while offset<len(message):
                remaining=deadline-time.monotonic()
                if remaining<=0 or not writer.select(remaining):raise ValueError('decision agent input timed out')
                try:offset+=os.write(self.process.stdin.fileno(),message[offset:])
                except BlockingIOError:continue
                except BrokenPipeError:raise ValueError('decision agent exited before reading input')
        while b'\n' not in self.buffer:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not self.selector.select(remaining):raise ValueError('decision agent timed out')
            chunk=os.read(self.process.stdout.fileno(),65536)
            if not chunk:raise ValueError('decision agent exited without a complete reply')
            self.buffer+=chunk
            if len(self.buffer)>self.max_reply_bytes:raise ValueError('oversized decision line')
        line,self.buffer=self.buffer.split(b'\n',1)
        value=json.loads(line)
        if not isinstance(value,dict):raise ValueError('decision must be a JSON object')
        return value

    def __exit__(self,*args):
        self.selector.close()
        if self.process.stdin:self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        if self.process.stdout:self.process.stdout.close()
