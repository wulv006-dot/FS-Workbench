import copy
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from date_policy import validate, subtract, get_capability, PolicyError


class Dates(unittest.TestCase):
    def setUp(self):
        self.cap=dict(contract='fs-data-capability-v2',policy_version='fixture-v1',dataset_id='orders.detail',scope={'site':'266','game':'1327'},timezone='Asia/Shanghai',allowed_modes=['fresh','archive','frozen'],
                      live=dict(enabled=True,earliest_available_date='2020-01-01',earliest_allowed_live_date='2026-08-01',latest_available_end_exclusive='2026-11-01',max_query_span=dict(unit='calendar_months',value=3)),
                      archive=dict(enabled=True,max_query_span=dict(unit='calendar_years',value=1),coverage_intervals=[dict(start='2024-01-01',end_exclusive='2024-03-01')]),
                      frozen=dict(enabled=True,snapshot_id='fixture',snapshot_revision='2',max_query_span=dict(unit='calendar_years',value=1),coverage_intervals=[dict(start='2024-01-01',end_exclusive='2024-03-01')]))
        self.req=dict(policy_version='fixture-v1',dataset_id='orders.detail',scope={'site':'266','game':'1327'},timezone='Asia/Shanghai',mode='fresh',start='2026-08-01',end_exclusive='2026-11-01')

    def test_valid_half_open_and_month_end_leap_semantics(self):
        self.assertEqual(validate(self.cap,self.req),dict(start='2026-08-01',end_exclusive='2026-11-01'))
        self.assertEqual(subtract(date(2024,2,29),dict(unit='calendar_years',value=1)),date(2023,2,28))
        self.assertEqual(subtract(date(2024,5,31),dict(unit='calendar_months',value=3)),date(2024,2,29))
        self.assertNotEqual(subtract(date(2024,3,1),dict(unit='calendar_years',value=1)),subtract(date(2024,3,1),dict(unit='days',value=365)))

    def test_old_single_day_missing_future_reverse_timezone_scope_policy_rejected(self):
        changes=[dict(start='2020-01-01',end_exclusive='2020-01-02'),dict(start=None),dict(end_exclusive='2026-11-02'),dict(start='2026-11-02'),dict(timezone='UTC'),dict(scope={'site':'other'}),dict(policy_version='old')]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(PolicyError): validate(self.cap,dict(self.req,**change))

    def test_unknown_source_never_enables_live(self):
        self.cap['live']['earliest_available_date']=None
        with self.assertRaisesRegex(PolicyError,'range_not_available'):validate(self.cap,self.req)

    def test_archive_frozen_and_gaps_never_fall_back_to_live(self):
        req=dict(self.req,mode='archive',start='2024-01-01',end_exclusive='2024-03-01')
        validate(self.cap,req)
        with self.assertRaisesRegex(PolicyError,'range_not_available'):validate(self.cap,dict(req,end_exclusive='2024-03-02'))
        with self.assertRaisesRegex(PolicyError,'missing_history'):validate(self.cap,dict(req,mode='frozen'))
        validate(self.cap,dict(req,mode='frozen',snapshot_id='fixture',snapshot_revision='2'))

    def test_ninety_days_is_not_three_calendar_months_and_not_clamped(self):
        self.cap['live'].update(earliest_allowed_live_date='2026-02-01',latest_available_end_exclusive='2026-05-01')
        req=dict(self.req,start='2026-01-31',end_exclusive='2026-05-01')
        before=copy.deepcopy(req)
        with self.assertRaises(PolicyError):validate(self.cap,req)
        self.assertEqual(req,before)

    def test_no_capability_enumeration_before_trusted_grant(self):
        def forbidden(*args):self.fail('unauthorized capability resolver called')
        with self.assertRaisesRegex(PolicyError,'permission_denied'):
            get_capability('fixture','orders.detail',self.req['scope'],'fresh',authorize=lambda *args:False,resolve=forbidden)


if __name__=='__main__':unittest.main()
