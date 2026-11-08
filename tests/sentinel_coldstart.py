"""Cold restart and controlled failback for the dedicated Sentinel lab."""
import json
import os
import subprocess
import time
import uuid

from sentinel_lab import ADDRESSES, NODES, PROJECT, call, current_master, docker, redis, wait_for

SENTINELS = ('sentinel-1', 'sentinel-2', 'sentinel-3')
ENV = dict(os.environ, MALL_SUBNET='172.30.93.0/24', MALL_GATEWAY_IP='172.30.93.250',
           MALL_WEB_PORT='18993', ORDER_TRUSTED_PROXY_REGEX='172[.]30[.]93[.]250',
           MALL_ADMIN_PASSWORD='sentinel-lab-only-test-password')
COMPOSE = ['docker', 'compose', '-p', PROJECT, '--env-file', 'deploy/.env.stack',
           '-f', 'deploy/compose.yml', '-f', 'deploy/compose.sentinel.yml']


def compose(*args):
    subprocess.run(COMPOSE + list(args), env=ENV, check=True, timeout=240)


def converged(primary):
    address = next(ip for ip, node in ADDRESSES.items() if node == primary)
    for sentinel in SENTINELS:
        if redis(sentinel, 'SENTINEL', 'get-master-addr-by-name', 'mall-redis', port=26379).splitlines() != [address, '6379']:
            return False
    for node in NODES:
        info = dict(line.split(':', 1) for line in redis(node, 'INFO', 'replication').splitlines() if ':' in line)
        if node == primary:
            if info.get('role') != 'master' or info.get('connected_slaves') != '2':
                return False
        elif (info.get('role'), info.get('master_host'), info.get('master_link_status')) != ('slave', address, 'up'):
            return False
    return True


def check_clients(token):
    return (call('GET', '/health/order')[0] == 200
            and call('GET', '/health/seckill')[0] == 200
            and call('GET', '/api/auth/me', token=token)[0] == 200)


def main():
    assert docker('port', PROJECT + '-gateway-1', '80/tcp') == '127.0.0.1:18993'
    primary = current_master()
    assert primary in NODES and primary != 'redis', 'Run the failover drill before cold restart'
    wait_for(lambda: converged(primary))
    credentials = {'username': 'cold_' + uuid.uuid4().hex[:12], 'password': 'Sentinel-lab-test-only-2026'}
    assert call('POST', '/api/auth/register', credentials)[0] == 201
    code, session = call('POST', '/api/auth/login', credentials)
    assert code == 200
    token = session['token']
    probe = 'sentinel-cold-probe:' + uuid.uuid4().hex
    assert redis(primary, 'SET', probe, 'persisted', 'EX', '600') == 'OK'
    for node in NODES:
        wait_for(lambda: redis(node, 'GET', probe) == 'persisted')

    started = time.monotonic()
    compose('stop')
    compose('up', '-d', '--no-deps', '--no-build', *SENTINELS)
    wait_for(lambda: current_master() == primary)
    # 启动上次主节点后再启动副本，避免启动先后差异触发意外选主。
    compose('up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '60', primary)
    compose('up', '-d', '--no-build', '--wait', '--wait-timeout', '180', 'gateway', 'relay', 'redis-replica', 'redis-replica-2')
    wait_for(lambda: converged(primary))
    wait_for(lambda: check_clients(token))
    assert redis(primary, 'GET', probe) == 'persisted'
    cold_seconds = round(time.monotonic() - started, 2)

    # Lab only. The short TILT period works around recurring pauses on this host.
    excluded = next(node for node in NODES if node not in (primary, 'redis'))
    priority = redis(excluded, 'CONFIG', 'GET', 'replica-priority').splitlines()[1]
    try:
        for sentinel in SENTINELS:
            assert redis(sentinel, 'SENTINEL', 'DEBUG', 'TILT-PERIOD', '3000', port=26379) == 'OK'
        for sentinel in SENTINELS:
            wait_for(lambda: 'sentinel_tilt:0' in redis(sentinel, 'INFO', 'sentinel', port=26379))
        assert redis(excluded, 'CONFIG', 'SET', 'replica-priority', '0') == 'OK'
        started = time.monotonic()
        assert redis('sentinel-1', 'SENTINEL', 'FAILOVER', 'mall-redis', port=26379) == 'OK'
        wait_for(lambda: converged('redis'), 90)
        wait_for(lambda: check_clients(token))
        assert redis('redis', 'GET', probe) == 'persisted'
        assert redis('redis', 'DEL', probe) == '1'
        failback_seconds = round(time.monotonic() - started, 2)
    finally:
        redis(excluded, 'CONFIG', 'SET', 'replica-priority', priority)
        for sentinel in SENTINELS:
            redis(sentinel, 'SENTINEL', 'DEBUG', 'TILT-PERIOD', '30000', port=26379)

    print(json.dumps({'passed': True, 'primaryBeforeAndAfterColdStart': primary,
                      'coldStartSecondsIncludingStop': cold_seconds,
                      'failbackPrimary': 'redis', 'failbackSeconds': failback_seconds,
                      'verified': ['all three Sentinels agree', 'one primary and two connected replicas',
                                   'persisted probe retained', 'original login session retained',
                                   'C++ and Java readiness'],
                      'failbackLabTiltPeriodMs': 3000}, indent=2))


if __name__ == '__main__':
    main()
