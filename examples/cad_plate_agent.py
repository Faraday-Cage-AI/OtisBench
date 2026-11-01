"""Text-only drilled-plate baseline. No evaluator imports and no vision claim."""
import ast
import json
import re
import sys


def decide(payload):
    text=payload['task'].get('description','')
    match=re.search(r'Rectangular plate: X length ([\d.]+), Y width ([\d.]+), Z thickness ([\d.]+)',text)
    bore=re.search(r'Four through bores, diameter ([\d.]+)',text)
    centers=re.search(r'Bore center XY coordinates: (\[.*\])',text)
    if not match or not bore or not centers:raise ValueError('example supports text_and_drawing drilled plates only')
    length,width,thickness=map(float,match.groups());radius=float(bore.group(1))/2;xy=ast.literal_eval(centers.group(1))
    program=dict(op='cut',base=dict(op='box',size=[length,width,thickness],origin=[0,0,0]),tools=[dict(op='cylinder',radius=radius,height=thickness+2,origin=[x,y,-1],axis='z') for x,y in xy])
    return dict(program=program)


def main():
    for line in sys.stdin:
        message=json.loads(line);print(json.dumps(decide(message['payload'])),flush=True)

if __name__=='__main__':main()
