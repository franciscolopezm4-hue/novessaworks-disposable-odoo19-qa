"""Zero-spend, manually leased, disposable official-container QA environment."""
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT = Path('/dev/shm/nwqa-' + os.environ['GITHUB_RUN_ID'])
CONTAINERS = ['nwqa-tunnel', 'nwqa-odoo', 'nwqa-postgres']

def run(args, **kwargs):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        safe = result.stderr.decode(errors='replace')
        for key in ['POSTGRES_PASSWORD', 'NWQA_WEB_PASSWORD', 'NWQA_GITHUB_TOKEN']:
            value = os.environ.get(key)
            if value:
                safe = safe.replace(value, '[redacted]')
        safe = re.sub(r'[A-Za-z0-9_-]{40,}', '[redacted]', safe)
        print('NWQA_COMMAND_DIAGNOSTIC: ' + safe[-1800:], flush=True)
        raise RuntimeError('Command failed: ' + args[0] + ' ' + args[1])
    return result.stdout

def cleanup():
    metadata = ROOT / 'deployment-id'
    if metadata.exists():
        deployment = metadata.read_text().strip()
        try:
            github('/deployments/' + deployment + '/statuses', 'POST', {'state': 'inactive'})
            github('/deployments/' + deployment, 'DELETE')
            print('NWQA_ENCRYPTED_TRANSFER_REMOVED', flush=True)
        except Exception:
            print('NWQA_TRANSFER_CLEANUP_PENDING', flush=True)
    for name in CONTAINERS:
        subprocess.run(['docker', 'rm', '-f', '-v', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    subprocess.run(['docker', 'network', 'rm', 'nwqa-net'], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    if ROOT.parent != Path('/dev/shm') or not ROOT.name.startswith('nwqa-'):
        raise RuntimeError('Unexpected cleanup path')
    if ROOT.exists():
        shutil.rmtree(ROOT)
    print('NWQA_CLEANUP: containers/anonymous volumes/ephemeral credential files removed')

def github(route, method, payload=None):
    url = 'https://api.github.com/repos/' + os.environ['GITHUB_REPOSITORY'] + route
    headers = {'Authorization': 'Bearer ' + os.environ['NWQA_GITHUB_TOKEN'],
               'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10'}
    data = None if payload is None else json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers,
         method=method), timeout=20) as response:
        return None if response.status == 204 else json.load(response)

def fetch_json(url, key=None, payload=None):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
        headers['X-Odoo-Database'] = 'NWQA'
    data = None if payload is None else json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=20) as res:
        return json.load(res)

