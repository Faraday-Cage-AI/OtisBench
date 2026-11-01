"""Build one inspectable public example packet without reference answers."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from pypdf import PdfReader,PdfWriter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle
from faraday_manufacturing_benchmark.document_cases import catalog,POLICY
from faraday_manufacturing_benchmark.documents import assets
ROOT=Path(__file__).resolve().parents[1]


def main():
    task=next(t for t in catalog() if t['family']=='split_delivery' and t['draw']==1 and t['mode']=='image_pdf');root,entry=assets(task)
    styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='BodySmall',fontName='Helvetica',fontSize=9.5,leading=12.5,spaceAfter=7));story=[]
    story.extend([Paragraph('Procurement document<br/>reconciliation',styles['Title']),Spacer(1,14),Paragraph('Synthetic example packet - image-only business documents',styles['Heading2']),Paragraph('Four purchase lines. Reconcile released revisions, shipments, quality, invoices and credits. Cite source pages; a carrier status or invoice copy alone does not establish accepted stock or a payable.',styles['BodyText']),Spacer(1,14)])
    data=[['Document','Pages']]+[[Paragraph(escape(d['title']),styles['BodySmall']),str(len(d['pages']))] for d in entry['documents']]
    table=Table(data,colWidths=[430,50]);table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#173C48')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#EDF2F4')]),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]));story.extend([table,Spacer(1,12),Paragraph('All source forms are synthetic and have no PDF text layer. The benchmark provides raw text extraction, OCR and image-page tools. This review packet contains no reference answer, solved plan or grading result.',styles['BodySmall']),PageBreak(),Paragraph('Public reconciliation policy',styles['Heading1'])])
    story.extend(Paragraph(escape(line),styles['BodySmall']) for line in POLICY.splitlines() if line)
    cover=BytesIO();SimpleDocTemplate(cover,pagesize=(612,792),rightMargin=54,leftMargin=54,topMargin=48,bottomMargin=48).build(story)
    writer=PdfWriter();writer.append(PdfReader(BytesIO(cover.getvalue())))
    for doc in entry['documents']:writer.append(PdfReader(BytesIO(root.joinpath(doc['filename']).read_bytes())),outline_item=doc['title'])
    writer.add_metadata({'/Title':'Synthetic procurement document reconciliation example','/Author':'Faraday Manufacturing Benchmark'})
    out=ROOT/'output/pdf/procurement-document-example.pdf';out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('wb') as stream:writer.write(stream)
    print(out,len(writer.pages),'pages')

if __name__=='__main__':main()
