#!/usr/bin/env python3
"""Normalize eight completed weekly allocation reports; no demand forecasts."""
from __future__ import annotations
import argparse
import json
import math
import re
import statistics
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

API_URL = 'https://api-intelligence.getbamboo.com/api/reports/allocation-sell-through?limit=8'
ROOT = Path(__file__).resolve().parents[1]
TRADE_SAMPLE_RE = re.compile(r'trade\s*sample|(^|[^A-Za-z0-9])TS([^A-Za-z0-9]|$)', re.I)
# Exact accessory category names, independent of brand. Do not infer from
# generic words such as "case", which also occur in cannabis beverage packs.
MERCHANDISE_CATEGORIES = frozenset({'phat panda neck gaiter/face covering', 'vape carry case'})
HISTORY_COLUMNS = ['week_id', 'allocated_units', 'sold_units', 'unsold_units', 'sell_through', 'sold_revenue', 'order_count']

def pacific_date(instant):
    try: return instant.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
    except ZoneInfoNotFoundError:
        # Windows Python can lack the IANA database. Modern US DST: second
        # Sunday in March at 10 UTC through first Sunday in November at 09 UTC.
        year=instant.year
        march=datetime(year,3,8,10,tzinfo=timezone.utc)
        november=datetime(year,11,1,9,tzinfo=timezone.utc)
        start=march+timedelta(days=(6-march.weekday())%7)
        end=november+timedelta(days=(6-november.weekday())%7)
        offset=-7 if start<=instant<end else -8
        return instant.astimezone(timezone(timedelta(hours=offset))).date().isoformat()

def number(value, default=0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default

def percentile(values, pct):
    values = sorted(values)
    if not values: return 0
    position = (len(values)-1)*pct
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi]-values[lo])*(position-lo)

def exclusion(product):
    if number(product.get('allocated_units')) <= 0 or product.get('unlimited'): return 'zero_or_unlimited'
    if product.get('type') == 'sample' or TRADE_SAMPLE_RE.search(' | '.join(str(product.get(k) or '') for k in ('product_name','category_name'))): return 'trade_samples'
    category=str(product.get('category_name') or '').strip().lower()
    if str(product.get('brand_name') or '').lower().startswith('non marijuana products') or 'accessories & merch' in category or category in MERCHANDISE_CATEGORIES: return 'non_merchandise'
    if not product.get('product_id'): return 'missing_product_id'
    return None

def row_anomalies(product):
    issues = []
    values = [product.get(k) for k in ('allocated_units','sold_units','unsold_units')]
    if any(v is None or not isinstance(v, (int,float)) or not math.isfinite(v) for v in values): return ['missing_or_invalid_quantity']
    allocated, sold, unsold = values
    if min(values) < 0: issues.append('negative_quantity')
    if sold > allocated: issues.append('oversold')
    if allocated != sold + unsold: issues.append('quantity_reconciliation')
    if allocated and abs(number(product.get('sell_through'), sold/allocated)-sold/allocated) > 0.00011: issues.append('source_rate_mismatch')
    return issues

def weighted_sell_through(rows):
    allocated = sum(r['allocated_units'] for r in rows)
    return sum(r['sold_units'] for r in rows)/allocated if allocated else 0

