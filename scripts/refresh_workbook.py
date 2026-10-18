#!/usr/bin/env python3
"""Refresh the artifact-authored XLSX template using only the Python standard library.

Preserves styles, panes, tables and native charts. Rebuilds all data rows and
formula caches, including chart caches, so CI needs no spreadsheet dependency.
"""
import copy
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
X = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
ET.register_namespace('x', X)
ET.register_namespace('c', C)
ET.register_namespace('a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
ET.register_namespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
def q(t): return f'{{{X}}}{t}'
def cq(t): return f'{{{C}}}{t}'
def column(n):
    result = ''
    while n:
        n, r = divmod(n-1,26)
        result = chr(65+r)+result
    return result
def serial(value): return (date.fromisoformat(value[:10])-date(1899,12,30)).days
def flag(p): return 'Limited history' if p['weeks_available']<4 else 'Small allocation' if p['median_weekly_allocated']<25 else '4+ weeks; median 25+ units'

def main():
    data=json.loads((ROOT/'data/allocation_sell_through.json').read_text(encoding='utf-8'))
    raw=json.loads((ROOT/'data/source.json').read_text(encoding='utf-8'))
    assert len(data['weeks'])==8, 'Workbook requires eight completed weeks'
    target=ROOT/'downloads/Bamboo_Weekly_Sell_Through_8_Weeks.xlsx'
    with ZipFile(target) as z: files={n:z.read(n) for n in z.namelist()}
    sheets=[ET.fromstring(files[f'xl/worksheets/sheet{i}.xml']) for i in range(1,5)]
    summary,ranking,detail,method=sheets
    row_indexes={}
    # Store explicit cached results so readers that do not recalculate still see current figures.
    def put(sheet, address, value, formula=None, style=None):
        sd=sheet.find(q('sheetData')); rn=int(re.search(r'\d+',address)[0])
        if id(sheet) not in row_indexes:row_indexes[id(sheet)]={int(r.get('r')):r for r in sd}
        row=row_indexes[id(sheet)].get(rn)
        if row is None:
            row=ET.SubElement(sd,q('row'),{'r':str(rn)})
            row_indexes[id(sheet)][rn]=row
        cell=row.find(f"{q('c')}[@r='{address}']")
        if cell is None: cell=ET.SubElement(row,q('c'),{'r':address})
        old_style=cell.get('s')
        cell.clear();cell.set('r',address)
        if style is not None or old_style is not None: cell.set('s',str(style if style is not None else old_style))
        if formula is not None: ET.SubElement(cell,q('f')).text=formula.lstrip('=')
        if value is None: return
        if isinstance(value,bool): cell.set('t','b');ET.SubElement(cell,q('v')).text='1' if value else '0'
        elif isinstance(value,(int,float)): ET.SubElement(cell,q('v')).text=str(value)
        elif formula is not None: cell.set('t','str');ET.SubElement(cell,q('v')).text=str(value)
        else: cell.set('t','inlineStr');ET.SubElement(ET.SubElement(cell,q('is')),q('t')).text=str(value)
    def replace_rows(sheet, rows, formulas=None):
        sd=sheet.find(q('sheetData'))
        prototype=sd.find(f"{q('row')}[@r='6']")
        styles={re.sub(r'\d','',c.get('r')):c.get('s') for c in prototype.findall(q('c'))}
        attrs={k:v for k,v in prototype.attrib.items() if k!='r'}
        for row in list(sd):
            if int(row.get('r'))>=6:sd.remove(row)
        row_indexes[id(sheet)]={int(r.get('r')):r for r in sd}
        for r,values in enumerate(rows,6):
            row=ET.SubElement(sd,q('row'),{'r':str(r),**attrs})
            row_indexes[id(sheet)][r]=row
            for n,value in enumerate(values,1):
                address=f'{column(n)}{r}'
                put(sheet,address,value,(formulas or {}).get(address),styles.get(column(n)))
        return len(rows)+5
    products=sorted(data['products'],key=lambda p:(-p['soldout_weeks'],-p['sellout_rate'],-p['total_sold_units'],str(p['product_id'])))
    rows=[];formulas={}
    for i,p in enumerate(products):
        r=i+6;hist={h[0]:h for h in p['history']}
        states=[]
        for w in data['weeks']:
            h=hist.get(w['id'])
            states.append('Not allocated' if h is None else 'Sold out' if h[3]==0 and h[2]>0 else '90%+ sold' if h[4]>=.9 else 'Available')
        rows.append([i+1,str(p['product_id']),p['product_name'],p['brand_name'],p['category_name'],p['weeks_available'],p['soldout_weeks'],p['soldout_weeks']/p['weeks_available'],p['total_allocated_units'],p['total_sold_units'],p['total_unsold_units'],p['total_sold_units']/p['total_allocated_units'],p['median_weekly_allocated'],p.get('longest_sellout_streak',0),p.get('latest_sellout_streak',0),p.get('latest_week_state',''),flag(p),p['total_sold_revenue'],*states])
        formulas[f'H{r}']=f'G{r}/F{r}';formulas[f'L{r}']=f'J{r}/I{r}'
    r_end=replace_rows(ranking,rows,formulas)
    for n,w in enumerate(data['weeks'],19):put(ranking,f'{column(n)}5',w['period_from'][:10])
    included={(w[0],p['product_id']) for p in products for w in p['history']}
    excluded={(r['week_id'],r['product_id']):r['reason'] for r in data.get('excluded_product_rows',[])}
    raw_rows=[]
    for w in sorted(raw['allocations'],key=lambda w:w['period_from']):
        for p in w['products']:
            key=(w['inventory_allocation_id'],p['product_id']);inc=key in included
            raw_rows.append([str(key[0]),serial(w['period_from']),serial(w['period_to']),str(p['product_id']),p['product_name'],p['brand_name'],p['category_name'],str(p['inventory_allocation_item_id']),p['allocated_units'],p['sold_units'],p['unsold_units'],p['sell_through'],p['sold_revenue'],p['order_count'],bool(p['unlimited']),'Yes' if inc else 'No','' if inc else excluded.get(key,'Excluded by eligibility rules'),'Yes' if inc and p['unsold_units']==0 and p['sold_units']>0 else 'No','Yes' if inc and p['sell_through']>=.9 else 'No',w.get('updated_at','')])
    d_end=replace_rows(detail,raw_rows)
    assert len(raw_rows)==data['summary']['source_row_count']
    assert len(included)==data['summary']['eligible_product_weeks']
    assert sum(p['soldout_weeks'] for p in products)==data['summary']['exact_sellout_occurrences']
    put(detail,'A4',f"Source: {data['source']['url']} | Generated: {raw['generated_at']} | Sales statuses: {', '.join(raw['sold_order_statuses'])}")
    s=data['summary'];put(summary,'A4',f"{s['period_from']} to {s['period_to']} | Eight completed Sunday–Saturday weeks")
    for address,value in [('B7',len(products)),('B8',sum(p['soldout_weeks']>=3 for p in products)),('B9',len(included)),('B10',sum(p['soldout_weeks'] for p in products)),('B11',len(raw_rows))]:put(summary,address,value)
    alloc=sum(p['total_allocated_units'] for p in products);sold=sum(p['total_sold_units'] for p in products)
    put(summary,'E7',alloc,f"SUM('Product rankings'!I6:I{r_end})");put(summary,'E8',sold,f"SUM('Product rankings'!J6:J{r_end})");put(summary,'E9',sold/alloc,'E8/E7')
    for r,w in enumerate(data['weeks'],15):
        vals=[w['period_from'][5:10],w['eligible_product_count'],w['eligible_allocated_units'],w['eligible_sold_units'],w['exact_sellouts'],w['eligible_sold_units']/w['eligible_allocated_units']]
        for n,v in enumerate(vals,1):put(summary,f'{column(n)}{r}',v,f'D{r}/C{r}' if n==6 else None)
    for i in range(12):
        p=products[i] if i<len(products) else None
        values=[p['product_name'],p['soldout_weeks'],p['weeks_available'],p['soldout_weeks']/p['weeks_available']] if p else [None]*4
        for n,(v,source_col) in enumerate(zip(values,['C','G','F','H']),1):put(summary,f'{column(n)}{i+28}',v,f"'Product rankings'!{source_col}{i+6}" if p else None)
        put(summary,f'E{i+28}',flag(p).replace('4+ weeks; median 25+ units','Comparable history') if p else '')
    for address,value in [('B21',len(raw_rows)),('B22',len(included)),('B23',len(raw_rows)-len(included)),('B24',raw['generated_at']),('B25',data['source']['url'])]:put(method,address,value)
    for i,sheet in enumerate(sheets,1):
        # XLSX requires row/cell address order after appending refreshed cells.
        sd=sheet.find(q('sheetData'))
        sd[:]=sorted(sd,key=lambda r:int(r.get('r')))
        for row in sd:
            row[:]=sorted(row,key=lambda c:(len(re.sub(r'\d','',c.get('r'))),re.sub(r'\d','',c.get('r'))))
        dim=sheet.find(q('dimension'))
        if dim is not None and i in (2,3):dim.set('ref',f'A1:{"Z" if i==2 else "T"}{r_end if i==2 else d_end}')
        if i==2:
            for cf in sheet.findall(q('conditionalFormatting')):cf.set('sqref',re.sub(r'\d+$',str(r_end),cf.get('sqref')))
        files[f'xl/worksheets/sheet{i}.xml']=ET.tostring(sheet,encoding='utf-8',xml_declaration=True)
    for name,end,last_col in [('xl/tables/table1.xml',r_end,'Z'),('xl/tables/table2.xml',d_end,'T')]:
        t=ET.fromstring(files[name]);ref=f'A5:{last_col}{end}';t.set('ref',ref)
        t.find(q('autoFilter')).set('ref',ref)
        if last_col=='Z':
            for tc,w in zip(t.find(q('tableColumns'))[18:],data['weeks']):tc.set('name',w['period_from'][:10])
        files[name]=ET.tostring(t,encoding='utf-8',xml_declaration=True)
    # Refresh all category and numeric caches while retaining source references and colors.
    for name in [n for n in files if '/charts/chart' in n and n.endswith('.xml')]:
        chart=ET.fromstring(files[name])
        for ref in chart.findall('.//'+cq('strRef'))+chart.findall('.//'+cq('numRef')):
            formula=ref.find(cq('f')).text
            match=re.search(r'\$([A-Z]+)\$(\d+):\$[A-Z]+\$(\d+)',formula)
            if not match:raise ValueError(f'Unsupported chart reference {formula}')
            c,first,last=match.groups();vals=[]
            for rn in range(int(first),int(last)+1):
                cell=summary.find(f"{q('sheetData')}/{q('row')}[@r='{rn}']/{q('c')}[@r='{c}{rn}']")
                vals.append(cell.find(q('is')).find(q('t')).text if cell.get('t')=='inlineStr' else cell.find(q('v')).text)
            cache=ref.find(cq('strCache')) if ref.tag==cq('strRef') else ref.find(cq('numCache'))
            fmt=cache.find(cq('formatCode'));fmt_text=fmt.text if fmt is not None else None
            cache.clear()
            if fmt_text is not None:ET.SubElement(cache,cq('formatCode')).text=fmt_text
            ET.SubElement(cache,cq('ptCount'),{'val':str(len(vals))})
            for i,v in enumerate(vals):ET.SubElement(ET.SubElement(cache,cq('pt'),{'idx':str(i)}),cq('v')).text=str(v)
        files[name]=ET.tostring(chart,encoding='utf-8',xml_declaration=True)
    with tempfile.NamedTemporaryFile(suffix='.xlsx',delete=False,dir=target.parent) as f: temp=Path(f.name)
    try:
        with ZipFile(temp,'w',ZIP_DEFLATED,compresslevel=6) as z:
            for name,content in files.items():z.writestr(name,content)
        with ZipFile(temp) as z:
            assert z.testzip() is None
            assert sum(int(r.get('r'))>=6 for r in ET.fromstring(z.read('xl/worksheets/sheet2.xml')).find(q('sheetData')))==len(products)
            assert sum(int(r.get('r'))>=6 for r in ET.fromstring(z.read('xl/worksheets/sheet3.xml')).find(q('sheetData')))==len(raw_rows)
        temp.replace(target)
    finally:
        if temp.exists():temp.unlink()
    print(json.dumps({'workbook':str(target),'products':len(products),'source_rows':len(raw_rows),'eligible_product_weeks':len(included),'sellout_occurrences':s['exact_sellout_occurrences'],'charts':2}))

if __name__=='__main__':main()
