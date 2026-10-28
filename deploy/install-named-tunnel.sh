#!/usr/bin/env bash
# Run on the development machine after `cloudflared tunnel login` completes.
set -euo pipefail
cd "$HOME/prediction-market-dashboard"
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
import json,uuid
rows=json.loads(Path('/tmp/pmi-tunnel-list.json').read_text())
if len(rows)!=1:
    raise RuntimeError('Expected one prediction-market-test tunnel')
tunnel_id=str(uuid.UUID(rows[0]['id']))
credentials=Path.home()/'.cloudflared'/f'{tunnel_id}.json'
if not credentials.exists():
    raise RuntimeError('The named tunnel has no local connector credentials')
credentials.chmod(0o600)
config={'tunnel':tunnel_id,'credentials-file':str(credentials),'protocol':'http2',
        'ingress':[{'hostname':'predict-test.projext-echo.xyz','service':'http://127.0.0.1:18000'},
                   {'service':'http_status:404'}]}
Path('deploy/tunnel.yml').write_text(json.dumps(config,indent=2)+'\n')
print('Tunnel:',tunnel_id)
PY
cloudflared tunnel --config deploy/tunnel.yml ingress validate
cloudflared tunnel route dns prediction-market-test predict-test.projext-echo.xyz
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
