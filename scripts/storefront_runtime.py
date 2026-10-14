"""Owned real services for S5 acceptance or an explicitly local showroom.

New database/key namespace/topic each run; cleanup only those owned resources.
No overwrite of existing catalog, activity ledgers or user passwords.
"""
import argparse, hashlib, http.client, json, os, signal, socket, subprocess, sys, time, uuid
from pathlib import Path
import redis
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from data import connect,migrate
sys.path.insert(0,str(ROOT/'tests'))
from test_s4 import call,wait,port

class Runtime:
    def __init__(self):
        self.database='mall_s5_'+uuid.uuid4().hex
        self.prefix='s5_'+uuid.uuid4().hex
        self.topic='mall_s5_'+uuid.uuid4().hex
        self.group='mall_s5_'+uuid.uuid4().hex
        self.java_port=port(); self.cpp_port=port()
        self.web_port=int(os.environ.get('MALL_WEB_PORT','5173'))
        self.processes=[];self.logs=[];self.created=False
        self.password='S5-local-demo-'+uuid.uuid4().hex[:16]
        self.cache=redis.Redis(port=16379,decode_responses=True,socket_timeout=5)
        self.env=dict(os.environ,MALL_DB_NAME=self.database,MALL_DB_USER='root',MALL_DB_PASSWORD='s1-local-root-only',MALL_DB_PORT='13306',MALL_REDIS_PORT='16379',MALL_KEY_PREFIX=self.prefix,MALL_BUSINESS_ENABLED='true',MALL_MQ_TOPIC=self.topic,MALL_MQ_GROUP=self.group,MALL_ADMIN_USERNAME='admin',MALL_ADMIN_PASSWORD=self.password,ORDER_PORT=str(self.java_port),ORDER_JOBS_ENABLED='true',MALL_LUA_DIRECTORY=str(ROOT/'src/seckill/lua'),MALL_HTTP_PORT=str(self.cpp_port),MALL_IP_LIMIT='10000',MALL_USER_LIMIT='10000',MALL_PROOF_LIMIT='10000')
    def start(self,argv,name,cwd=ROOT,env=None):
        log=(ROOT/'build/wsl'/f's5-{name}.log').open('w');self.logs.append(log)
        p=subprocess.Popen(argv,cwd=cwd,env=env or self.env,stdout=log,stderr=subprocess.STDOUT);self.processes.append(p);return p
    def setup(self):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:probe.bind(('127.0.0.1',self.web_port))
            except OSError as error:raise RuntimeError(f'Port {self.web_port} is in use; choose a free MALL_WEB_PORT') from error
        with connect() as db:
            with db.cursor() as cur:cur.execute(f'CREATE DATABASE `{self.database}` CHARACTER SET utf8mb4')
        self.created=True
        with connect(self.database) as db:migrate(db)
        subprocess.run(['docker','exec','seckill-mall-mq-broker-1','sh','mqadmin','updateTopic','-n','namesrv:9876','-b','127.0.0.1:10911','-t',self.topic,'-r','4','-w','4','-a','+message.type=NORMAL'],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','exec','seckill-mall-mq-broker-1','sh','mqadmin','updateSubGroup','-n','namesrv:9876','-b','127.0.0.1:10911','-g',self.group],check=True,stdout=subprocess.DEVNULL)
        java=self.start(['java','-jar',str(ROOT/'build/wsl/order-target/order-service-0.1.0-SNAPSHOT.jar')],'java')
        def ready():
            if java.poll() is not None:raise RuntimeError('Java startup failed; see build/wsl/s5-java.log')
            return call(self.java_port,'GET','/health/ready')[0]==200
        wait(ready,100)
        self.start([str(ROOT/'build/wsl/cpp-s3/src/seckill/seckill_service'),'--serve'],'cpp')
        wait(lambda:call(self.cpp_port,'GET','/health/live')[0]==200)
        code,session=call(self.java_port,'POST','/api/auth/login',body={'username':'admin','password':self.password});assert code==200,session
        self.admin=session['token'];self.items=[]
        products=[('AERO/01 · 轻量跑鞋','工程网布与缓震泡棉概念设计。EU42，白 / 荧光黄；概念鞋款，用于项目演示。','shoe-run-v1.webp','109900','89900','42','跑步','白 / 荧光黄'),('COURT/02 · 实战篮球鞋','立体支撑鞋面与分段外底概念设计。EU42，钴蓝 / 黑；概念鞋款，用于项目演示。','shoe-court-v1.webp','99900','79900','42','篮球','钴蓝 / 黑'),('STREET/03 · 城市休闲鞋','复古轮廓与柔和皮革概念设计。EU42，米白 / 酒红；概念鞋款，用于项目演示。','shoe-street-v1.webp','49900','39900','42','休闲','米白 / 酒红'),('AERO/01 WOMEN · 跑步鞋','轻盈网面，走向下一公里。EU38.5，白 / 荧光黄；概念鞋款，用于项目演示。','shoe-run-v1.webp','69900','59900','38.5','跑步','白 / 荧光黄')]
        now=int(time.time()*1000)
        for title,description,image,price,deal,size,category,colorway in products:
            code,g=call(self.java_port,'POST','/api/admin/goods',self.admin,{'title':title,'description':description,'imageUrl':'/assets/'+image,'priceFen':price,'stock':'30'});assert code==201,g
            code,attrs=call(self.java_port,'PATCH',f'/api/admin/skus/{g["skuId"]}',self.admin,{'sizeEu':size,'category':category,'colorway':colorway});assert code==200,attrs
            code,a=call(self.java_port,'POST','/api/admin/activities',self.admin,{'name':'DROP 01 · 限时发售','skuId':g['skuId'],'stock':'10','priceFen':deal,'startsAtMs':str(now-60000),'endsAtMs':str(now+86400000)});assert code==201,a
            assert call(self.java_port,'POST',f'/api/admin/activities/{a["activityId"]}/activate',self.admin,{'skuId':g['skuId']})[0]==200
            self.items.append(dict(g,**a,title=title,sizeEu=size))
        self.start([str(ROOT/'build/wsl/cpp-s3/src/mq/mall_relay_worker'),'--loop'],'relay')
        viteenv=dict(self.env,MALL_ORDER_ORIGIN=f'http://127.0.0.1:{self.java_port}',MALL_SECKILL_ORIGIN=f'http://127.0.0.1:{self.cpp_port}')
        self.start(['node','node_modules/vite/bin/vite.js','preview'],'web',ROOT/'build/wsl/web',viteenv)
        wait(lambda:call(self.web_port,'GET','/api/goods')[0]==200)
        config={'pid':os.getpid(),'baseUrl':f'http://127.0.0.1:{self.web_port}','webPort':self.web_port,'javaPort':self.java_port,'prefix':self.prefix,'database':self.database,'password':self.password,'items':self.items}
        path=ROOT/'build/wsl/s5-runtime.json';path.write_text(json.dumps(config,ensure_ascii=False));path.chmod(0o600)
        return config
    def cleanup(self):
        for p in reversed(self.processes):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=25)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in self.logs:log.close()
        keys=list(self.cache.scan_iter(match=self.prefix+':*'))
        if keys:self.cache.unlink(*keys)
        if self.created:
            with connect() as db:
                with db.cursor() as cur:cur.execute(f'DROP DATABASE IF EXISTS `{self.database}`')
        (ROOT/'build/wsl/s5-runtime.json').unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--test',action='store_true');parser.add_argument('--stop',action='store_true');args=parser.parse_args()
    if sys.platform!='linux':raise SystemExit('Run in native WSL/Linux')
    if args.stop:
        path=ROOT/'build/wsl/s5-runtime.json'
        if not path.exists():raise SystemExit('No owned showroom running')
        config=json.loads(path.read_text());pid=int(config['pid'])
        process=Path('/proc')/str(pid)
        if pid<=1 or b'storefront_runtime.py' not in (process/'cmdline').read_bytes() or (process/'cwd').resolve()!=ROOT.resolve():raise SystemExit('PID ownership check failed; refusing to stop unrelated process')
        os.kill(pid,signal.SIGTERM);raise SystemExit(0)
    def stop_owned(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop_owned)
    # Dedicated local infrastructure credentials; never production defaults.
    os.environ.setdefault('MALL_DB_USER','root')
    os.environ.setdefault('MALL_DB_PASSWORD','s1-local-root-only')
    runtime=Runtime()
    try:
        runtime.setup()
        if args.test:
            result=subprocess.run(['node',str(ROOT/'tests/browser/s5.mjs')],env=dict(runtime.env,S5_CONFIG=str(ROOT/'build/wsl/s5-runtime.json')),cwd=ROOT)
            if result.returncode:raise SystemExit(result.returncode)
            with connect(runtime.database) as db:
                with db.cursor() as cur:
                    cur.execute('SELECT COUNT(*),COUNT(DISTINCT reservation_id) FROM orders');total,unique=cur.fetchone();assert total==2 and total==unique,(total,unique)
                    cur.execute("SELECT COUNT(*) FROM payments WHERE status='SUCCEEDED'");payments=cur.fetchone()[0];assert payments==1,payments
                    cur.execute("SELECT status,COUNT(*) FROM orders GROUP BY status");states=dict(cur.fetchall());assert states=={'PAID':1,'CLOSED':1},states
                    cur.execute("SELECT s.activity_id,s.sku_id,s.initial_stock,s.available_stock,COALESCE(SUM(CASE WHEN o.status IN ('PAID','PENDING_PAYMENT') THEN o.quantity ELSE 0 END),0) FROM activity_stock s LEFT JOIN orders o ON o.activity_id=s.activity_id AND o.sku_id=s.sku_id GROUP BY s.activity_id,s.sku_id,s.initial_stock,s.available_stock")
                    inventory=[list(map(int,row)) for row in cur.fetchall()]
                    assert all(available>=0 and available+occupied==initial for _,_,initial,available,occupied in inventory),inventory
            result={'orders':total,'uniqueReservations':unique,'successfulMockPayments':payments,'orderStates':states,'inventoryColumns':['activityId','skuId','initial','available','occupied'],'inventory':inventory,'result':'PASS'}
            (ROOT/'tests/reports/wsl/sports-ui/sql.json').write_text(json.dumps(result,indent=2))
            print('PASS S5 SQL: unique orders, real payment records, stock conservation',flush=True)
        else:
            print(f'Showroom http://localhost:{self.web_port}; local admin credentials in build/wsl/s5-runtime.json; Ctrl+C cleans owned DB/cache. Never deploy this root/test configuration.',flush=True)
            while True:
                if any(p.poll() is not None for p in runtime.processes):raise RuntimeError('Showroom service exited')
                time.sleep(1)
    except KeyboardInterrupt:pass
    finally:runtime.cleanup()
