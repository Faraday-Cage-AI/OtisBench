"""Synthetic dimensioned parts for executable B-rep geometry evaluation."""
from copy import deepcopy
import hashlib
import math
import random

FAMILIES=('drilled_plate','counterbore_plate','slotted_plate','pocket_block','stepped_shaft','flanged_bushing','angle_bracket','open_housing',
          'rounded_plate','chamfered_pocket','tapered_hub','lofted_adapter')
MODES=('text_and_drawing','drawing_only','revision_edit')


def catalog():
    tasks=[]
    for family in FAMILIES:
        for mode in MODES:
            for draw in range(2):
                tid=f'cad-{family}-{mode}-{draw+1:02}'
                tasks.append(dict(id=tid,family=family,mode=mode,draw=draw,seed=int.from_bytes(hashlib.sha256(tid.encode()).digest()[:8],'big'),provenance='synthetic-generated'))
    return tasks


def box(size,origin=(0,0,0)):return dict(op='box',size=list(size),origin=list(origin))
def cylinder(radius,height,origin,axis='z'):return dict(op='cylinder',radius=radius,height=height,origin=list(origin),axis=axis)
def union(*children):return dict(op='union',children=list(children))
def cut(base,*tools):return dict(op='cut',base=base,tools=list(tools))


def build(task):
    rng=random.Random(task['seed']);f=task['family'];length=rng.randrange(70,101,5);width=rng.randrange(40,61,5);thick=rng.randrange(8,15,2);radius=rng.choice([3,4,5]);notes=[]
    if f not in FAMILIES:raise ValueError('unknown CAD part family')
    if f=='drilled_plate':
        holes=[(12,12),(length-16,12),(12,width-13),(length-16,width-13)]
        program=cut(box((length,width,thick)),*[cylinder(radius,thick+2,(x,y,-1)) for x,y in holes])
        notes=[f'Rectangular plate: X length {length}, Y width {width}, Z thickness {thick}.',f'Four through bores, diameter {2*radius}, axes parallel to Z.',f'Bore center XY coordinates: {holes}.']
    elif f=='counterbore_plate':
        cx=length*.35;cy=width*.6;outer=radius+4;depth=3
        program=cut(box((length,width,thick)),cylinder(radius,thick+2,(cx,cy,-1)),cylinder(outer,depth+1,(cx,cy,thick-depth)))
        notes=[f'Rectangular plate: X {length}, Y {width}, Z {thick}.',f'Bore center XY: ({cx:g}, {cy:g}). Z-axis through bore diameter {2*radius}.',f'Counterbore opens on the TOP face: diameter {2*outer}, depth {depth}.']
    elif f=='slotted_plate':
        a=20;b=length-20;cy=width*.45
        slot=union(box((b-a,2*radius,thick+2),(a,cy-radius,-1)),cylinder(radius,thick+2,(a,cy,-1)),cylinder(radius,thick+2,(b,cy,-1)))
        program=cut(box((length,width,thick)),slot)
        notes=[f'Rectangular plate: X {length}, Y {width}, Z {thick}.',f'One Z-through capsule slot, width {2*radius}; semicircle radius {radius}.',f'Slot end-circle centers XY: ({a:g}, {cy:g}) and ({b:g}, {cy:g}).']
    elif f=='pocket_block':
        height=thick+12;px=10;py=8;pl=length-28;pw=width-20;depth=7
        program=cut(box((length,width,height)),box((pl,pw,depth+1),(px,py,height-depth)))
        notes=[f'Solid block: X {length}, Y {width}, Z {height}.',f'Open rectangular pocket on TOP: X size {pl}, Y size {pw}, depth {depth}.',f'Pocket lower-left XY corner: ({px}, {py}); vertical square walls, no fillets.']
    elif f=='stepped_shaft':
        r1=radius+8;r2=radius+3;l1=length//2;l2=length-l1;center=r1
        program=union(cylinder(r1,l1,(0,center,center),'x'),cylinder(r2,l2,(l1,center,center),'x'))
        notes=[f'Coaxial two-step shaft along +X. Axis at Y={center}, Z={center}.',f'First segment: X=0 to {l1}, diameter {2*r1}.',f'Second segment: X={l1} to {length}, diameter {2*r2}. Flat ends, sharp shoulder.']
    elif f=='flanged_bushing':
        outer=radius+8;flange=outer+5;height=thick+12;fh=4;center=flange
        program=cut(union(cylinder(flange,fh,(center,center,0)),cylinder(outer,height-fh,(center,center,fh))),cylinder(radius,height+2,(center,center,-1)))
        notes=[f'Coaxial bushing along +Z; center XY=({center}, {center}).',f'Bottom flange: outside diameter {2*flange}, Z=0 to {fh}.',f'Upper body: outside diameter {2*outer}, Z={fh} to {height}.',f'Coaxial through bore diameter {2*radius}. Flat ends, no chamfers.']
    elif f=='angle_bracket':
        height=35;t=6;cx=length*.65;cy=width*.55
        solid=union(box((length,width,t)),box((t,width,height),(0,0,t)))
        program=cut(solid,cylinder(radius,t+2,(cx,cy,-1)),cylinder(radius,t+2,(-1,width*.35,t+height*.6),'x'))
        notes=[f'Horizontal base: X {length}, Y {width}, thickness Z {t}.',f'Upright on X=0 edge: X thickness {t}, full Y width, Z={t} to {t+height}.',f'Base Z-through bore: diameter {2*radius}, XY=({cx:g}, {cy:g}).',f'Upright X-through bore: diameter {2*radius}, Y={width*.35:g}, Z={t+height*.6:g}.']
    elif f=='open_housing':
        height=30;wall=4
        program=cut(box((length,width,height)),box((length-2*wall,width-2*wall,height),(wall,wall,wall)),cylinder(radius,wall+2,(length*.6,-1,height*.55),'y'))
        notes=[f'Open-top rectangular housing: outer X {length}, Y {width}, Z {height}.',f'Uniform side walls and bottom thickness {wall}; square corners, no fillets.',f'One front-wall bore along +Y: diameter {2*radius}, X={length*.6:g}, Z={height*.55:g}.',f'The bore goes through the FRONT wall only (Y=0 to {wall}); rear wall remains intact.']
    elif f=='rounded_plate':
        holes=[(12,12),(length-16,12),(12,width-13),(length-16,width-13)]
        blank=dict(op='fillet',shape=box((length,width,thick)),radius=1)
        program=cut(blank,*[cylinder(radius,thick+2,(x,y,-1)) for x,y in holes])
        notes=[f'Blank envelope X {length}, Y {width}, Z {thick}; lower corner (0,0,0).',
            'Round ALL twelve edges of the rectangular blank with R1 before drilling; corner blends follow the common edge radius.',
            f'Four sharp-edged Z-through bores, diameter {2*radius}, center XY coordinates: {holes}.']
    elif f=='chamfered_pocket':
        height=thick+12;depth=7
        blank=dict(op='chamfer',shape=box((length,width,height)),distance=1)
        program=cut(blank,box((length-28,width-20,depth+1),(10,8,height-depth)))
        notes=[f'Blank envelope X {length}, Y {width}, Z {height}; lower corner (0,0,0).',
            'Apply equal-distance 1 mm chamfers to ALL twelve blank edges before pocketing.',
            f'Top pocket: X size {length-28}, Y size {width-20}, depth {depth}; lower-left XY (10,8). Pocket edges remain sharp.']
    elif f=='tapered_hub':
        outer=radius+10;flange=outer+5;height=thick+16;fh=4;center=flange
        taper=dict(op='cone',radius1=outer,radius2=outer-5,height=height-fh,origin=[center,center,fh],axis='z')
        program=cut(union(cylinder(flange,fh,(center,center,0)),taper),cylinder(radius,height+2,(center,center,-1)))
        notes=[f'Coaxial hub along +Z, center XY ({center},{center}).',f'Bottom flange diameter {2*flange}, Z=0 to {fh}.',
            f'Straight conical frustum from diameter {2*outer} at Z={fh} to diameter {2*(outer-5)} at Z={height}.',
            f'Coaxial sharp-edged through bore diameter {2*radius}; no edge rounds or chamfers.']
    else:
        height=thick+25
        sections=[dict(origin=[0,0,0],size=[length,width]),dict(origin=[3,2,12],size=[length-8,width-6]),dict(origin=[8,5,height],size=[length-20,width-14])]
        program=dict(op='loft_rectangles',sections=sections)
        notes=['Solid ruled-loft adapter; not a hollow duct. Closed XY rectangular sections joined by straight ruled side surfaces.',
            f'Bottom profile at Z=0: lower-left XY (0,0), size X {length}, Y {width}.',
            f'Middle profile at Z=12: lower-left XY (3,2), size X {length-8}, Y {width-6}.',
            f'Top profile at Z={height}: lower-left XY (8,5), size X {length-20}, Y {width-14}. Match corresponding rectangle corners; no twist.']
    baseline=deepcopy(program)
    def alter(node):
        if node['op']=='box':node['size'][2]+=2;return 'The base/block thickness differs from the released drawing.'
        if node['op']=='cylinder':node['radius']+=1;return 'The first external diameter differs from the released drawing.'
        if node['op']=='cone':node['radius1']+=1;return 'The first conical diameter differs from the released drawing.'
        if node['op']=='loft_rectangles':node['sections'][0]['size'][0]+=2;return 'The bottom loft profile differs from the released drawing.'
        if node['op'] in ('fillet','chamfer','translate'):return alter(node['shape'])
        return alter(node['base'] if node['op']=='cut' else node['children'][0])
    change=alter(baseline)
    common=['All dimensions are millimeters. Right-handed XYZ coordinates.','All unstated edges are sharp. Apply rounds/chamfers only where explicitly specified.','Coordinates are global; solid must occupy the drawn datum position.','Reconstruct one watertight solid. Drawing geometry and dimensions define the target.']
    return dict(program=program,baseline_program=baseline,notes=common+notes,revision_note=change+' Produce released revision B; all other geometry must match the released drawing.',part_name=f.replace('_',' ').title())
