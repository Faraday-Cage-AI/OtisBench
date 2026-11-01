"""Public raw-vibration baseline; supports vibration_order tasks only.

Uses no evaluator package or answer files. This is a hand-coded control, not a
model-performance result and not a solver for other sensor families.
"""
import csv
import io
import json
import math
import sys


class VibrationAgent:
    def __init__(self):self.plan=self.actions();self.started=False
    def decide(self,track,payload):
        if not self.started:self.started=True;return next(self.plan)
        if not payload['last_result']['ok']:raise ValueError(payload['last_result']['error'])
        return self.plan.send(payload['last_result'])

    def actions(self):
        def call(tool,**arguments):return (yield dict(tool=tool,arguments=arguments))
        yield from call('read_asset')
        policy=(yield from call('read_policy'))['policy']
        if policy['analysis_type']!='vibration_order':raise ValueError('this example supports vibration_order only')
        stream=(yield from call('list_streams'))['streams'][0];rows=[];cursor=0
        while cursor is not None:
            page=yield from call('read_stream',stream_id=stream['id'],cursor=cursor,limit=64)
            rows.extend(csv.DictReader(io.StringIO(page['csv'])));cursor=page['next_cursor']
        p=policy['parameters'];values=[];times=[]
        for row in rows:
            if row['quality']!='good' or not row['velocity_mm_s'] or not row['time_s']:continue
            values.append(float(row['velocity_mm_s']));times.append(float(row['time_s']))
        n=len(values)
        if n!=len(rows) or n<2 or any(abs((b-a)-1/p['sample_hz'])>1e-7 for a,b in zip(times,times[1:])):
            assessment=dict(valid_samples=n,rms_mm_s=None,dominant_hz=None,dominant_order=None,diagnosis='unknown',decision='inspect')
        else:
            centered=[v-sum(values)/n for v in values];best=None
            for k in range(1,n//2+1):
                real=sum(v*math.cos(2*math.pi*k*i/n) for i,v in enumerate(centered));imag=sum(v*math.sin(2*math.pi*k*i/n) for i,v in enumerate(centered));power=real*real+imag*imag
                if best is None or power>best[0]:best=(power,k)
            frequency=best[1]*p['sample_hz']/n;order=frequency*60/p['shaft_rpm'];rms=math.sqrt(sum(v*v for v in values)/n)
            diagnosis='imbalance' if abs(order-1)<=p['order_tolerance'] else 'misalignment' if abs(order-2)<=p['order_tolerance'] else 'other'
            decision='stop' if rms>=p['stop_rms_mm_s'] else 'inspect' if diagnosis=='other' else 'continue'
            assessment=dict(valid_samples=n,rms_mm_s=rms,dominant_hz=frequency,dominant_order=order,diagnosis=diagnosis,decision=decision)
        proposal=(yield from call('propose',assessment=assessment))['proposal']['id']
        approval=(yield from call('request_approval',proposal_id=proposal))['approval']['id']
        result=yield from call('execute',proposal_id=proposal,approval_id=approval);rid=result['assessment_id']
        yield from call('read_result',assessment_id=rid)
        yield from call('finish',assessment_id=rid)


def main():
    agent=VibrationAgent()
    for line in sys.stdin:
        message=json.loads(line);print(json.dumps(agent.decide(message['track'],message['payload'])),flush=True)

if __name__=='__main__':main()
