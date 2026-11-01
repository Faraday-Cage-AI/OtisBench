"""Deterministic, readable procurement forms and actual image-only PDF variants."""
from pathlib import Path
from io import BytesIO
import subprocess
import tempfile
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from .document_cases import build

WIDTH,HEIGHT=612,792


def vector_pdf(document,style=0):
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(WIDTH,HEIGHT),invariant=1,pageCompression=1)
    c.setTitle(document['title']);c.setAuthor('Faraday Synthetic Benchmark');records=document['records'];pages=max(1,(len(records)+3)//4)
    for p in range(pages):
        c.setFillColor(HexColor('#173C48' if style==0 else '#34415D'));c.rect(0,HEIGHT-82,WIDTH,82,fill=1,stroke=0)
        c.setFillColorRGB(1,1,1);c.setFont('Helvetica-Bold',18);c.drawString(38,HEIGHT-34,document['headers']['Form']+' / SYNTHETIC RECORD')
        c.setFont('Helvetica',10);c.drawString(38,HEIGHT-55,document['title']);c.drawRightString(WIDTH-38,HEIGHT-72,f'Page {p+1} of {pages}')
        c.setFillColor(HexColor('#17242D'));y=HEIGHT-108;c.setFont('Courier',11)
        for key,value in document['headers'].items():c.drawString(38,y,f'{key}: {value}');y-=14
        y-=10
        for j,record in enumerate(records[p*4:(p+1)*4],p*4+1):
            c.setFillColor(HexColor('#EAF0F3'));c.rect(34,y-3,WIDTH-68,17,fill=1,stroke=0)
            c.setFillColor(HexColor('#17242D'));c.setFont('Courier-Bold',11);c.drawString(40,y,f'Record: {j}');y-=17;c.setFont('Courier',11)
            for key,value in record.items():
                line=f'{key}: {value}'
                if c.stringWidth(line,'Courier',11)>WIDTH-84:raise ValueError('form field exceeds printable width')
                c.drawString(42,y,line);y-=13
            y-=11
        if y<45:raise ValueError('form records exceed page height')
        c.setStrokeColor(HexColor('#C7D4DA'));c.line(38,37,WIDTH-38,37);c.setFont('Helvetica',8);c.setFillColor(HexColor('#52646E'))
        c.drawString(38,23,'Synthetic evaluation data - not a real order, certificate or payment instruction.')
        c.drawRightString(WIDTH-38,23,document['id']);c.showPage()
    c.save();return stream.getvalue()


def assets(document,style=0):
    vector=vector_pdf(document,style)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);pdf=root/'form.pdf';pdf.write_bytes(vector)
        subprocess.run(['pdftoppm','-r','150','-png',str(pdf),str(root/'page')],capture_output=True,check=True,timeout=30)
        pages=[p.read_bytes() for p in sorted(root.glob('page-*.png'),key=lambda p:int(p.stem.split('-')[-1]))]
    out=BytesIO();c=canvas.Canvas(out,pagesize=(WIDTH,HEIGHT),invariant=1,pageCompression=1)
    c.setTitle(document['title']);c.setAuthor('Faraday Synthetic Benchmark')
    for png in pages:c.drawImage(ImageReader(BytesIO(png)),0,0,width=WIDTH,height=HEIGHT);c.showPage()
    c.save();return vector,out.getvalue(),pages
