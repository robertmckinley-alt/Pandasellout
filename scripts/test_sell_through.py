import unittest
from refresh_sell_through import build_dataset, classify, exclusion, row_anomalies, weighted_sell_through

def product(pid='p', allocated=100, sold=100, **extra):
    return dict(product_id=pid,product_name=pid,brand_name='Brand',category_name='Flower',allocated_units=allocated,sold_units=sold,unsold_units=allocated-sold,sell_through=round(sold/allocated,4) if allocated else 0,sold_revenue=sold*2,order_count=1,**extra)

def dataset(rows):
    return build_dataset({'generated_at':'2026-10-18T18:00:00Z','allocations':[{'inventory_allocation_id':str(i),'period_from':f'2026-09-{i*7+1:02d}','period_to':f'2026-09-{i*7+7:02d}','products':r} for i,r in enumerate(rows)]})

class RulesTest(unittest.TestCase):
    def test_frequency_uses_offered_weeks_and_missing_breaks_streak(self):
        result=dataset([[product()],[product()],[product('other')],[product()]])
        p=next(p for p in result['products'] if p['product_id']=='p')
        self.assertEqual((p['soldout_weeks'],p['weeks_available'],p['sellout_rate']),(3,3,1))
        self.assertEqual(p['coverage_rate'],.75)
        self.assertEqual(p['latest_sellout_streak'],1)
        self.assertEqual(p['longest_sellout_streak'],2)

    def test_not_offered_latest_does_not_extend_streak(self):
        p=next(p for p in dataset([[product()],[product('other')]])['products'] if p['product_id']=='p')
        self.assertEqual(p['latest_week_state'],'not_offered')
        self.assertEqual(p['latest_sellout_streak'],0)

    def test_zero_unsold_with_unreconciled_sale_is_not_sellout(self):
        p=product(sold=50);p['unsold_units']=0
        result=dataset([[p]])
        self.assertEqual(result['products'][0]['soldout_weeks'],0)
        self.assertEqual(result['products'][0]['signal'],'Data review')
        self.assertIn('quantity_reconciliation',row_anomalies(p))

    def test_overselling_is_flagged_not_exhaustion(self):
        p=product(sold=101)
        self.assertIn('oversold',row_anomalies(p))
        self.assertEqual(dataset([[p]])['products'][0]['soldout_weeks'],0)

    def test_missing_unsold_is_not_assumed_zero(self):
        p=product();del p['unsold_units']
        self.assertEqual(dataset([[p]])['products'][0]['soldout_weeks'],0)

    def test_weighted_rate_uses_units_not_mean_percentages(self):
        self.assertEqual(weighted_sell_through([product(allocated=100,sold=100),product(allocated=900,sold=0)]),.1)

    def test_explicit_samples_and_zero_allocation_are_excluded(self):
        self.assertEqual(exclusion(product(type='sample')),'trade_samples')
        self.assertEqual(exclusion(product(allocated=0,sold=0)),'zero_or_unlimited')

    def test_accessory_categories_are_excluded_regardless_of_brand(self):
        for category in ('Phat Panda Neck Gaiter/Face Covering','Vape Carry Case'):
            p=product();p['category_name']=category
            self.assertEqual(exclusion(p),'non_merchandise')

    def test_topicals_and_beverage_cases_remain_eligible(self):
        for category in ('Panda Balm','Topical Creams','Sungaze - Case - 4 Packs','Sungaze - Case - Singles'):
            p=product();p['category_name']=category
            self.assertIsNone(exclusion(p))

    def test_no_numeric_recommendations_even_for_repeated_sellouts(self):
        p=dataset([[product()] for _ in range(4)])['products'][0]
        self.assertEqual(p['signal'],'Chronic sellout')
        self.assertEqual(p['volume_adjustment_pct'],0)
        self.assertIsNone(p['recommended_weekly_allocation'])

    def test_missing_recent_data_does_not_become_fake_negative_trend(self):
        p=next(p for p in dataset([[product()],[product('other')]])['products'] if p['product_id']=='p')
        self.assertIsNone(p['recent_units_trend_pct'])

    def test_duplicate_product_week_does_not_inflate_frequency(self):
        result=dataset([[product(),product()]])
        self.assertEqual(result['products'][0]['weeks_available'],1)
        self.assertEqual(result['quality']['anomaly_counts']['duplicate_product_week'],1)

    def test_partial_week_is_excluded_from_completed_history(self):
        result=build_dataset({'generated_at':'2026-10-18T18:00:00Z','allocations':[{'inventory_allocation_id':'future','period_from':'2026-10-18','period_to':'2026-10-24','products':[product()]}]})
        self.assertFalse(result['weeks'][0]['is_completed'])
        self.assertEqual(result['summary']['product_count'],0)
        self.assertEqual(result['summary']['excluded_rows']['incomplete_week'],1)

    def test_source_and_eligible_totals_are_separate(self):
        result=build_dataset({'generated_at':'2026-10-18T18:00:00Z','allocations':[{'inventory_allocation_id':'w','period_from':'2026-10-04','period_to':'2026-10-10','allocated_units':1000,'sold_units':200,'products':[product(),product('sample',type='sample')]}]})
        self.assertEqual(result['weeks'][0]['allocated_units'],1000)
        self.assertEqual(result['weeks'][0]['eligible_allocated_units'],100)
        self.assertEqual(result['summary']['source_row_count'],2)
        self.assertEqual(result['summary']['eligible_product_weeks'],1)

if __name__=='__main__': unittest.main()
