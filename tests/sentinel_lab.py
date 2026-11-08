"""Owned Sentinel lab drill. Kills only the current primary of the named lab."""
import hashlib
import http.client
import json
import subprocess
import time
import uuid
from urllib.parse import urlencode

from shipping_fixture import prepare_shipping

PROJECT = 'seckill-mall-sentinel-lab'
NODES = ('redis', 'redis-replica', 'redis-replica-2')
ADDRESSES = dict(zip(('172.30.93.201', '172.30.93.202', '172.30.93.203'), NODES))


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, timeout=35).strip()


def redis(node, *args, port=6379):
    container = PROJECT + '-' + node + '-1'
    return docker('exec', container, 'redis-cli', '-p', str(port), '--raw', *args)


def current_master():
    target = redis('sentinel-1', 'SENTINEL', 'get-master-addr-by-name', 'mall-redis', port=26379).splitlines()
    if len(target) == 2:
        return ADDRESSES.get(target[0])
    return None


def call(method, path, body=None, token=None):
    connection = http.client.HTTPConnection('127.0.0.1', 18993, timeout=5)
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def wait_for(check, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
        time.sleep(.5)
    raise AssertionError('Sentinel drill timed out')


def main():
    old = current_master()
    assert old in NODES
    container = PROJECT + '-' + old + '-1'
    label = docker('inspect', '--format', '{{index .Config.Labels "com.docker.compose.project"}}', container)
    assert label == PROJECT
    wait_for(lambda: redis('sentinel-1', 'SENTINEL', 'CKQUORUM', 'mall-redis', port=26379).startswith('OK '))
    for sentinel in ('sentinel-1', 'sentinel-2', 'sentinel-3'):
        wait_for(lambda: 'sentinel_tilt:0' in redis(sentinel, 'INFO', 'sentinel', port=26379), 60)
    wait_for(lambda: 'connected_slaves:2' in redis(old, 'INFO', 'replication'))
    username = 'sentinel_' + uuid.uuid4().hex[:12]
    credentials = {'username': username, 'password': 'Sentinel-lab-test-only-2026'}
    assert call('POST', '/api/auth/register', credentials)[0] == 201
    code, session = call('POST', '/api/auth/login', credentials)
    assert code == 200
    token = session['token']
    user = session['userId']
    activities = call('GET', '/api/activities')[1]['items']
    active = [row for row in activities if row['status'] == 'ACTIVE' and int(row['endsAtMs']) > time.time()*1000]
    assert len(active) >= 2, 'Seed this lab before running the drill'

    def reserve(activity, primary):
        a, sku, request = activity['activityId'], activity['skuId'], str(uuid.uuid4())
        prepare_shipping(call, token, a, sku, request)
        query = urlencode({'activityId': a, 'skuId': sku})
        code, challenge = call('GET', '/api/seckill/captcha?' + query, token=token)
        assert code == 200, challenge
        key = f'seckill:{{{a}:{sku}}}:challenge:' + challenge['captchaId']
        proof = json.loads(redis(primary, 'GET', key))
        proof['answerDigest'] = hashlib.sha256(b'123456').hexdigest()
        assert redis(primary, 'SET', key, json.dumps(proof), 'KEEPTTL') == 'OK'
        params = {'activityId': a, 'skuId': sku, 'requestId': request}
        code, proof = call('POST', '/api/seckill/token',
            dict(params, captchaId=challenge['captchaId'], captchaAnswer='123456'), token)
        assert code == 200, proof
        body = dict(params, activityToken=proof['activityToken'], captchaToken=proof['captchaToken'])
        code, accepted = call('POST', '/api/seckill/buy', body, token)
        assert code == 202, accepted
        return body, f'seckill:{{{a}:{sku}}}:ledger', '/api/order/status?' + urlencode(params)

    def order(path):
        def read():
            status, result = call('GET', path, token=token)
            return result if status == 200 and result.get('orderId') else None
        return wait_for(read, 90)

    a0, s0 = active[0]['activityId'], active[0]['skuId']
    a1, s1 = active[1]['activityId'], active[1]['skuId']
    first_stock = int(redis(old, 'HGET', f'seckill:{{{a0}:{s0}}}:ledger', 'stock'))
    second_stock = int(redis(old, 'HGET', f'seckill:{{{a1}:{s1}}}:ledger', 'stock'))
    assert min(first_stock, second_stock) > 0
    relay = PROJECT + '-relay-1'
    docker('stop', relay)
    killed = False
    try:
        body, ledger, path = reserve(active[0], old)
        field = f'req:{user}:{body["requestId"]}'
        for node in NODES:
            if node != old:
                wait_for(lambda: redis(node, 'HEXISTS', ledger, field) == '1')
        started = time.monotonic()
        docker('kill', container)
        killed = True
        new = wait_for(lambda: (name if (name := current_master()) and name != old else None))
        wait_for(lambda: call('GET', '/health/order')[0] == call('GET', '/health/seckill')[0] == 200)
        wait_for(lambda: call('GET', '/api/auth/me', token=token)[0] == 200)
        elapsed = round(time.monotonic() - started, 2)
        assert call('POST', '/api/seckill/buy', body, token)[0] == 200
        docker('start', relay)
        first = order(path)
        assert first['orderState'] == 'PENDING_PAYMENT'
        _, second_ledger, second_path = reserve(active[1], new)
        second = order(second_path)
        assert first['orderId'] != second['orderId']
        assert int(redis(new, 'HGET', ledger, 'stock')) == first_stock - 1
        assert int(redis(new, 'HGET', second_ledger, 'stock')) == second_stock - 1
        assert call('POST', '/api/shop/seckill/' + second['orderId'] + '/cancel', {}, token)[0] == 200
        wait_for(lambda: int(redis(new, 'HGET', second_ledger, 'stock')) == second_stock)
        print(json.dumps({'passed': True, 'oldPrimary': old, 'newPrimary': new,
                          'clientRecoverySeconds': elapsed, 'verified': [
                              'replicated accepted reservation before kill', 'C++ and Java readiness',
                              'session retained', 'request replay', 'relay resumes queued reservation',
                              'new order after failover', 'both stocks decremented once', 'cancel restores stock']}, indent=2))
    finally:
        docker('start', relay)
        if killed:
            docker('start', container)


if __name__ == '__main__':
    main()
