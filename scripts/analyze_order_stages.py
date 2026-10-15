#!/usr/bin/env python3
"""Correlate relay and Java consumer stage logs by reservationId."""
import argparse
import json
import re
import sys
from collections import defaultdict

LINE = re.compile(r"\bevent=seckill_stage\s+(.*)")
PAIR = re.compile(r"([A-Za-z][A-Za-z0-9]*)=([^\s]+)")
FIELDS = ("relayPendingAgeMs", "publishCallMs", "relayToConsumerMs",
          "brokerQueueMs", "relaySendToBrokerMs", "mysqlTransactionMs",
          "reservationAgeMs")


def parse(lines):
    events = defaultdict(dict)
    malformed = 0
    duplicates = 0
    for line in lines:
        match = LINE.search(line)
        if not match:
            continue
        row = dict(PAIR.findall(match.group(1)))
        reservation = row.get("reservationId")
        stage = row.get("stage")
        if not reservation or not stage:
            malformed += 1
            continue
        if stage in events[reservation]:
            # RocketMQ can redeliver a reservation after a transient failure.
            # Keep the first observation for stable latency statistics.
            duplicates += 1
            continue
        events[reservation][stage] = row
    return events, malformed, duplicates


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, int((len(values) - 1) * fraction + 0.999999))]


def summarize(events, malformed, duplicates=0):
    metrics = {key: [] for key in FIELDS}
    counts = defaultdict(int)
    for stages in events.values():
        relay = stages.get("relay_publish", {})
        received = stages.get("consumer_received", {})
        committed = stages.get("order_transaction_committed", {})
        failed = stages.get("order_transaction_failed", {})
        counts["relay_publish"] += bool(relay)
        counts["consumer_received"] += bool(received)
        counts["committed"] += bool(committed)
        counts["failed"] += bool(failed)
        for field in ("relayPendingAgeMs", "publishCallMs"):
            if field in relay:
                metrics[field].append(int(relay[field]))
        for field in ("relayToConsumerMs", "brokerQueueMs", "relaySendToBrokerMs",
                      "reservationAgeMs"):
            if field in received and int(received[field]) >= 0:
                metrics[field].append(int(received[field]))
        txn = committed or failed
        if "mysqlTransactionMs" in txn:
            metrics["mysqlTransactionMs"].append(int(txn["mysqlTransactionMs"]))
    return {
        "reservations": len(events),
        "malformedStageLines": malformed,
        "duplicateStageLines": duplicates,
        "stageCounts": dict(counts),
        "latencyMs": {
            key: {"count": len(values), "p50": percentile(values, .50),
                  "p95": percentile(values, .95), "p99": percentile(values, .99),
                  "max": max(values) if values else None}
            for key, values in metrics.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="*", help="combined Docker relay/order logs; stdin if omitted")
    args = parser.parse_args()
    if args.logs:
        streams = [open(path, encoding="utf-8", errors="replace") for path in args.logs]
        try:
            lines = (line for stream in streams for line in stream)
            result = summarize(*parse(lines))
        finally:
            for stream in streams:
                stream.close()
    else:
        result = summarize(*parse(sys.stdin))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
