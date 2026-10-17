"""Real mixed API journeys on the owned S7 stack; no production data resets."""
import argparse
import base64
import concurrent.futures as cf
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {'catalog': 500, 'catalog_filtered': 500, 'detail': 300,
          'activity_info': 500, 'orders': 1000, 'me': 1000,
          'register': 1000, 'login': 1000, 'captcha_image': 500,
          'captcha_accessible': 500, 'token': 500, 'buy': 500,
          'buy_replay': 500, 'order_status': 1000, 'pay': 1000, 'pay_replay': 1000}


def quantile(values, p):
    return round(sorted(values)[math.ceil(len(values)*p/100)-1], 3) if values else None


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['route']].append(row)
    return {name: {'count': len(items),
                   'statuses': dict(Counter(str(x['status']) for x in items)),
                   'p50': quantile([x['ms'] for x in items], 50),
                   'p95': quantile([x['ms'] for x in items], 95),
                   'p99': quantile([x['ms'] for x in items], 99)}
            for name, items in sorted(groups.items())}


def accessible_answer(text):
    match = re.fullmatch(r'请计算 (\d{2}) 加 (\d{2})，并输入得数。', text)
    if not match:
        raise ValueError('Unknown accessible challenge format')
    return str(sum(map(int, match.groups())))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class Run:
    def __init__(self, smoke=False):
        from stack_client import activity, call, clean, dc, login, redis, sql, wait
        self.activity, self.call, self.clean, self.dc = activity, call, clean, dc
        self.login_admin, self.redis, self.sql, self.wait = login, redis, sql, wait
        self.smoke = smoke
        self.duration = 120 if smoke else 1800
        self.user_count = 4 if smoke else 64
        self.expiring = 0 if smoke else 16
        self.registrations = 2 if smoke else 8
        self.run_id = uuid.uuid4().hex[:12]
        self.password = secrets.token_hex(18)
        self.lock = threading.Lock()
        self.rows, self.journeys, self.live, self.errors = [], [], [], []
        self.closed_seen = {}
        self.start = None
        self.phase = 'setup'
        self.report = {'stage': 'S19', 'date': datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),
                       'platform': sys.platform, 'runId': self.run_id, 'complete': False,
                       'smokeOnly': smoke, 'passed': False,
                       'apiP95TargetsMs': LIMITS,
                       'profile': {'durationSeconds': self.duration, 'backgroundReadQps': 15,
                                   'journeys': self.user_count, 'naturalExpiryOrders': self.expiring,
                                   'realRegistrations': self.registrations,
                                   'preseededBcryptAccounts': self.user_count-self.registrations,
                                   'paymentTtlMs': 900000, 'activities': 3},
                       'scope': 'Same-host WSL API profile, not browser/CDN or production capacity. '
                                '15 read requests/s plus 64 paced full journeys over 30 minutes; '
                                'not 15 complete journeys/s. Java auth limits unchanged. '
                                'Image challenge answer digests privately set; accessible questions solved normally. '
                                'Real captcha/token endpoints and production 60s proof lifetime. '
                                'First 16 orders expire naturally at 15 minutes; remaining 48 use MOCK payment.'}

    def request(self, route, method, path, body=None, token=None, expected=200):
        started = time.monotonic()
        try:
            status, result = self.call(method, path, body, token)
        except (OSError, TimeoutError):
            status, result = 0, {}
        row = {'phase': self.phase, 'route': route, 'status': status, 'ms': (time.monotonic()-started)*1000,
               'offset': started-self.start if self.start is not None else None}
        with self.lock:
            self.rows.append(row)
        if expected is not None and status != expected:
            raise RuntimeError(f'{route}: expected {expected}, got {status}')
        if route == 'orders' and status == 200:
            with self.lock:
                for order in result['items']:
                    if order['orderState']=='CLOSED':
                        self.closed_seen.setdefault(order['orderId'], time.monotonic())
        return status, result

    def prepare(self, user, campaign, image=False):
        a, sku, _goods = campaign
        token = user['token']
        mode = 'image' if image else 'accessible'
        _, challenge = self.request('captcha_'+mode, 'GET',
            f'/api/seckill/captcha?activityId={a}&skuId={sku}&mode={mode}', token=token)
        assert int(challenge['expiresAtMs'])-int(time.time()*1000) <= 60000
        if image:
            assert base64.b64decode(challenge['imageDataUrl'].split(',', 1)[1]).startswith(b'\x89PNG\r\n\x1a\n')
            key = f'seckill:{{{a}:{sku}}}:challenge:'+challenge['captchaId']
            proof = json.loads(self.redis('GET', key))
            proof['answerDigest'] = hashlib.sha256(b'123456').hexdigest()
            self.redis('SET', key, json.dumps(proof), 'KEEPTTL')
            answer = '123456'
        else:
            answer = accessible_answer(challenge['challengeText'])
        request_id = str(uuid.uuid4())
        _, proof = self.request('token', 'POST', '/api/seckill/token',
            {'activityId': a, 'skuId': sku, 'requestId': request_id,
             'captchaId': challenge['captchaId'], 'captchaAnswer': answer}, token)
        return {'activityId': a, 'skuId': sku, 'requestId': request_id,
                'activityToken': proof['activityToken'], 'captchaToken': proof['captchaToken']}

    def find_order(self, body, token, started):
        path = ('/api/order/status?activityId='+body['activityId']+'&skuId='+body['skuId']
                +'&requestId='+body['requestId'])
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            _, result = self.request('order_status', 'GET', path, token=token)
            if result.get('orderId'):
                return result, (time.monotonic()-started)*1000
            time.sleep(.2)
        raise RuntimeError('Durable order not observed within 180s')

    def pay(self, order_id, token, replay=True):
        body = {'orderId': order_id, 'idempotencyKey': str(uuid.uuid4())}
        _, first = self.request('pay', 'POST', '/api/order/pay', body, token)
        if replay:
            _, again = self.request('pay_replay', 'POST', '/api/order/pay', body, token)
            assert first == again, 'Payment replay changed response'

    def journey(self, index):
        try:
            name = f's19_{self.run_id}_{index}'
            if index < self.registrations:
                self.request('register', 'POST', '/api/auth/register',
                             {'username': name, 'password': self.password}, expected=201)
            _, auth = self.request('login', 'POST', '/api/auth/login',
                                 {'username': name, 'password': self.password})
            user = {'token': auth['token'], 'userId': auth['userId']}
            with self.lock:
                self.live.append(user)
            body = self.prepare(user, self.campaigns[index % 3], image=index % 2 == 0)
            started = time.monotonic()
            _, accepted = self.request('buy', 'POST', '/api/seckill/buy', body, user['token'], 202)
            if index % 8 == 0:
                _, replay = self.request('buy_replay', 'POST', '/api/seckill/buy', body, user['token'])
                assert replay['reservationId'] == accepted['reservationId']
            order, latency = self.find_order(body, user['token'], started)
            expiry_mono = time.monotonic() + (int(order['expiresAtMs'])
                - (time.time()*1000+self.mysql_offset_ms))/1000
            must_expire = index < self.expiring
            if not must_expire:
                self.pay(order['orderId'], user['token'])
            with self.lock:
                self.journeys.append({'index': index, 'orderId': order['orderId'],
                    'activityId': body['activityId'], 'durableMs': latency,
                    'mustExpire': must_expire, 'expiryMono': expiry_mono,
                    'expiresAtMs': int(order['expiresAtMs'])})
        except Exception as error:
            with self.lock:
                self.errors.append({'journeyIndex': index, 'error': type(error).__name__,
                                    'message': str(error)[:180]})

    def background(self, index):
        campaign = self.campaigns[index % 3]
        with self.lock:
            token = self.live[(index//6) % len(self.live)]['token'] if self.live else None
        options = [('catalog', '/api/goods/catalog?page=0&size=12'),
                   ('catalog_filtered', '/api/goods/catalog?sort=low&maxPriceFen=10000&size=12'),
                   ('detail', '/api/goods/'+campaign[2]),
                   ('activity_info', f'/api/seckill/info?activityId={campaign[0]}&skuId={campaign[1]}'),
                   ('orders', '/api/orders'), ('me', '/api/auth/me')]
        route, path = options[index % len(options)]
        if token is None and route in ('orders', 'me'):
            route, path = options[3]
        try:
            self.request(route, 'GET', path, token=token)
        except Exception as error:
            with self.lock:
                self.errors.append({'backgroundIndex': index, 'error': type(error).__name__,
                                    'message': str(error)[:180]})

    def snapshot(self):
        with self.lock:
            rows, journeys, errors = list(self.rows), list(self.journeys), list(self.errors)
            closed_seen = dict(self.closed_seen)
        mixed_rows = [x for x in rows if x['phase']=='mixed']
        closed_lags = [max(0,(closed_seen[x['orderId']]-x['expiryMono'])*1000)
                       for x in journeys if x['mustExpire'] and x['orderId'] in closed_seen]
        self.report.update({'api': aggregate(rows), 'mixedApi': aggregate(mixed_rows),
            'completedJourneys': len(journeys),
            'durableObservedCount': len(journeys),
            'naturalClosedObserved': len(closed_lags),
            'expiryToClosedObservedMs': {f'p{p}':quantile(closed_lags,p) for p in (50,95,99)},
            'errors': errors, 'durableOrderMs': {f'p{p}': quantile([x['durableMs'] for x in journeys], p)
                                               for p in (50, 95, 99)},
            'submittedReadRequests': sum(x['route'] in ('catalog','catalog_filtered','detail',
                                                       'activity_info','orders','me') for x in mixed_rows)})
        # Private checkpoint deliberately contains no credentials, proofs or passwords.
        atomic_json(ROOT/'build/wsl/s19-progress.json', self.report)

    def setup(self):
        self.admin = self.login_admin()
        before = time.time()*1000
        now = int(self.sql('SELECT CAST(UNIX_TIMESTAMP(NOW(3))*1000 AS UNSIGNED)'))
        self.mysql_offset_ms = now - (before+time.time()*1000)/2
        self.report['mysqlClockOffsetMs'] = self.mysql_offset_ms
        self.campaigns = []
        for i in range(3):
            a, sku = self.activity(self.admin, 64, f'S19-{self.run_id}-{i}')
            goods = self.sql(f'SELECT goods_id FROM skus WHERE id={int(sku)}')
            self.campaigns.append((a, sku, goods))
        # One genuine registration produces a server-side bcrypt hash; only
        # additional owned fixture accounts reuse it. All sessions use real login.
        seed = 's19_seed_'+self.run_id
        status, _ = self.call('POST', '/api/auth/register', {'username': seed, 'password': self.password})
        assert status == 201, f'Seed registration failed: {status}'
        encoded = self.sql(f"SELECT password_hash FROM users WHERE username='{seed}'")
        assert re.fullmatch(r'\$2[aby]\$10\$[./A-Za-z0-9]{53}', encoded)
        values = ','.join(f"('s19_{self.run_id}_{i}','{encoded}',{int(time.time()*1000)})"
                          for i in range(self.registrations, self.user_count))
        if values:
            self.sql('INSERT INTO users(username,password_hash,created_at_ms) VALUES '+values)
        self.report['activityIds'] = [a for a, _, _ in self.campaigns]
        self.report['datasetBefore'] = self.sql('SELECT (SELECT COUNT(*) FROM orders),'
            "(SELECT COUNT(*) FROM outbox_events WHERE status='PENDING'),"
            "(SELECT COUNT(*) FROM orders WHERE status='PENDING_PAYMENT' AND "
            'expires_at_ms<=CAST(UNIX_TIMESTAMP(NOW(3))*1000 AS UNSIGNED))').split('\t')

    def mixed(self):
        self.phase = 'mixed'
        total = self.duration*15
        futures = []
        self.start = time.monotonic()
        next_journey = 0
        with cf.ThreadPoolExecutor(max_workers=64) as pool:
            for index in range(total):
                target = self.start+index/15
                time.sleep(max(0, target-time.monotonic()))
                if next_journey < self.user_count and index >= next_journey*total/self.user_count:
                    futures.append(pool.submit(self.journey, next_journey))
                    next_journey += 1
                futures.append(pool.submit(self.background, index))
                if (index+1) % 900 == 0:
                    self.snapshot()
                    print(json.dumps({'minute': (index+1)/900, 'readsScheduled': index+1,
                        'completedJourneys': self.report['completedJourneys'],
                        'errors': len(self.report['errors'])}), flush=True)
            self.report['submissionSeconds'] = time.monotonic()-self.start
            for future in futures:
                future.result()
        self.snapshot()
        assert not self.errors, 'Mixed request or journey errors; see checkpoint'
        assert len(self.journeys) == self.user_count
        final = []
        for a, _sku, _goods in self.campaigns:
            final.append(self.clean(activity_id=a, limit=100000, timeout=180))
        ids = ','.join(self.report['activityIds'])
        outcomes = dict((s, int(n)) for s, n in (row.split('\t') for row in self.sql(
            f'SELECT status,COUNT(*) FROM orders WHERE activity_id IN ({ids}) GROUP BY status').splitlines()))
        self.report['orderOutcomes'] = outcomes
        self.report['reconciliations'] = final
        self.report['paymentRows'] = int(self.sql('SELECT COUNT(*) FROM payments WHERE order_id IN '
            f'(SELECT id FROM orders WHERE activity_id IN ({ids}))'))
        counts = self.sql('SELECT COUNT(*),COUNT(DISTINCT reservation_id),'
            'COUNT(DISTINCT activity_id,user_id) FROM seckill_requests '
            f'WHERE activity_id IN ({ids})').split('\t')
        self.report['requestCounts'] = dict(zip(('rows','distinctReservations','distinctActivityUsers'),map(int,counts)))
        assert set(self.report['requestCounts'].values()) == {self.user_count}
        expiry = self.sql(f'SELECT COUNT(*) FROM orders WHERE activity_id IN ({ids}) AND '
            'expires_at_ms-created_at_ms<>900000')
        assert expiry == '0', 'Order TTL changed'
        assert outcomes == ({'PAID': self.user_count} if self.smoke else {'CLOSED':16, 'PAID':48}), outcomes
        assert self.report['paymentRows'] == self.user_count-self.expiring
        self.report['mixedGate'] = {
            'noRequestErrors': not self.errors,
            'allJourneysComplete': len(self.journeys) == self.user_count,
            'readLoadComplete': self.report['submittedReadRequests'] == total,
            'readRateWithinOnePercent': total/self.report['submissionSeconds'] >= 15*.99,
            'perApiP95WithinTargets': all(v['p95'] <= LIMITS[k] for k,v in self.report['mixedApi'].items()),
            'durableP95Within3s': self.report['durableOrderMs']['p95'] <= 3000,
            'durableP99Within8s': self.report['durableOrderMs']['p99'] <= 8000,
            'allNaturalClosesObserved': self.report['naturalClosedObserved'] == self.expiring,
            'naturalCloseP99Within60s': self.expiring == 0 or self.report['expiryToClosedObservedMs']['p99'] <= 60000,
            'allInventoryClean': all(x['status']=='CLEAN' for x in final)}

    def burst(self, stock):
        self.phase = 'burst'+str(stock)
        a, sku = self.activity(self.admin, stock, f'S19-burst-{self.run_id}-{stock}')
        goods = self.sql(f'SELECT goods_id FROM skus WHERE id={int(sku)}')
        users = list(self.live)
        plans = [self.prepare(user, (a,sku,goods)) for user in users]
        ready = threading.Barrier(len(users))
        def send(pair):
            user, body = pair
            ready.wait(timeout=30)
            started = time.monotonic()
            code, result = self.request('burst_buy', 'POST', '/api/seckill/buy', body, user['token'], None)
            return user, body, code, result, started
        with cf.ThreadPoolExecutor(max_workers=len(users)) as pool:
            responses = list(pool.map(send, zip(users, plans)))
        statuses = Counter(str(x[2]) for x in responses)
        codes = Counter(x[3].get('code','ACCEPTED') for x in responses)
        orders, durable = [], []
        for user, body, code, result, started in responses:
            if code == 202:
                order, ms = self.find_order(body, user['token'], started)
                orders.append(order['orderId']);durable.append(ms)
                self.pay(order['orderId'], user['token'], replay=False)
        reconciliation = self.clean(activity_id=a, limit=100000, timeout=180)
        expected = min(len(users),stock)
        assert statuses.get('202',0) == expected, statuses
        assert all(x[2]==202 or (x[2]==409 and x[3].get('code')=='SOLD_OUT') for x in responses), codes
        assert len(set(orders)) == expected == reconciliation['orders']
        return {'activityId':a,'users':len(users),'initialStock':stock,
                'httpStatuses':dict(statuses),'businessCodes':dict(codes),
                'accepted':len(orders),'requestToOrderObservationMs':{f'p{p}':quantile(durable,p) for p in (50,95,99)},
                'buyApi':aggregate([x for x in self.rows if x['phase']==self.phase and x['route']=='burst_buy'])['burst_buy'],
                'reconciliation':reconciliation,'passed':True,
                'scope':'Simultaneous buy submissions after real accessible captcha/token preparation. '
                        'Serial result observation is conservative and not a durable latency gate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--report', default='s19-mixed-journeys.json')
    args = parser.parse_args()
    assert sys.platform == 'linux', 'WSL/Linux required'
    assert re.fullmatch(r's19-[a-z0-9-]+\.json', args.report)
    path = ROOT/'tests/reports/wsl'/args.report
    assert not path.exists(), 'Refuse overwriting existing evidence'
    run = Run(args.smoke)
    runtime = {}
    for service in ('seckill','relay','order'):
        info=json.loads(subprocess.check_output(['docker','inspect',f'seckill-mall-s7-{service}-1'],text=True))[0]
        assert info['Config']['Labels']['com.docker.compose.project']=='seckill-mall-s7'
        assert info['State']['Running']
        env=dict(x.split('=',1) for x in info['Config']['Env'] if '=' in x)
        runtime[service]={'imageId':info['Image'], **{k:env[k] for k in
            ('MALL_HTTP_WORKERS','MALL_HTTP_QUEUE','ORDER_PAYMENT_TTL_MS','MALL_MQ_CONSUMER_THREADS') if k in env}}
    assert runtime['order']['ORDER_PAYMENT_TTL_MS']=='900000'
    assert runtime['seckill']['imageId']==runtime['relay']['imageId']
    assert runtime['seckill']['MALL_HTTP_WORKERS']=='32'
    run.report['runtime']=runtime
    run.report['gitBase']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    run.report['sourceSha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
        ('tests/load_s19_journeys.py','src/seckill/service.cpp',
         'src/order/src/main/java/com/seckillmall/order/business/Orders.java',
         'src/order/src/main/java/com/seckillmall/order/business/Cache.java',
         'src/order/src/main/java/com/seckillmall/order/business/Workers.java')}
    run.report['dockerHost']=json.loads(subprocess.check_output(
        ['docker','info','--format','{"cpus":{{.NCPU}},"memoryBytes":{{.MemTotal}}}'],text=True))
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(143)))
    try:
        run.setup()
        run.mixed()
        run.report['bursts']=[run.burst(stock) for stock in ([4] if args.smoke else [64,32])]
        run.report['complete']=True
        run.report['passed']=all(run.report['mixedGate'].values())
    except BaseException as error:
        run.report['failure']={'type':type(error).__name__, 'message':str(error)[:200]}
        raise
    finally:
        run.snapshot()
        atomic_json(path,run.report)
        print(json.dumps({'report':str(path.relative_to(ROOT)), 'passed':run.report['passed'],
                          'complete':run.report['complete']}),flush=True)
    return 0 if run.report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
