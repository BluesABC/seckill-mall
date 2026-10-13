"""Generate a local stack env without overwriting existing credentials."""
import argparse,secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--path',default=str(ROOT/'deploy/.env.stack'));args=parser.parse_args()
path=Path(args.path).resolve()
if path.exists():
    print('Existing env preserved: '+str(path))
    raise SystemExit(0)
path.parent.mkdir(parents=True,exist_ok=True)
values={'MYSQL_ROOT_PASSWORD':secrets.token_hex(24),'MYSQL_PASSWORD':secrets.token_hex(24),'MALL_ADMIN_USERNAME':'admin','MALL_ADMIN_PASSWORD':secrets.token_hex(24),'MALL_WEB_PORT':'18080','MALL_SUBNET':'172.30.85.0/24','MALL_GATEWAY_IP':'172.30.85.10','ORDER_TRUSTED_PROXY_REGEX':r'172\.30\.85\.10'}
with path.open('x',encoding='utf-8',newline='\n') as f:
    for key,value in values.items():f.write(key+'='+value+'\n')
path.chmod(0o600);print('Generated local credentials at '+str(path)+'; do not commit this file')
