"""Bounded declarative CSG execution and actual OpenCascade solid comparison.

Candidate Python is never evaluated. Optional CadQuery dependency is lazy-loaded.
"""
from copy import deepcopy
import importlib.metadata
import math
from pathlib import Path

MAX_NODES=64
MAX_DEPTH=12
PROGRAM_SCHEMA={
 'box':dict(op='box',size='three positive dimensions',origin='XYZ lower corner'),
 'cylinder':dict(op='cylinder',radius='positive radius',height='positive length',origin='XYZ start-center',axis='x | y | z'),
 'cone':dict(op='cone',radius1='positive start radius',radius2='positive end radius',height='positive length',origin='XYZ start-center',axis='x | y | z'),
 'fillet':dict(op='fillet',shape='shape node',radius='positive radius applied to ALL edges of child before later operations'),
 'chamfer':dict(op='chamfer',shape='shape node',distance='positive equal-distance chamfer on ALL edges of child before later operations'),
 'loft_rectangles':dict(op='loft_rectangles',sections='2..4 parallel XY rectangle objects: origin XYZ lower-left, size [X,Y]; strictly increasing Z; straight ruled sides'),
 'union':dict(op='union',children='2..16 shape nodes'),
 'cut':dict(op='cut',base='shape node',tools='1..16 shape nodes'),
 'translate':dict(op='translate',shape='shape node',vector='XYZ displacement'),
}


def validate(program):
    count=0
    def number(v,positive=False):
        if type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1000 or positive and v<.001:raise ValueError('invalid geometric scalar')
    def vector(v,positive=False):
        if not isinstance(v,list) or len(v)!=3:raise ValueError('expected XYZ vector')
        for x in v:number(x,positive)
    def visit(node,depth):
        nonlocal count
        count+=1
        if count>MAX_NODES or depth>MAX_DEPTH or not isinstance(node,dict):raise ValueError('program exceeds geometry bounds')
        op=node.get('op')
        if op=='box':
            if set(node)!={'op','size','origin'}:raise ValueError('invalid box fields')
            vector(node['size'],True);vector(node['origin'])
        elif op=='cylinder':
            if set(node)!={'op','radius','height','origin','axis'} or node['axis'] not in ('x','y','z'):raise ValueError('invalid cylinder fields')
            number(node['radius'],True);number(node['height'],True);vector(node['origin'])
        elif op=='cone':
            if set(node)!={'op','radius1','radius2','height','origin','axis'} or node['axis'] not in ('x','y','z'):raise ValueError('invalid cone fields')
            number(node['radius1'],True);number(node['radius2'],True);number(node['height'],True);vector(node['origin'])
        elif op in ('fillet','chamfer'):
            field='radius' if op=='fillet' else 'distance'
            if set(node)!={'op','shape',field}:raise ValueError('invalid edge treatment')
            number(node[field],True);visit(node['shape'],depth+1)
        elif op=='loft_rectangles':
            if set(node)!={'op','sections'} or not isinstance(node['sections'],list) or not 2<=len(node['sections'])<=4:raise ValueError('invalid loft sections')
            previous=None
            for section in node['sections']:
                if not isinstance(section,dict) or set(section)!={'origin','size'}:raise ValueError('invalid loft profile')
                vector(section['origin'])
                if not isinstance(section['size'],list) or len(section['size'])!=2:raise ValueError('invalid rectangle size')
                for value in section['size']:number(value,True)
                z=section['origin'][2]
                if previous is not None and z-previous<.001:raise ValueError('loft sections must increase in Z')
                previous=z
        elif op=='union':
            if set(node)!={'op','children'} or not isinstance(node['children'],list) or not 2<=len(node['children'])<=16:raise ValueError('invalid union')
            for child in node['children']:visit(child,depth+1)
        elif op=='cut':
            if set(node)!={'op','base','tools'} or not isinstance(node['tools'],list) or not 1<=len(node['tools'])<=16:raise ValueError('invalid cut')
            visit(node['base'],depth+1)
            for child in node['tools']:visit(child,depth+1)
        elif op=='translate':
            if set(node)!={'op','shape','vector'}:raise ValueError('invalid transform')
            vector(node['vector']);visit(node['shape'],depth+1)
        else:raise ValueError('unsupported CSG operation')
    visit(program,0);return count