def classify(rows, weeks_available, median_allocated, soldout_weeks, near_sellout_weeks, recent_rows=None):
    recent = rows[-4:] if recent_rows is None else recent_rows
    overall, latest = weighted_sell_through(rows), weighted_sell_through(recent)
    if weeks_available < 4 or median_allocated < 25: return 'Limited history', 0, 'Hold', 'Limited comparable history or small typical allocation; review before drawing a demand conclusion.'
    if soldout_weeks >= 3 and soldout_weeks/weeks_available >= .5 and overall >= .85 and latest >= .85:
        return 'Chronic sellout', 0, 'Review supply first', 'Repeated full weekly allocations; review supply and allocation changes. Unmet demand is not measured.'
    if soldout_weeks >= 3 and overall >= .75 and latest >= .75:
        return 'Recurring sellout', 0, 'Review supply first', 'At least three exact weekly sellouts; review supply before changing allocation.'
    if soldout_weeks >= 3: return 'Volatile allocation', 0, 'Hold', 'Repeat sellouts coexist with inconsistent sell-through on other allocations.'
    if near_sellout_weeks >= math.ceil(weeks_available/2) and overall >= .9: return 'Consistent fast mover', 0, 'Hold', 'At least half the offered weeks reached 90%; no automatic allocation or pricing change.'
    if len(recent)>=2 and sum(r['is_sellout'] for r in recent)>=1 and sum(r['is_near_sellout'] for r in recent)>=2 and latest>=.75: return 'Emerging shortage', 0, 'Hold', 'Recent allocation exhaustion warrants a supply review; unmet demand is not measured.'
    if len(recent)>=3 and latest<.5: return 'Slow mover', 0, 'Hold', 'Recent weighted sell-through is below 50%; investigate allocation and assortment.'
    if .7<=latest<.9: return 'Balanced', 0, 'Hold', 'Recent weighted sell-through is between 70% and 90%.'
    return 'Watch', 0, 'Hold', 'No sustained repeat shortage signal.'

