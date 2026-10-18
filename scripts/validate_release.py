"""Independent source-to-report reconciliation; no calls to the normalizer."""
import csv
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'data/allocation_sell_through.json').read_text(encoding='utf-8'))
source=json.loads((ROOT/'data/source.json').read_text(encoding='utf-8'))
summary=data['summary']
expected={}
excluded=Counter()
eligible=defaultdict(list)
for week in source['allocations']:
    for row in week['products']:
        category=row['category_name'].strip().lower()
        if row['allocated_units']<=0 or row['unlimited']:
            excluded['zero_or_unlimited']+=1;continue
        text=row['product_name']+' | '+row['category_name']
        if row['type']=='sample' or re.search(r'trade\s*sample|(?<![A-Za-z0-9])TS(?![A-Za-z0-9])',text,re.I):
            excluded['trade_samples']+=1;continue
        if row['brand_name'].lower().startswith('non marijuana products') or 'accessories & merch' in category or category in {'phat panda neck gaiter/face covering','vape carry case'}:
            excluded['non_merchandise']+=1;continue
        assert row['allocated_units']==row['sold_units']+row['unsold_units']
        assert row['allocated_units']>=row['sold_units']>=0
        key=(week['inventory_allocation_id'],row['product_id'])
        assert key not in expected
        expected[key]=row
        eligible[row['product_id']].append(row)

actual={}
for product in data['products']:
    for values in product['history']:
        row=dict(zip(data['history_columns'],values))
        key=(row['week_id'],product['product_id'])
        actual[key]=row
        for field in ['allocated_units','sold_units','unsold_units','sold_revenue','order_count']:
            assert row[field]==expected[key][field],(key,field)
    rows=eligible[product['product_id']]
    sellouts=sum(r['unsold_units']==0 and r['sold_units']>0 for r in rows)
    assert product['weeks_available']==len(rows)
    assert product['soldout_weeks']==sellouts
    assert math.isclose(product['sellout_rate'],sellouts/len(rows),abs_tol=.000051)
assert set(expected)==set(actual)
assert len(eligible)==summary['product_count']
assert len(expected)==summary['eligible_product_weeks']
assert dict(excluded)==summary['excluded_rows']
assert len(expected)+sum(excluded.values())==summary['source_row_count']
assert sum(r['unsold_units']==0 and r['sold_units']>0 for r in expected.values())==summary['exact_sellout_occurrences']
for field,total in [('allocated_units','total_allocated_units'),('sold_units','total_sold_units'),('unsold_units','total_unsold_units'),('sold_revenue','total_sold_revenue')]:
    assert math.isclose(sum(r[field] for r in expected.values()),summary[total],abs_tol=.011)

for file,count in [('all_product_rankings.csv',summary['product_count']),('eligible_weekly_detail.csv',summary['eligible_product_weeks'])]:
    with (ROOT/'downloads'/file).open(encoding='utf-8-sig',newline='') as f:
        assert sum(1 for _ in csv.DictReader(f))==count

ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(ROOT/'downloads/Bamboo_Weekly_Sell_Through_8_Weeks.xlsx') as z:
    assert z.testzip() is None
    for sheet,count in [('sheet2.xml',summary['product_count']),('sheet3.xml',summary['source_row_count'])]:
        xml=ET.fromstring(z.read('xl/worksheets/'+sheet))
        rows=xml.findall('s:sheetData/s:row',ns)
        assert sum(int(r.attrib['r'])>=6 for r in rows)==count
        assert not xml.findall('.//s:c[@t="e"]',ns)
    assert sum('/charts/chart' in n and n.endswith('.xml') for n in z.namelist())>=2
assert (ROOT/'downloads/Bamboo_Sellout_Report_8_Weeks.pdf').read_bytes().startswith(b'%PDF-')
print(json.dumps({'status':'PASS','products':len(eligible),'eligible_product_weeks':len(expected),'source_rows':summary['source_row_count'],'sellout_occurrences':summary['exact_sellout_occurrences'],'excluded':dict(excluded)},sort_keys=True))
