"""演示续场回归：检查库存上限、保留活动及失败后不盲目重试。"""
import importlib.util
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('renew_demo', Path(__file__).parents[1] / 'scripts/renew-demo.py')
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RenewalTest(TestCase):
    def run_rows(self, rows, failure=False):
        db = MagicMock()
        cursor = db.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = rows
        calls = []
        def api(path, body, token=None):
            calls.append((path, body))
            if path.endswith('/login'):
                return {'token': 'private'}
            if path.endswith('/activate'):
                if failure:
                    raise RuntimeError('activation failed')
                return {}
            return {'activityId': '123'}
        with patch.object(module, 'connect', return_value=db), patch.object(module, 'call', side_effect=api), patch.dict(module.os.environ, {'MALL_ADMIN_USERNAME': 'admin', 'MALL_ADMIN_PASSWORD': 'test-only'}), patch.object(module.time, 'time', return_value=1800000000):
            if failure:
                with self.assertRaises(RuntimeError):
                    module.main()
            else:
                module.main()
        self.assertIn('NOT EXISTS', cursor.execute.call_args.args[0])
        return calls

    def test_no_expired_sessions_does_not_login(self):
        self.assertEqual([], self.run_rows([]))

    def test_allocates_only_remaining_stock_and_uses_runtime_clock(self):
        calls = self.run_rows([(1, 20, 89900), (2, 3, 79900), (3, 0, 39900)])
        created = [body for path, body in calls if path == '/api/admin/activities']
        self.assertEqual(['10', '3'], [body['stock'] for body in created])
        self.assertEqual('1800604800000', created[0]['endsAtMs'])
        self.assertEqual(2, sum(path.endswith('/activate') for path, body in calls))

    def test_activation_failure_stops_without_duplicate_allocation(self):
        calls = self.run_rows([(1, 20, 89900), (2, 20, 79900)], failure=True)
        self.assertEqual(1, sum(path == '/api/admin/activities' for path, body in calls))


if __name__ == '__main__':
    main()
