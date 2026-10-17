#!/usr/bin/env python3
"""Independently evaluate the local v0.1 sustained buy-path gate from evidence."""
import argparse
import json
import math
from pathlib import Path


def evaluate(report):
    checks = {}

    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def count(value):
        return number(value) and value >= 0 and int(value) == value

    def check(name, condition):
        checks[name] = bool(condition)

    total = report.get('submitted')
    duration = report.get('durationSeconds')
    qps = report.get('offeredQps')
    observed = report.get('observedSubmissionQps')
    elapsed = report.get('observedSubmissionSeconds')
    accepted = report.get('accepted')
    reserved = report.get('reserved')
    persisted = report.get('persisted')
    statuses = report.get('httpStatusCounts', {})
    status_valid = (isinstance(statuses, dict) and bool(statuses)
                    and all(isinstance(k, str) and k.isdigit() and count(v)
                            for k, v in statuses.items()))
    total_valid = count(total) and total > 0
    check('durationAtLeast30Minutes', number(duration) and duration >= 1800)
    check('targetAtLeast15Qps', number(qps) and qps >= 15)
    check('plannedLoadComplete', total_valid and number(qps) and number(duration)
          and total >= math.ceil(qps * duration))
    check('observedRateAtLeast99PercentOfTarget', number(observed) and number(qps)
          and observed >= qps * .99)
    actual_rate = total / elapsed if total_valid and number(elapsed) and elapsed > 0 else None
    check('observedRateMatchesMeasuredTime', actual_rate is not None and number(observed)
          and abs(actual_rate - observed) <= .002)
    # Arrival timestamps span N-1 intervals for N requests, so include the last
    # scheduled interval (plus 20ms measurement/rounding tolerance).
    check('measuredRunCoversPlannedDuration', number(elapsed) and number(duration)
          and number(qps) and qps > 0 and elapsed + 1/qps + .02 >= duration)
    check('httpCountConservation', status_valid and total_valid and sum(statuses.values()) == total)
    check('acceptedCountMatchesHttp202', count(accepted) and status_valid
          and accepted == statuses.get('202', 0))
    check('acceptanceAtLeast99_5Percent', count(accepted) and total_valid
          and accepted / total >= .995)
    errors = sum(v for k, v in statuses.items() if int(k) >= 500) if status_valid else None
    check('server5xxAtMost0_1Percent', errors is not None and total_valid and errors / total <= .001)
    check('server5xxCountConsistent', errors is not None and count(report.get('server5xxCount'))
          and errors == report.get('server5xxCount'))
    check('noTransportUnknown', status_valid and statuses.get('0', 0) == 0)

    for field, thresholds in [('buyApiLatencyMsAcceptedOnly', {'p95': 500}),
                               ('buyApiLatencyMsAllResponses', {'p95': 500}),
                               ('requestToDurableOrderMs', {'p95': 3000, 'p99': 8000})]:
        metrics = report.get(field, {})
        valid = (isinstance(metrics, dict) and all(number(metrics.get(p)) and metrics[p] >= 0
                                                   for p in ('p50', 'p95', 'p99')))
        check(field + 'CompleteAndOrdered', valid
              and metrics['p50'] <= metrics['p95'] <= metrics['p99'])
        for percentile, bound in thresholds.items():
            check(field + percentile + 'WithinTarget', valid and metrics[percentile] <= bound)

    check('allReservationsPersisted', count(reserved) and count(persisted)
          and count(accepted) and total_valid and accepted <= persisted == reserved <= total)
    coverage = report.get('requestToDurableObservedCount')
    check('durableObservationCoverageAtLeast99_5Percent', count(coverage) and count(persisted)
          and persisted > 0 and persisted * .995 <= coverage <= persisted)
    stages = report.get('stageTelemetry', {})
    stage_counts = stages.get('stageCounts', {}) if isinstance(stages, dict) else {}
    check('stageEvidenceComplete', count(reserved) and count(persisted)
          and stages.get('reservations') == reserved
          and stages.get('malformedStageLines') == 0
          and stage_counts.get('relay_publish') == reserved
          and stage_counts.get('consumer_received') == reserved
          and stage_counts.get('committed') == persisted)
    reconciliation = report.get('reconciliation', {})
    check('inventoryReconciliationClean', isinstance(reconciliation, dict)
          and reconciliation.get('status') == 'CLEAN'
          and reconciliation.get('orders') == persisted
          and reconciliation.get('alerts') == [])
    ledgers = reconciliation.get('ledgers', []) if isinstance(reconciliation, dict) else []
    ledger_valid = isinstance(ledgers, list) and len(ledgers) == 1
    if ledger_valid:
        ledger = ledgers[0]
        fields = ('initial', 'dbAvailable', 'redisAvailable', 'held', 'activeOrders',
                  'inTransit', 'pendingSend')
        ledger_valid = (isinstance(ledger, dict) and all(count(ledger.get(k)) for k in fields)
                        and ledger['inTransit'] == ledger['pendingSend'] == 0
                        and ledger['held'] == ledger['activeOrders']
                        and ledger['dbAvailable'] == ledger['redisAvailable']
                        and ledger['initial'] == ledger['dbAvailable'] + ledger['activeOrders'])
    check('inventoryLedgerConservesStock', ledger_valid)
    outbox = report.get('outboxStatus', {})
    check('outboxDrained', isinstance(outbox, dict) and bool(outbox)
          and all(k == 'PUBLISHED' and count(v) for k, v in outbox.items())
          and count(persisted) and outbox.get('PUBLISHED', 0) >= persisted)
    cleanup = report.get('timeToInventoryCleanAfterResponsesMs')
    check('inventoryCleanWithin600Seconds', number(cleanup) and 0 <= cleanup <= 600000)

    windows = report.get('fiveMinuteWindows', [])
    valid_windows = isinstance(windows, list) and count(duration) and 1800 <= duration <= 86400
    expected = list(range(0, int(duration), 300)) if valid_windows else []
    valid_windows = valid_windows and len(windows) == len(expected)
    if valid_windows:
        for row, start in zip(windows, expected):
            valid_windows = (valid_windows and isinstance(row, dict)
                             and row.get('startSeconds') == start
                             and count(row.get('submitted')) and row['submitted'] > 0
                             and count(row.get('accepted')) and row['accepted'] <= row['submitted']
                             and count(row.get('server5xx')) and count(row.get('transportUnknown'))
                             and row['transportUnknown'] == 0
                             and row['server5xx'] / row['submitted'] <= .001
                             and number(qps)
                             and row['submitted'] >= min(300, duration - start) * qps * .99)
    check('fiveMinuteWindowsSustainLoadAndErrorBudget', valid_windows and total_valid
          and sum(row['submitted'] for row in windows) == total)
    check('windowCountsMatchHttpTotals', valid_windows and status_valid
          and sum(row['server5xx'] for row in windows) == errors
          and sum(row['transportUnknown'] for row in windows) == statuses.get('0', 0)
          and sum(row['accepted'] for row in windows) == accepted)
    return {'passed': all(checks.values()), 'checks': checks,
            'failedChecks': [name for name, passed in checks.items() if not passed],
            'scope': 'Local v0.1 sustained buy-path gate only; production HA/SLA/payments/a11y remain separate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding='utf-8-sig'))
        if not isinstance(report, dict):
            raise ValueError('report must be an object')
        result = evaluate(report)
    except (OSError, ValueError, TypeError, OverflowError, AttributeError, KeyError) as error:
        result = {'passed': False, 'failedChecks': ['invalidOrMissingEvidence'],
                  'error': type(error).__name__}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
