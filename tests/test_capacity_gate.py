"""Evidence-gate regressions: short runs and forged summary flags cannot pass."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_capacity_gate import evaluate


def evidence():
    return {'submitted': 27000, 'durationSeconds': 1800, 'offeredQps': 15,
            'observedSubmissionQps': 15, 'accepted': 27000, 'reserved': 27000,
            'observedSubmissionSeconds': 1800,
            'persisted': 27000, 'httpStatusCounts': {'202': 27000}, 'server5xxCount': 0,
            'buyApiLatencyMsAcceptedOnly': {'p50': 50, 'p95': 100, 'p99': 200},
            'buyApiLatencyMsAllResponses': {'p50': 50, 'p95': 100, 'p99': 200},
            'requestToDurableOrderMs': {'p50': 500, 'p95': 1000, 'p99': 2000},
            'requestToDurableObservedCount': 27000,
            'stageTelemetry': {'reservations': 27000, 'malformedStageLines': 0,
                'stageCounts': {'relay_publish': 27000, 'consumer_received': 27000, 'committed': 27000}},
            'reconciliation': {'status': 'CLEAN', 'orders': 27000, 'alerts': [],
                'ledgers': [{'initial': 27000, 'dbAvailable': 0, 'redisAvailable': 0,
                             'held': 27000, 'activeOrders': 27000, 'inTransit': 0, 'pendingSend': 0}]},
            'outboxStatus': {'PUBLISHED': 27000}, 'timeToInventoryCleanAfterResponsesMs': 5000,
            'fiveMinuteWindows': [{'startSeconds': n, 'submitted': 4500, 'accepted': 4500, 'server5xx': 0,
                                  'transportUnknown': 0} for n in range(0, 1800, 300)]}


class CapacityGateTests(unittest.TestCase):
    def test_clean_label_cannot_hide_missing_or_inconsistent_inventory(self):
        for field, value in [('initial', 27001), ('redisAvailable', 1), ('held', 26999),
                             ('inTransit', 1), ('pendingSend', 1), ('dbAvailable', -1)]:
            with self.subTest(field=field):
                row = evidence(); row['reconciliation']['ledgers'][0][field] = value
                self.assertFalse(evaluate(row)['checks']['inventoryLedgerConservesStock'])
        row = evidence(); del row['reconciliation']['ledgers']
        self.assertFalse(evaluate(row)['passed'])

    def test_valid_evidence_passes_without_summary_flags(self):
        self.assertTrue(evaluate(evidence())['passed'])

    def test_short_missing_and_slow_runs_cannot_claim_success(self):
        for field, value in [('durationSeconds', 60), ('observedSubmissionQps', 14),
                             ('observedSubmissionSeconds', 900),
                             ('submitted', 26999), ('requestToDurableObservedCount', 100),
                             ('reconciliation', {'status': 'IN_FLIGHT'}),
                             ('outboxStatus', {'PENDING': 1}),
                             ('timeToInventoryCleanAfterResponsesMs', 601000),
                             ('requestToDurableOrderMs', {'p50': 500, 'p95': 3100, 'p99': 9000}),
                             ('buyApiLatencyMsAcceptedOnly', {'p50': 50, 'p95': None, 'p99': 200})]:
            with self.subTest(field=field):
                row = evidence(); row[field] = value
                row['temporaryGateResults'] = {'passed': True}
                self.assertFalse(evaluate(row)['passed'])

    def test_concentrated_errors_fail_five_minute_budget(self):
        row = evidence()
        row['httpStatusCounts'] = {'202': 26995, '503': 5}
        row['accepted'] = 26995; row['server5xxCount'] = 5
        row['fiveMinuteWindows'][0]['server5xx'] = 5
        row['fiveMinuteWindows'][0]['accepted'] = 4495
        result = evaluate(row)
        self.assertTrue(result['checks']['server5xxAtMost0_1Percent'])
        self.assertFalse(result['checks']['fiveMinuteWindowsSustainLoadAndErrorBudget'])

    def test_wrong_counts_missing_stages_and_nan_fail(self):
        for mutate in [lambda r: r['httpStatusCounts'].update({'202': 26999}),
                       lambda r: r['stageTelemetry']['stageCounts'].update({'committed': 26999}),
                       lambda r: r.update({'observedSubmissionQps': float('nan')}),
                       lambda r: r.update({'accepted': True}),
                       lambda r: r['fiveMinuteWindows'].pop()]:
            row = copy.deepcopy(evidence()); mutate(row)
            self.assertFalse(evaluate(row)['passed'])

    def test_window_summary_cannot_hide_a_count_mismatch(self):
        row = evidence()
        row['httpStatusCounts'] = {'202': 26999, '503': 1}
        row['accepted'] = 26999; row['server5xxCount'] = 1
        row['fiveMinuteWindows'][0]['accepted'] = 4499
        self.assertFalse(evaluate(row)['checks']['windowCountsMatchHttpTotals'])

    def test_cli_fails_closed_on_malformed_or_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            for content in ['not-json', '{}', '[]', '{"stageTelemetry":null}']:
                path.write_text(content, encoding='utf-8')
                result = subprocess.run([sys.executable, str(ROOT/'scripts/check_capacity_gate.py'), str(path)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(result.stdout)['passed'])


if __name__ == '__main__':
    unittest.main()
