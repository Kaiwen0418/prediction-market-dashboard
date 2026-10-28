#!/usr/bin/env bash
# Run on the development machine after `cloudflared tunnel login` completes.
set -euo pipefail
cd "$HOME/prediction-market-dashboard"
export PMI_API_HOSTNAME="${PMI_API_HOSTNAME:-predict-test.project-echo.xyz}"
# Cloudflared silently appends the selected zone to out-of-zone hostnames.
# Validate the authenticated zone before any tunnel or DNS mutation.
python3 - <<'PYZONE'
import base64,json,os,re,urllib.request
from pathlib import Path
hostname=os.environ['PMI_API_HOSTNAME']
if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',hostname):
    raise SystemExit('Invalid API hostname')
pem=Path.home().joinpath('.cloudflared/cert.pem').read_text()
encoded=re.search(r'-----BEGIN ARGO TUNNEL TOKEN-----\s*(.*?)\s*-----END ARGO TUNNEL TOKEN-----',pem,re.S).group(1)
cert=json.loads(base64.b64decode(encoded))
if not re.fullmatch('[a-f0-9]{32}',cert['zoneID']):
    raise SystemExit('Invalid authenticated zone ID')
request=urllib.request.Request('https://api.cloudflare.com/client/v4/zones/'+cert['zoneID'],
    headers={'Authorization':'Bearer '+cert['apiToken']})
with urllib.request.urlopen(request,timeout=20) as response:
    zone=json.load(response)['result']['name']
if not hostname.endswith('.'+zone):
    raise SystemExit(f'API hostname {hostname} is outside authenticated zone {zone}; no changes made')
print('Validated API hostname:',hostname,'zone:',zone)
PYZONE
cloudflared tunnel list --name prediction-market-test --output json > /tmp/pmi-tunnel-list.json
existing_id="$(python3 - <<'PY'
import json
with open('/tmp/pmi-tunnel-list.json') as stream:
    tunnels=json.load(stream) or []
print(tunnels[0]['id'] if tunnels else '')
PY
)"
if [ -z "$existing_id" ]; then
  cloudflared tunnel create prediction-market-test
  cloudflared tunnel list --name prediction-market-test --output json > /tmp/pmi-tunnel-list.json
fi
python3 - <<'PY'
from pathlib import Path
import json,uuid,os
rows=json.loads(Path('/tmp/pmi-tunnel-list.json').read_text())
if len(rows)!=1:
    raise RuntimeError('Expected one prediction-market-test tunnel')
tunnel_id=str(uuid.UUID(rows[0]['id']))
credentials=Path.home()/'.cloudflared'/f'{tunnel_id}.json'
if not credentials.exists():
    raise RuntimeError('The named tunnel has no local connector credentials')
credentials.chmod(0o600)
config={'tunnel':tunnel_id,'credentials-file':str(credentials),'protocol':'http2',
        'ingress':[{'hostname':os.environ['PMI_API_HOSTNAME'],'service':'http://127.0.0.1:18000'},
                   {'service':'http_status:404'}]}
Path('deploy/tunnel.yml').write_text(json.dumps(config,indent=2)+'\n')
print('Tunnel:',tunnel_id)
PY
cloudflared tunnel --config deploy/tunnel.yml ingress validate
cloudflared tunnel route dns prediction-market-test "$PMI_API_HOSTNAME"
mkdir -p "$HOME/.config/systemd/user"
cp deploy/pmi-api-named-tunnel.service "$HOME/.config/systemd/user/pmi-api-tunnel.service"
systemctl --user daemon-reload
systemctl --user enable pmi-api-tunnel.service
systemctl --user restart pmi-api-tunnel.service
systemctl --user is-active pmi-api-tunnel.service
python3 - <<'PY'
from pathlib import Path
Path('/tmp/pmi-tunnel-list.json').unlink(missing_ok=True)
PY
