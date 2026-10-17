"""Read-only S19 resource/expiry sample; run alongside the owned test profile."""
import json,sys,subprocess
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from stack_client import sql
p=ROOT/'build/wsl/s19-progress.json'
d=json.loads(p.read_text())
ids=','.join(str(int(x)) for x in d['activityIds'])
metrics=sql("SELECT (SELECT COUNT(*) FROM orders WHERE status='PENDING_PAYMENT' AND expires_at_ms<=CAST(UNIX_TIMESTAMP(NOW(3))*1000 AS UNSIGNED)),(SELECT COUNT(*) FROM outbox_events WHERE status='PENDING')").split('\t')
statuses=sql(f"SELECT status,COUNT(*) FROM orders WHERE activity_id IN ({ids}) GROUP BY status")
stats=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}',*['seckill-mall-s7-'+s+'-1' for s in ('seckill','relay','order','redis','mysql','broker')]],capture_output=True,text=True,timeout=15,check=True)
row={'at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),'activityIds':d['activityIds'],'globalExpiredPending':int(metrics[0]),'globalOutboxPending':int(metrics[1]),'ownOrderStatuses':dict((s,int(n)) for s,n in (x.split('\t') for x in statuses.splitlines())),'resourceSamples':[json.loads(x) for x in stats.stdout.splitlines()],'readOnly':True}
p=ROOT/'tests/reports/wsl/s19-runtime-samples.json';rows=json.loads(p.read_text()) if p.exists() else [];rows.append(row);p.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in row.items() if k!='resourceSamples'}))
