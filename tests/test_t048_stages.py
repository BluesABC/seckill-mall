# 测试职责：发布/消费/事务阶段日志关联及重复去重。
# 具体断言及fixture边界在本文件；通过范围以对应阶段报告为准，不自动代表生产上线。
"""Retry-aware parsing tests for T048 stage telemetry."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_order_stages import parse, summarize  # noqa: E402


class StageTelemetryTests(unittest.TestCase):
    def test_redelivery_is_counted_separately_and_does_not_replace_first_sample(self):
        lines = [
            "event=seckill_stage stage=relay_publish reservationId=r1 relayPendingAgeMs=120",
            "event=seckill_stage stage=relay_publish reservationId=r1 relayPendingAgeMs=900",
            "event=seckill_stage stage=consumer_received reservationId=r1 reservationAgeMs=150",
            "event=seckill_stage stage=order_transaction_committed reservationId=r1 mysqlTransactionMs=30",
            "event=seckill_stage stage=order_transaction_committed reservationId=r1 mysqlTransactionMs=80",
            "event=seckill_stage stage=broken",
        ]
        events, malformed, duplicates = parse(lines)
        result = summarize(events, malformed, duplicates)

        self.assertEqual(result["reservations"], 1)
        self.assertEqual(result["malformedStageLines"], 1)
        self.assertEqual(result["duplicateStageLines"], 2)
        self.assertEqual(result["latencyMs"]["relayPendingAgeMs"]["p50"], 120)
        self.assertEqual(result["latencyMs"]["mysqlTransactionMs"]["p50"], 30)


if __name__ == "__main__":
    unittest.main()