def provision():
    if os.environ.get('GITHUB_REPOSITORY') != 'franciscolopezm4-hue/novessaworks-disposable-odoo19-qa':
        raise RuntimeError('Harness restricted to the authorized public repository')
    prefix = os.environ['NWQA_PREFIX']
    if not re.fullmatch(r'NWQA-\d{8}-\d{4}', prefix):
        raise RuntimeError('Invalid synthetic prefix')
    public_pem = base64.b64decode(os.environ['NWQA_PUBLIC_KEY_B64'], validate=True)
    if b'-----BEGIN PUBLIC KEY-----' not in public_pem or b'PRIVATE' in public_pem:
        raise RuntimeError('Only a public key is accepted')
    ROOT.mkdir(mode=0o700)
    shared = ROOT / 'shared'
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (ROOT / 'public.pem').write_bytes(public_pem)
    public_desc = run(['openssl', 'pkey', '-pubin', '-in', str(ROOT/'public.pem'), '-text', '-noout'])
    if b'4096 bit' not in public_desc:
        raise RuntimeError('RSA-4096 required')
    db_password, web_password, master_password = [secrets.token_urlsafe(32) for _ in range(3)]
    for value in [db_password, web_password, master_password]:
        print('::add-mask::' + value, flush=True)
    os.environ.update(POSTGRES_PASSWORD=db_password, PASSWORD=db_password, NWQA_WEB_PASSWORD=web_password)
    odoo_env = ['-e', 'HOST=nwqa-postgres', '-e', 'PORT=5432', '-e', 'USER=odoo', '-e', 'PASSWORD']
    config = ('[options]\ndb_host = nwqa-postgres\ndb_port = 5432\ndb_user = odoo\n'
        'db_password = ' + db_password + '\ndb_name = NWQA\ndbfilter = ^NWQA$\n'
        'admin_passwd = ' + master_password + '\nlist_db = False\nproxy_mode = True\n'
        'http_port = 8069\nmax_cron_threads = 0\nlog_level = warn\n')
    (shared / 'odoo.conf').write_text(config)
    (shared / 'odoo.conf').chmod(0o644)
    shutil.copy('seed_odoo.py', shared/'seed_odoo.py')
    for image in ['postgres:16', 'odoo:19.0', 'cloudflare/cloudflared:latest']:
        run(['docker', 'pull', image])
        digest = run(['docker', 'image', 'inspect', '--format', '{{index .RepoDigests 0}}', image]).decode().strip()
        print('NWQA_IMAGE: ' + digest, flush=True)
    run(['docker', 'network', 'create', 'nwqa-net'])
    run(['docker', 'run', '-d', '--name', 'nwqa-postgres', '--network', 'nwqa-net',
        '-e', 'POSTGRES_USER=odoo', '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB=postgres',
        'postgres:16'])
    for _ in range(45):
        probe = subprocess.run(['docker', 'exec', 'nwqa-postgres', 'pg_isready', '-U', 'odoo'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError('PostgreSQL readiness timed out')
    volume = str(shared) + ':/nwqa'
    run(['docker', 'run', '--rm', '--network', 'nwqa-net', '-v', volume, *odoo_env, 'odoo:19.0',
        'odoo', '-c', '/nwqa/odoo.conf', '-i', 'base,contacts,crm,project',
        '--without-demo=all', '--stop-after-init'])
    # New database, credential rotation and synthetic fixtures before any public exposure.
    with open(shared/'seed_odoo.py', 'rb') as seed:
        run(['docker', 'run', '--rm', '-i', '--network', 'nwqa-net', '-v', volume,
            '-e', 'NWQA_PREFIX', '-e', 'NWQA_WEB_PASSWORD', *odoo_env, 'odoo:19.0',
            'odoo', 'shell', '-c', '/nwqa/odoo.conf', '--no-http'], stdin=seed)
    credentials = json.loads((shared/'credential.json').read_text())
    print('::add-mask::' + credentials['apiKey'], flush=True)
    run(['docker', 'run', '-d', '--name', 'nwqa-odoo', '--network', 'nwqa-net',
        '-p', '127.0.0.1:18079:8069', '-v', volume, *odoo_env, 'odoo:19.0',
        'odoo', '-c', '/nwqa/odoo.conf'])
    for _ in range(45):
        try:
            version = fetch_json('http://127.0.0.1:18079/web/version')
            if version.get('version_info', [0])[0] != 19:
                raise RuntimeError('Expected Odoo 19')
            fetch_json('http://127.0.0.1:18079/json/2/res.partner/search_read',
                       credentials['apiKey'], {'domain': [['name', 'ilike', prefix]],
                       'fields': ['id', 'name'], 'limit': 1})
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(2)
    else:
        raise RuntimeError('Odoo JSON-2 readiness timed out')
    run(['docker', 'run', '-d', '--name', 'nwqa-tunnel', '--network', 'host',
        'cloudflare/cloudflared:latest', 'tunnel', '--no-autoupdate', '--url',
        'http://127.0.0.1:18079'])
    for _ in range(60):
        logs = run(['docker', 'logs', 'nwqa-tunnel']).decode(errors='replace')
        # cloudflared writes to stderr; docker forwards it there.
        result = subprocess.run(['docker', 'logs', 'nwqa-tunnel'], capture_output=True)
        logs += result.stderr.decode(errors='replace')
        match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', logs)
        if match:
            url = match.group(0)
            try:
                public_version = fetch_json(url + '/web/version')
                records = fetch_json(url + '/json/2/res.partner/search_read', credentials['apiKey'],
                    {'domain': [['name', 'ilike', prefix]], 'fields': ['id', 'name'], 'limit': 1})
                if public_version.get('version_info', [0])[0] == 19 and len(records) == 1:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
        time.sleep(2)
    else:
        raise RuntimeError('Temporary public JSON-2 endpoint readiness timed out')
    credentials['url'] = url
    credentials['runId'] = os.environ['GITHUB_RUN_ID']
    # OAEP maximum payload for RSA-4096/SHA256 is 446 bytes; omit fixture IDs from transfer.
    transfer = {k:v for k,v in credentials.items() if k not in ['fixtures', 'prefix', 'runId']}
    encrypted = run(['openssl', 'pkeyutl', '-encrypt', '-pubin', '-inkey', str(ROOT/'public.pem'),
        '-pkeyopt', 'rsa_padding_mode:oaep', '-pkeyopt', 'rsa_oaep_md:sha256'],
        input=json.dumps(transfer, separators=(',', ':')).encode())
    # GitHub job logs are unavailable through REST during a live job. Transfer ciphertext
    # as ephemeral deployment metadata, never as plaintext in logs or artifacts.
    deployment = github('/deployments', 'POST', {'ref': os.environ['GITHUB_SHA'],
        'task': 'NWQA-disposable-test', 'auto_merge': False, 'required_contexts': [],
        'environment': prefix, 'transient_environment': True, 'production_environment': False,
        'payload': {'encryptedCredential': base64.b64encode(encrypted).decode(),
                    'url': url, 'prefix': prefix, 'runId': os.environ['GITHUB_RUN_ID']}})
    (ROOT/'deployment-id').write_text(str(deployment['id']))
    print('NWQA_ENCRYPTED_TRANSFER_READY: ' + str(deployment['id']), flush=True)
    print('NWQA_READY: ' + json.dumps({'url': url, 'version': version['version'],
        'json2': True, 'prefix': prefix, 'fixtureIds': credentials['fixtures'],
        'disposable': True, 'leaseMinutes': 100, 'costUSD': 0}), flush=True)
    (shared/'credential.json').unlink()
    # Cancellation ends the lease early; the always() step independently cleans up.
    time.sleep(100*60)

if __name__ == '__main__':
    if '--cleanup' in sys.argv:
        cleanup()
    else:
        try:
            provision()
        except Exception as error:
            print('NWQA_FAILED: ' + type(error).__name__, flush=True)
            raise SystemExit(1)
        finally:
            cleanup()
