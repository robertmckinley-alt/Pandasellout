"""Create the shareable PDF and CSV reports from the audited weekly dataset."""
from pathlib import Path
import csv
import json
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.graphics.shapes import Drawing, Rect, String, Line

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'downloads'
INK = colors.HexColor('#16312c')
GREEN = colors.HexColor('#087f5b')
PALE = colors.HexColor('#e9f5ef')
GRAY = colors.HexColor('#52635c')
LINE = colors.HexColor('#dce7e1')
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='ReportTitle', fontName='Helvetica-Bold', fontSize=29, leading=33, textColor=INK, spaceAfter=12))
styles.add(ParagraphStyle(name='ReportH1', fontName='Helvetica-Bold', fontSize=17, leading=21, textColor=INK, spaceAfter=10))
styles.add(ParagraphStyle(name='ReportBody', fontName='Helvetica', fontSize=10, leading=15, textColor=INK, spaceAfter=8))
styles.add(ParagraphStyle(name='ReportSmall', fontName='Helvetica', fontSize=8, leading=11, textColor=GRAY, spaceAfter=6))
styles.add(ParagraphStyle(name='TableText', fontName='Helvetica', fontSize=8, leading=10, textColor=INK))
styles.add(ParagraphStyle(name='TableHead', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.white))
styles.add(ParagraphStyle(name='Num', parent=styles['TableText'], alignment=TA_RIGHT))

def para(text, style='ReportBody'):
    return Paragraph(escape(str(text)), styles[style])

def num(value):
    return f'{value:,.0f}'

def pct(value):
    return f'{value:.1%}'

def table(headers, rows, widths):
    cells = [[para(v, 'TableHead') for v in headers]]
    cells.extend([[para(v, 'TableText') for v in row] for row in rows])
    obj = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
    obj.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), INK),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f3f7f4')]),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 8), ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LINEBELOW', (0,-1), (-1,-1), .5, LINE),
    ]))
    return obj

def weekly_chart(weeks):
    drawing = Drawing(510, 190)
    max_count = max(w['exact_sellouts'] for w in weeks) * 1.2
    for i, w in enumerate(weeks):
        x = 18 + i * 62
        height = w['exact_sellouts'] / max_count * 115
        drawing.add(Rect(x, 36, 39, height, fillColor=GREEN, strokeColor=None))
        drawing.add(String(x+19.5, height+43, num(w['exact_sellouts']), textAnchor='middle', fontName='Helvetica-Bold', fontSize=10, fillColor=INK))
        label = w['period_to'][5:].replace('-', '/')
        drawing.add(String(x+19.5, 22, label, textAnchor='middle', fontName='Helvetica', fontSize=8, fillColor=GRAY))
        drawing.add(String(x+19.5, 9, pct(w['exact_sellouts']/w['eligible_product_count']), textAnchor='middle', fontName='Helvetica', fontSize=8, fillColor=GRAY))
    drawing.add(Line(10,36,505,36,strokeColor=LINE))
    drawing.add(String(10,176,'Exact sellout occurrences by week',fontName='Helvetica-Bold',fontSize=11,fillColor=INK))
    return drawing

def allocation_chart(product, weeks, columns):
    history = {r['week_id']: r for r in [dict(zip(columns,row)) for row in product['history']]}
    drawing = Drawing(510, 193)
    highest = max(r['allocated_units'] for r in history.values()) or 1
    drawing.add(String(10,179,product['product_name'],fontName='Helvetica-Bold',fontSize=11,fillColor=INK))
    for i, w in enumerate(weeks):
        x = 18+i*62
        r = history.get(w['id'])
        if r:
            h = r['allocated_units']/highest*110
            s = r['sold_units']/highest*110
            drawing.add(Rect(x,37,41,h,fillColor=colors.HexColor('#cfdfd4'),strokeColor=None))
            drawing.add(Rect(x+8,37,25,s,fillColor=GREEN,strokeColor=None))
            drawing.add(String(x+20.5,h+44,f"{num(r['sold_units'])}/{num(r['allocated_units'])}",textAnchor='middle',fontName='Helvetica',fontSize=7,fillColor=INK))
        drawing.add(String(x+20.5,23,w['period_to'][5:].replace('-','/'),textAnchor='middle',fontName='Helvetica',fontSize=8,fillColor=GRAY))
    drawing.add(String(10,5,'Pale: allocated units. Green: sold units. Labels: sold / allocated.',fontName='Helvetica',fontSize=8,fillColor=GRAY))
    return drawing

def breakdown(products, field):
    groups = {}
    for p in products:
        g = groups.setdefault(p[field], {'products':0,'events':0,'offered':0,'sold':0,'allocated':0})
        g['products'] += 1
        g['events'] += p['soldout_weeks']
        g['offered'] += p['weeks_available']
        g['sold'] += p['total_sold_units']
        g['allocated'] += p['total_allocated_units']
    return sorted(groups.items(), key=lambda kv:kv[1]['events'], reverse=True)

