# 测试职责：突发门禁拒绝溢出、伪造延迟和成功请求被拒绝样本掩盖。
# 具体断言及fixture边界在本文件；通过范围以对应阶段报告为准，不自动代表生产上线。
"""Reject corrupted or incomplete evidence using a real S20 report fixture."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('burst_gate',ROOT/'scripts/check_burst_gate.py')
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class EvidenceChecks(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'tests/reports/wsl/s20-fixed-64-01.json').read_text(encoding='utf-8'))

    def reject(self, data):
        data['passed']=True
        self.assertFalse(gate.evaluate(data)['passed'])

    def test_real_evidence(self):
        self.assertTrue(gate.evaluate(self.data)['passed'])

    def test_short_or_incomplete(self):
        for key in ('rounds','complete'):
            data=copy.deepcopy(self.data)
            data[key]=data['rounds'][:1] if key=='rounds' else False
            self.reject(data)

    def test_overflow(self):
        self.data['rounds'][1]['tcpDelta']['ListenOverflows']=1
        self.reject(self.data)

    def test_forged_latency_summary(self):
        self.data['rounds'][0]['rows'][-5:]=[dict(row,httpMs=1500) for row in self.data['rounds'][0]['rows'][-5:]]
        self.reject(self.data)

    def test_stock_and_count(self):
        for key in ('held','dbAvailable','initial'):
            data=copy.deepcopy(self.data)
            data['rounds'][0]['reconciliation']['ledgers'][0][key]+=1
            self.reject(data)

    def test_unexpected_status_or_nan(self):
        for field,value in (('status',503),('httpMs',float('nan')),('upstreamConnectMs',None)):
            data=copy.deepcopy(self.data)
            data['rounds'][0]['rows'][0][field]=value
            self.reject(data)

    def test_missing_timing_row(self):
        self.data['rounds'][0]['rows'].pop()
        self.reject(self.data)

    def test_sold_out_does_not_hide_slow_accepts(self):
        data=json.loads((ROOT/'tests/reports/wsl/s20-fixed-32-01.json').read_text(encoding='utf-8'))
        accepted=[row for row in data['rounds'][0]['rows'] if row['status']==202]
        for row in accepted[-3:]:
            row['httpMs']=1500
        self.reject(data)


if __name__=='__main__':
    unittest.main()
