"""为微信状态机探针创建/删除自有数据库；不触碰商城业务库或真实商户配置。"""
import json,os,subprocess,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from data import connect,migrate
if sys.platform!='linux':raise SystemExit('Use WSL/Linux')
name='mall_wx_'+uuid.uuid4().hex
try:
    with connect() as db:
        with db.cursor() as cursor:cursor.execute('CREATE DATABASE `'+name+'` CHARACTER SET utf8mb4')
        db.commit()
    with connect(name) as db:migrate(db)
    cp=str(ROOT/'build/wsl/order-target/test-classes')+':'+str(ROOT/'build/wsl/order-target/classes')+':'+(ROOT/'build/wsl/t060-classpath.txt').read_text().strip()
    result=subprocess.run(['java','-ea','-cp',cp,'com.seckillmall.order.business.WechatDatabaseProbe'],env=dict(os.environ,T060_DB_NAME=name,MALL_PAYMENT_PROVIDER="WECHAT"),capture_output=True,text=True)
    if result.returncode:
        print(result.stdout);print(result.stderr);raise SystemExit(result.returncode)
    report=json.loads(result.stdout.splitlines()[-1]);(ROOT/'tests/reports/wsl/t060-wechat-database.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
finally:
    with connect() as db:
        with db.cursor() as cursor:cursor.execute('DROP DATABASE IF EXISTS `'+name+'`')
        db.commit()
