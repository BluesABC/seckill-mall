"""Crash/restart only the owned S1 Redis container; verify AOF reservation recovery."""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from data import cache
compose=["docker","compose","-p","seckill-mall-s1","--env-file",str(ROOT/"deploy/.env.s1.example"),"-f",str(ROOT/"deploy/compose.infra.yml")]
container=subprocess.check_output(compose+["ps","-q","redis"],text=True).strip()
if not container or "\n" in container: raise RuntimeError("Exactly one owned S1 Redis container required")
labels=json.loads(subprocess.check_output(["docker","inspect",container],text=True))[0]["Config"]["Labels"]
if labels.get("com.docker.compose.project")!="seckill-mall-s1" or labels.get("com.docker.compose.service")!="redis":
    raise RuntimeError("Refusing to restart unrelated container")
client=cache(); key="s1:recovery:"+uuid.uuid4().hex
now=int(time.time()*1000); request=str(uuid.uuid4()); reservation=str(uuid.uuid4())
preload=(ROOT/"src/seckill/lua/preload.lua").read_text(encoding="utf-8")
reserve=(ROOT/"src/seckill/lua/reserve.lua").read_text(encoding="utf-8")
try:
    assert client.eval(preload,1,key,10,now-1000,now+3600000,"ACTIVE",1,1990,1,1)[0]=="INITIALIZED"
    with client.pipeline(transaction=False) as pipe:
        pipe.eval(reserve,1,key,1,request,reservation,1,"recovery-check")
        pipe.execute_command("WAITAOF",1,0,1000)
        result=pipe.execute()
    assert result[0][0]=="RESERVED" and result[1][0]==1
    snapshot=client.hgetall(key)
    subprocess.run(["docker","kill","--signal","KILL",container],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(compose+["up","-d","--wait","--wait-timeout","60","redis"],check=True)
    assert client.hgetall(key)==snapshot
    replay=client.eval(reserve,1,key,1,request,str(uuid.uuid4()),1,"recovery-check")
    assert replay[0]=="REPLAY" and client.hget(key,"stock")=="9"
    report={"platform":sys.platform,"redisCrash":"SIGKILL","aofConfirmed":True,
            "stockQualificationRequestPendingRecovered":True,"replayAfterRestart":True,
            "scope":"single Redis process crash; not disk loss or failover"}
    (ROOT/"tests/reports/wsl/s1-recovery.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report))
finally:
    subprocess.run(compose+["up","-d","--wait","--wait-timeout","60","redis"],check=True)
    client.unlink(key)