def execute(program):
    validate(program)
    import cadquery as cq
    def node(p):
        op=p['op']
        if op=='box':return cq.Solid.makeBox(*p['size'],pnt=cq.Vector(*p['origin']))
        if op=='cylinder':
            direction={'x':(1,0,0),'y':(0,1,0),'z':(0,0,1)}[p['axis']]
            return cq.Solid.makeCylinder(p['radius'],p['height'],pnt=cq.Vector(*p['origin']),dir=cq.Vector(*direction))
        if op=='cone':
            direction={'x':(1,0,0),'y':(0,1,0),'z':(0,0,1)}[p['axis']]
            return cq.Solid.makeCone(p['radius1'],p['radius2'],p['height'],pnt=cq.Vector(*p['origin']),dir=cq.Vector(*direction))
        if op in ('fillet','chamfer'):
            shape=node(p['shape'])
            return shape.fillet(p['radius'],shape.Edges()) if op=='fillet' else shape.chamfer(p['distance'],None,shape.Edges())
        if op=='loft_rectangles':
            wires=[]
            for section in p['sections']:
                x,y,z=section['origin'];width,height=section['size']
                wires.append(cq.Wire.makePolygon([(x,y,z),(x+width,y,z),(x+width,y+height,z),(x,y+height,z)],close=True))
            return cq.Solid.makeLoft(wires,ruled=True)
        if op=='union':
            shapes=[node(c) for c in p['children']];return shapes[0].fuse(*shapes[1:]).clean()
        if op=='cut':return node(p['base']).cut(*(node(c) for c in p['tools'])).clean()
        return node(p['shape']).translate(tuple(p['vector']))
    return node(program)


def measure(shape):
    bounds=shape.BoundingBox();center=shape.Center()
    return dict(valid=bool(shape.isValid()),solids=len(shape.Solids()),volume_mm3=shape.Volume(),surface_mm2=shape.Area(),
        bounds_mm=[bounds.xmin,bounds.ymin,bounds.zmin,bounds.xmax,bounds.ymax,bounds.zmax],center_mm=list(center.toTuple()))


def compare(target,candidate):
    reference=measure(target);actual=measure(candidate)
    intersection=max(0,target.intersect(candidate).Volume())
    union=reference['volume_mm3']+actual['volume_mm3']-intersection
    symmetric=max(0,reference['volume_mm3']+actual['volume_mm3']-2*intersection)
    tolerance=max(1e-5,reference['volume_mm3']*1e-7)
    bounds_error=max(abs(a-b) for a,b in zip(reference['bounds_mm'],actual['bounds_mm']))
    checks=dict(valid_solid=actual['valid'] and actual['solids']==1,nonempty=actual['volume_mm3']>1e-6,
        symmetric_difference=symmetric<=tolerance,datum_bounds=bounds_error<=1e-4,
        volume=abs(reference['volume_mm3']-actual['volume_mm3'])<=tolerance)
    return dict(strict_success=all(checks.values()),score=100*sum(checks.values())/len(checks),checks=checks,candidate=actual,
        reference=reference,intersection_volume_mm3=intersection,symmetric_difference_mm3=symmetric,symmetric_difference_tolerance_mm3=tolerance,
        volume_iou=intersection/union if union>0 else 0,maximum_bound_error_mm=bounds_error)


def export_step(shape,path):
    import cadquery as cq
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);cq.exporters.export(shape,str(path),'STEP')
    # OCCT writes wall-clock creation timestamps. Fix only header timestamp to
    # make native public asset generation reproducible on the pinned kernel.
    import re
    text=path.read_text();text=re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}","2000-01-01T00:00:00",text)
    text=re.sub(r"Open CASCADE STEP translator [0-9.]+ \d+","Faraday synthetic part",text)
    path.write_text(text)


def import_step(path):
    import cadquery as cq
    p=Path(path)
    if not p.is_file() or p.stat().st_size>5_000_000:raise ValueError('STEP input missing or exceeds five MB')
    text=p.read_text(errors='strict')
    if 'ISO-10303-21' not in text:raise ValueError('not a STEP exchange file')
    # The pinned exporter uses millimeters. Alternate STEP units must be
    # explicitly converted by the submitting agent before grading.
    if 'SI_UNIT(.MILLI.,.METRE.)' not in text:raise ValueError('STEP must declare millimeter length units')
    imported=cq.importers.importStep(str(p));values=imported.vals()
    if not values:raise ValueError('STEP contains no shapes')
    return values[0] if len(values)==1 else cq.Compound.makeCompound(values)


def versions():
    return {name:importlib.metadata.version(name) for name in ('cadquery','cadquery-ocp','pillow')}
