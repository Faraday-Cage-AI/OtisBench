"""Deterministic raster engineering views from the actual target B-rep.

The PNG has pixel content only: no program, dimensions JSON, EXIF solution or
hidden SVG text. Human-readable dimension notes are part of the drawing itself.
"""
import io
import math
from .cad_cases import build
from .cad_kernel import execute


def projected_edges(shape,normal,x_direction):
    import cadquery as cq
    from OCP.HLRBRep import HLRBRep_Algo,HLRBRep_HLRToShape
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.gp import gp_Ax2,gp_Pnt,gp_Dir
    from OCP.BRepLib import BRepLib
    # Native hidden-line removal supplies face silhouettes, including cylinder
    # outlines that are absent from a solid's topological Edges() collection.
    algorithm=HLRBRep_Algo();algorithm.Add(shape.wrapped)
    algorithm.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(),gp_Dir(*normal),gp_Dir(*x_direction))))
    algorithm.Update();algorithm.Hide();output=HLRBRep_HLRToShape(algorithm)
    groups=[(False,output.VCompound()),(False,output.Rg1LineVCompound()),(False,output.OutLineVCompound()),(True,output.HCompound()),(True,output.OutLineHCompound())]
    edges=[]
    for hidden,compound in groups:
        if compound.IsNull():continue
        BRepLib.BuildCurves3d_s(compound,1e-6)
        for edge in cq.Shape(compound).Edges():
            n=2 if edge.geomType()=='LINE' else 65
            points=[edge.positionAt(i/(n-1)).toTuple() for i in range(n)]
            edges.append((hidden,[(p[0],-p[1]) for p in points]))
    return edges


def drawing_png(task):
    from PIL import Image,ImageDraw,ImageFont
    source=build(task);shape=execute(source['program']);image=Image.new('RGB',(1700,1250),'white');draw=ImageDraw.Draw(image)
    title=ImageFont.load_default(size=32);heading=ImageFont.load_default(size=23);body=ImageFont.load_default(size=20);small=ImageFont.load_default(size=17)
    navy='#173247';blue='#087D9B';gray='#607381';line='#B8C8D2'
    draw.text((40,25),'RELEASED ENGINEERING DRAWING / REVISION B',font=title,fill=navy)
    draw.text((40,70),source['part_name']+'  |  Units: mm  |  One solid  |  Datum XYZ',font=heading,fill=gray)
    draw.line((35,110,1665,110),fill=line,width=2)
    panels=[('TOP / +X right, +Y up',(40,135,550,590),(0,0,1),(1,0,0)),
            ('FRONT / +X right, +Z up',(580,135,1090,590),(0,-1,0),(1,0,0)),
            ('SIDE / +Y right, +Z up',(40,625,550,1080),(1,0,0),(0,1,0)),
            ('ISOMETRIC / datum orientation',(580,625,1090,1080),(1,1,1),(-1,1,0))]
    for label,(x0,y0,x1,y1),normal,x_direction in panels:
        draw.rounded_rectangle((x0,y0,x1,y1),radius=8,outline=line,width=2)
        draw.text((x0+15,y0+13),label,font=small,fill=navy)
        projected=projected_edges(shape,normal,x_direction);points=[p for _,edge in projected for p in edge]
        lo=[min(p[i] for p in points) for i in range(2)];hi=[max(p[i] for p in points) for i in range(2)]
        scale=min((x1-x0-80)/max(hi[0]-lo[0],1),(y1-y0-110)/max(hi[1]-lo[1],1))
        ox=(x0+x1)/2-(hi[0]+lo[0])/2*scale;oy=(y0+y1+30)/2-(hi[1]+lo[1])/2*scale
        for hidden,edge in sorted(projected,key=lambda item:not item[0]):
            pixels=[(ox+p[0]*scale,oy+p[1]*scale) for p in edge]
            if not hidden:draw.line(pixels,fill=navy,width=2);continue
            phase=0
            for a,b in zip(pixels,pixels[1:]):
                distance=math.hypot(b[0]-a[0],b[1]-a[1]);steps=max(1,math.ceil(distance/2))
                for j in range(steps):
                    if phase%5<3:
                        start=(a[0]+(b[0]-a[0])*j/steps,a[1]+(b[1]-a[1])*j/steps)
                        end=(a[0]+(b[0]-a[0])*(j+1)/steps,a[1]+(b[1]-a[1])*(j+1)/steps)
                        draw.line((start,end),fill=gray,width=1)
                    phase+=1
        draw.text((x0+15,y1-28),'Dashed: hidden. Dimensions govern.',font=small,fill=gray)
    x=1140;y=140;right=1660
    draw.text((x,y),'DIMENSIONS AND FEATURES',font=heading,fill=blue);y+=45
    for i,note in enumerate(source['notes'],1):
        # Pixel-measured wrapping avoids clipped dimensions on any part family.
        words=(f'{i}. '+note).split();lines=[];current=''
        for word in words:
            proposed=(current+' '+word).strip()
            if draw.textlength(proposed,font=body)>right-x and current:lines.append(current);current=word
            else:current=proposed
        if current:lines.append(current)
        for text in lines:
            if y+25>1170:raise ValueError('drawing notes exceed page; revise layout')
            draw.text((x,y),text,font=body,fill=navy);y+=27
        y+=16
    draw.line((35,1120,1090,1120),fill=line,width=2)
    draw.text((40,1140),'Coordinate views are schematic projections; use written dimensions, not pixel scale.',font=small,fill=gray)
    draw.text((40,1175),'Synthetic benchmark source / No manufacturing release or certification implied',font=small,fill=gray)
    output=io.BytesIO();image.save(output,format='PNG',optimize=False);return output.getvalue()