def footer(canvas, doc):
    canvas.setStrokeColor(LINE)
    canvas.line(42,36,553,36)
    canvas.setFont('Helvetica',8)
    canvas.setFillColor(GRAY)
    canvas.drawString(42,23,'Panda Sellout Intelligence | Wholesale allocation analysis')
    canvas.drawRightString(553,23,str(doc.page))

def write_csvs(data):
    fields = ['product_id','product_name','brand_name','category_name','weeks_available','soldout_weeks','sellout_rate','coverage_rate','latest_sellout_streak','longest_sellout_streak','latest_week_state','total_allocated_units','total_sold_units','total_unsold_units','weighted_sell_through','median_weekly_allocated','signal','rationale']
    with (OUT/'all_product_rankings.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(data['products'])
    weeks={w['id']:w for w in data['weeks']}
    fields=['product_id','product_name','brand_name','category_name','period_from','period_to','allocated_units','sold_units','unsold_units','sell_through','sold_revenue','order_count','exact_sellout']
    with (OUT/'eligible_weekly_detail.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for p in data['products']:
            for values in p['history']:
                r=dict(zip(data['history_columns'],values));w=weeks[r['week_id']]
                writer.writerow({**p,**r,'period_from':w['period_from'],'period_to':w['period_to'],'exact_sellout':r['allocated_units']>0 and r['sold_units']>0 and r['unsold_units']==0})

def build():
    data=json.loads((ROOT/'data/allocation_sell_through.json').read_text(encoding='utf-8'))
    s=data['summary'];weeks=data['weeks'];products=data['products']
    ranked=sorted(products,key=lambda p:(p['soldout_weeks'],p['sellout_rate'],p['weeks_available'],p['total_sold_units']),reverse=True)
    established=[p for p in ranked if p['weeks_available']>=4 and p['soldout_weeks']>=2]
    repeated=sum(p['soldout_weeks']>=2 for p in products)
    frequent=sum(p['soldout_weeks']>=3 for p in products)
    OUT.mkdir(exist_ok=True)
    story=[para('What keeps selling out?', 'ReportTitle'),para(f"Eight completed weeks | {s['period_from']} to {s['period_to']}",'ReportH1'),para(f"Source generated {data['source']['generated_at']}. Historical weekly data in America/Los_Angeles.",'ReportSmall')]
    story += [table(['Eligible products','Sellout events','Repeat products (2+)','Weighted sell-through'],[[num(s['product_count']),num(s['exact_sellout_occurrences']),num(repeated),pct(s['total_sold_units']/s['total_allocated_units'])]],[128,128,128,128]),Spacer(1,14)]
    p=ranked[0]
    story.append(para(f"{p['product_name']} has the most observed sellout weeks: {p['soldout_weeks']} of {p['weeks_available']} offered weeks ({pct(p['sellout_rate'])}). It sold {num(p['total_sold_units'])} of {num(p['total_allocated_units'])} allocated units across this window."))
    story.append(para(f"{num(repeated)} products exhausted allocations in at least two weeks; {num(frequent)} did so in at least three. These are observed repeat events, not proof of unmet retail demand."))
    story.append(weekly_chart(weeks))
    latest=weeks[-1];prior=weeks[-2]
    story.append(para(f"The latest week ended {latest['period_to']} with {latest['exact_sellouts']} sellouts among {latest['eligible_product_count']} eligible products ({pct(latest['exact_sellouts']/latest['eligible_product_count'])}). The prior week recorded {prior['exact_sellouts']}. Product mix and allocations change, so this comparison does not by itself show a change in consumer demand."))
    story.append(para('Scope: allocation exhaustion measured from weekly order totals. Submitted and pending orders are included. Daily sellout timing, retail inventory outages and lost sales cannot be calculated from this endpoint.','ReportSmall'))
    story += [PageBreak(),para('The repeat-sellout leaderboard','ReportH1'),para('Products below were offered in at least four of the eight weeks and sold out at least twice. Ranked by exact sellout weeks, then frequency and units sold. Coverage is shown so short histories remain visible.')]
    rows=[]
    for p in established[:20]:
        rows.append([p['product_name'],f"{p['soldout_weeks']}/{p['weeks_available']}",pct(p['sellout_rate']),f"{num(p['total_sold_units'])} / {num(p['total_allocated_units'])}",pct(p['total_sold_units']/p['total_allocated_units'])])
    story.append(table(['Product','Weeks out','Frequency','Sold / allocated','Sell-through'],rows,[229,53,65,100,65]))
    story.append(Spacer(1,10))
    story.append(para(f"Frequency = sold-out weeks / eligible offered weeks. Sell-through = total units sold / total units allocated. A product absent from a week is not counted as a failed sale. All {num(s['product_count'])} eligible products and all original source rows are available in the workbook.",'ReportSmall'))
    story += [PageBreak(),para('Allocation size changes the interpretation','ReportH1')]
    p=ranked[0]
    story.append(allocation_chart(p,weeks,data['history_columns']))
    story.append(para(f"{p['product_name']} sold out {p['soldout_weeks']} times, but its latest-week state is {p['latest_week_state'].replace('_',' ')}. Its current consecutive calendar-week sellout streak is {p['latest_sellout_streak']}; its longest streak was {p['longest_sellout_streak']}. Review the weekly allocation bars before making a supply decision."))
    limited=[p for p in ranked if p['weeks_available']<4 and p['soldout_weeks']>=2][:6]
    story.append(para('Strong rates with limited history','ReportH1'))
    story.append(table(['Product','Sold-out / offered','Sold / allocated'],[[p['product_name'],f"{p['soldout_weeks']} / {p['weeks_available']}",f"{num(p['total_sold_units'])} / {num(p['total_allocated_units'])}"] for p in limited],[300,100,112]))
    story.append(Spacer(1,12))
    story.append(para('Practical review sequence: start with repeated sellouts on meaningful, stable allocations; confirm pending orders and product availability; inspect recent weeks; then discuss supply with the team. A high rate from one or two small allocations is a watch item. No automatic production, pricing or lost-revenue estimate is supported.'))
    story += [PageBreak(),para('Where sellouts concentrate','ReportH1'),para('Counts show exhausted product-week allocations. Rates use eligible product-weeks within each group. Unit sell-through is weighted by allocation volume; it is a different measure from sellout frequency.')]
    for title,field,limit in [('Brands','brand_name',8),('Categories','category_name',12)]:
        story.append(para(title,'ReportH1'))
        rows=[]
        for name,g in breakdown(products,field)[:limit]:
            rows.append([name,num(g['products']),num(g['events']),pct(g['events']/g['offered']),pct(g['sold']/g['allocated'])])
        story.append(table(['Group','Products','Events','Event rate','Sell-through'],rows,[255,55,58,72,72]))
        story.append(Spacer(1,12))
    story += [PageBreak(),para('Definitions, audit and source','ReportH1')]
    notes=[
        ('Source',data['source']['url']),
        ('Time window',f"{s['week_count']} completed Sunday-Saturday allocation periods, {s['period_from']} to {s['period_to']}; source timezone America/Los_Angeles."),
        ('Exact sellout','A valid, finite, positive allocation with positive sold units and zero remaining units. Overselling and inconsistent quantities are exceptions rather than automatic sellouts.'),
        ('Near sellout','At least 90% of an eligible allocation sold; exact sellouts are included in the 90%+ measure but separately labeled.'),
        ('Frequency and coverage','Frequency is exact sold-out weeks divided by weeks offered. Coverage is offered weeks divided by eight. Streaks require consecutive calendar weeks and break when a product is absent.'),
        ('Weighted sell-through','Total eligible sold units divided by total eligible allocated units. Weekly percentages are not averaged.'),
        ('Eligibility','Trade samples, non-marijuana merchandise, zero/unlimited allocations and anomalous records are excluded from the analytical denominator. The full original source is retained.'),
        ('Sales status',', '.join(data['source']['sold_order_statuses'])+'. These are wholesale order totals, including submitted and pending orders.'),
        ('Missing detail','No store-level records, dated sellout events, restock events, within-week timestamps, duration unavailable or lost-demand observations are provided.'),
        ('Refresh','Weekly automated refresh recreates the dataset, workbook, PDF and CSVs from the latest eight completed periods. The dashboard displays source freshness and reports stale or failed loads.'),
    ]
    for heading,text in notes:
        story.append(Paragraph('<b>'+escape(heading)+'.</b> '+escape(text),styles['ReportBody']))
    story.append(Spacer(1,10))
    story.append(KeepTogether([table(['Audit measure','Count'],[['Original product-week rows',num(s['source_row_count'])],['Eligible product-weeks',num(s['eligible_product_weeks'])],['Excluded merchandise',num(s['excluded_rows']['non_merchandise'])],['Excluded trade samples',num(s['excluded_rows']['trade_samples'])],['Excluded zero/unlimited allocations',num(s['excluded_rows']['zero_or_unlimited'])],['Anomaly records',num(len(data['quality']['anomaly_rows']))]],[360,152])]))
    path=OUT/'Bamboo_Sellout_Report_8_Weeks.pdf'
    SimpleDocTemplate(str(path),pagesize=(595.28,841.89),leftMargin=42,rightMargin=41.28,topMargin=42,bottomMargin=48,title='Panda Sellout Intelligence - Eight Week Report',author='Panda Sellout Intelligence').build(story,onFirstPage=footer,onLaterPages=footer)
    write_csvs(data)
    print(json.dumps({'pdf':str(path),'eligible_products':s['product_count'],'repeat_2plus':repeated,'repeat_3plus':frequent}))

if __name__=='__main__':
    build()