def build_dataset(api):
    generated = api.get('generated_at')
    today = pacific_date(datetime.fromisoformat(generated.replace('Z','+00:00')) if generated else datetime.now(timezone.utc))
    allocations = sorted(api.get('allocations', []), key=lambda a:a.get('period_from',''))
    weeks, histories, excluded_rows, anomaly_rows = [], defaultdict(list), [], []
    excluded, quality_counts = Counter(), Counter()
    names, source_row_count = defaultdict(set), 0
    for allocation in allocations:
        week = {k:allocation.get(k) for k in ('name','period_from','period_to','updated_at','allocated_units','sold_units','unsold_units','sell_through','sold_revenue','product_count')}
        week.update(id=allocation.get('inventory_allocation_id'), exact_sellouts=0, near_sellouts=0, eligible_product_count=0, eligible_allocated_units=0, eligible_sold_units=0, eligible_unsold_units=0, eligible_sold_revenue=0, is_completed=bool(allocation.get('period_to') and allocation['period_to']<today))
        seen = set()
        for product in allocation.get('products', []):
            source_row_count += 1
            pid = product.get('product_id')
            reason = exclusion(product)
            issues = row_anomalies(product)
            if pid in seen: issues.append('duplicate_product_week')
            seen.add(pid)
            for issue in issues: quality_counts[issue]+=1
            if issues: anomaly_rows.append({'week_id':week['id'],'product_id':pid,'product_name':product.get('product_name'),'issues':issues})
            if not week['is_completed']: reason = 'incomplete_week'
            if reason:
                excluded[reason]+=1
                excluded_rows.append({**{k:product.get(k) for k in ('product_id','product_name','brand_name','category_name','allocated_units','sold_units','unsold_units','sold_revenue')},'week_id':week['id'],'reason':reason})
                continue
            if 'duplicate_product_week' in issues: continue
            allocated,sold,unsold = [number(product.get(k)) for k in ('allocated_units','sold_units','unsold_units')]
            st=sold/allocated
            row={**product,'week_id':week['id'],'allocated_units':allocated,'sold_units':sold,'unsold_units':unsold,'sell_through':round(st,4),'sold_revenue':number(product.get('sold_revenue')),'order_count':number(product.get('order_count')),'is_sellout':not issues and allocated>0 and sold==allocated and unsold==0,'is_near_sellout':not issues and st>=.9,'anomalies':issues}
            histories[pid].append(row)
            names[pid].add(product.get('product_name'))
            week['eligible_product_count']+=1
            for k in ('allocated_units','sold_units','unsold_units','sold_revenue'): week['eligible_'+k]+=row[k]
            week['exact_sellouts']+=int(row['is_sellout'])
            week['near_sellouts']+=int(row['is_near_sellout'])
        week['eligible_sold_revenue']=round(week['eligible_sold_revenue'],2)
        week['eligible_sell_through']=round(week['eligible_sold_units']/week['eligible_allocated_units'],4) if week['eligible_allocated_units'] else 0
        weeks.append(week)
    recent_ids={w['id'] for w in weeks[-4:]}
    prior_ids={w['id'] for w in weeks[-8:-4]}
    products=[]
    for pid, rows in histories.items():
        first=rows[-1]; count=len(rows); sells=sum(r['is_sellout'] for r in rows); near=sum(r['is_near_sellout'] for r in rows)
        recent=[r for r in rows if r['week_id'] in recent_ids]; prior=[r for r in rows if r['week_id'] in prior_ids]
        median=statistics.median(r['allocated_units'] for r in rows)
        signal,adjustment,price,rationale=classify(rows,count,median,sells,near,recent)
        by_week={r['week_id']:r for r in rows}; current=longest=0
        for w in weeks:
            current=current+1 if by_week.get(w['id'],{}).get('is_sellout') else 0
            longest=max(longest,current)
        last=by_week.get(weeks[-1]['id']) if weeks else None
        latest_state='not_offered' if last is None else ('anomaly' if last['anomalies'] else 'sellout' if last['is_sellout'] else 'near_sellout' if last['is_near_sellout'] else 'available')
        anomaly_count=sum(bool(r['anomalies']) for r in rows)
        if anomaly_count: signal,price,rationale='Data review','Hold','Quantity or source consistency issue; resolve before acting.'
        total_allocated=sum(r['allocated_units'] for r in rows); total_sold=sum(r['sold_units'] for r in rows); revenue=sum(r['sold_revenue'] for r in rows)
        recent_avg=statistics.mean(r['sold_units'] for r in recent) if recent else None
        prior_avg=statistics.mean(r['sold_units'] for r in prior) if prior else None
        product={k:first.get(k) for k in ('product_name','brand_name','category_name','package_type','net_weight','uom')}
        product.update(product_id=pid,weeks_available=count,soldout_weeks=sells,near_sellout_weeks=near,sellout_rate=round(sells/count,4),coverage_rate=round(count/len(weeks),4),latest_sellout_streak=current,longest_sellout_streak=longest,latest_week_state=latest_state,anomaly_count=anomaly_count,weighted_sell_through=round(weighted_sell_through(rows),4),recent_4_week_sell_through=round(weighted_sell_through(recent),4),total_allocated_units=total_allocated,total_sold_units=total_sold,total_unsold_units=sum(r['unsold_units'] for r in rows),total_sold_revenue=round(revenue,2),total_order_count=sum(r['order_count'] for r in rows),median_weekly_allocated=median,median_weekly_sold=statistics.median(r['sold_units'] for r in rows),p75_weekly_sold=round(percentile([r['sold_units'] for r in rows],.75),1),average_weekly_sold=round(total_sold/count,1),realized_revenue_per_unit=round(revenue/total_sold,2) if total_sold else 0,recent_units_trend_pct=round((recent_avg-prior_avg)/prior_avg,4) if recent_avg is not None and prior_avg else None,signal=signal,volume_adjustment_pct=0,recommended_weekly_allocation=None,price_signal=price,rationale=rationale,recommendation='Manual supply review' if sells>=3 and not anomaly_count else 'Monitor; no automatic change',history=[[r[k] for k in HISTORY_COLUMNS] for r in rows])
        products.append(product)
    products.sort(key=lambda p:(-p['soldout_weeks'],-p['sellout_rate'],-p['total_sold_units']))
    summary={'week_count':len(weeks),'period_from':weeks[0]['period_from'] if weeks else None,'period_to':weeks[-1]['period_to'] if weeks else None,'product_count':len(products),'recurring_sellout_count':sum(p['soldout_weeks']>=3 for p in products),'chronic_sellout_count':sum(p['signal']=='Chronic sellout' for p in products),'fast_mover_count':sum(p['signal'] in ('Consistent fast mover','Emerging shortage') for p in products),'slow_mover_count':sum(p['signal']=='Slow mover' for p in products),'excluded_rows':dict(excluded),'source_row_count':source_row_count,'eligible_product_weeks':sum(p['weeks_available'] for p in products),'exact_sellout_occurrences':sum(p['soldout_weeks'] for p in products)}
    for k in ('allocated_units','sold_units','unsold_units','sold_revenue'): summary['total_'+k]=round(sum(w['eligible_'+k] for w in weeks),2)
    summary['weighted_sell_through']=round(summary['total_sold_units']/summary['total_allocated_units'],4) if summary['total_allocated_units'] else 0
    summary['recurring_with_comparable_history_count']=sum(p['soldout_weeks']>=3 and p['weeks_available']>=4 and p['median_weekly_allocated']>=25 and not p['anomaly_count'] for p in products)
    return {'schema_version':'2026-10-18-a','source':{'url':API_URL,'generated_at':generated,'state_code':api.get('state_code'),'timezone':'America/Los_Angeles','sold_order_statuses':api.get('sold_order_statuses',[]),'data_status':'Historical completed weekly allocations','period_note':'Sunday-Saturday allocation reports. Latest period and coverage follow the source.','sales_note':'Sold units include source order statuses, including pending and submitted. They are wholesale allocation order demand, not confirmed consumer retail sales.','limitations':['Weekly totals do not establish day or time of sellout, hours unavailable, or repeated stockouts within a week.','Missing product weeks are not assumed to have zero demand.','Allocation sizes change; sales do not measure unmet demand or lost revenue.']},'criteria':{'exact_sellout':'Positive allocation; sold equals allocated; unsold equals zero; no quantity or source consistency anomalies.','near_sellout':'At least 90% sell-through, including exact sellouts; no anomalies.','recurring_sellout':'Exact sellout in at least 3 offered weeks.','minimum_history_weeks':4,'minimum_median_weekly_allocation':25,'merchandise_exclusion_rules':['Brand starts with Non Marijuana Products (case insensitive)','Category contains Accessories & Merch (case insensitive)','Exact category: Phat Panda Neck Gaiter/Face Covering','Exact category: Vape Carry Case'],'frequency_denominator':'Completed weeks with positive finite allocations after sample and merchandise exclusions.','excluded':'Unlimited/zero allocations, samples, non-marijuana merchandise, missing identity, incomplete periods.','recommendations':'Manual review only. No numeric price, allocation or lost-sales forecast.'},'history_columns':HISTORY_COLUMNS,'summary':summary,'weeks':weeks,'products':products,'excluded_product_rows':excluded_rows,'quality':{'anomaly_counts':dict(quality_counts),'anomaly_rows':anomaly_rows,'renamed_product_count':sum(len(n)>1 for n in names.values()),'missing_calendar_weeks_note':'Product absence is treated as not offered, not as a zero-sale or zero-stock observation.'}}

def fetch_api():
    request=urllib.request.Request(API_URL,headers={'User-Agent':'sellout-intelligence/1.0'})
    with urllib.request.urlopen(request,timeout=90) as response: return json.load(response)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-file',type=Path,help='Reuse an already fetched source snapshot without another request')
    args=parser.parse_args()
    api=json.loads(args.source_file.read_text(encoding='utf-8')) if args.source_file else fetch_api()
    dataset=build_dataset(api)
    (ROOT/'data').mkdir(exist_ok=True)
    (ROOT/'data'/'source.json').write_text(json.dumps(api,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    (ROOT/'data'/'allocation_sell_through.json').write_text(json.dumps(dataset,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    print(json.dumps(dataset['summary'],indent=2))

if __name__=='__main__': main()
