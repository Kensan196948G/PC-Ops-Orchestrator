"""Integration test for PC-Ops Orchestrator API."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

app = create_app('testing')
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                username='admin',
                password_hash=hash_password('admin'),
                role='admin',
            )
            db.session.add(admin)
            db.session.commit()


def request(method, path, token=None, data=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = json.dumps(data) if data else None
    return client.open(path, method=method, headers=headers, data=body)


def test_login():
    r = request('POST', '/api/auth/login', data={'username': 'admin', 'password': 'admin'})
    assert r.status_code == 200, f'Login failed: {r.status_code} {r.data}'
    data = json.loads(r.data)
    assert 'token' in data
    print(f'  [PASS] Login: token={data["token"][:20]}...')
    return data['token']


def test_dashboard_stats(token):
    r = request('GET', '/api/dashboard/stats', token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f'  [PASS] Dashboard stats: {json.dumps(data)}')


def test_agent_collect():
    body = {
        'pc_name': 'PC-TEST-001',
        'domain': 'company.local',
        'os_version': 'Windows 11 Pro',
        'os_architecture': '64-bit',
        'cpu_name': 'Intel Core i7-12700H',
        'cpu_cores': 14,
        'cpu_logical_processors': 20,
        'memory_total_gb': 32.0,
        'memory_available_gb': 18.5,
        'disk_total_gb': 512.0,
        'disk_free_gb': 256.0,
        'ip_address': '192.168.1.100',
        'agent_version': '1.0.0',
        'cpu_usage': 23.5,
        'uptime_days': 5.2,
        'pending_reboot': False,
    }
    r = request('POST', '/api/collect', token='default-agent-key', data=body)
    assert r.status_code == 200, f'Collect failed: {r.status_code} {r.data}'
    data = json.loads(r.data)
    assert data['message'] == 'ok'
    assert data['pc_id'] > 0
    print(f'  [PASS] Agent collect: pc_id={data["pc_id"]}, score={data["health_score"]}')


def test_pc_list(token):
    r = request('GET', '/api/pcs', token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data['total'] >= 1
    assert len(data['pcs']) >= 1
    print(f'  [PASS] PC list: {data["total"]} PCs, first={data["pcs"][0]["pc_name"]}')


def test_pc_detail(token):
    r = request('GET', '/api/pcs/1', token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data['pc']['pc_name'] == 'PC-TEST-001'
    print(f'  [PASS] PC detail: {data["pc"]["pc_name"]}')


def test_create_task(token):
    body = {'task_type': 'cleanup', 'pc_name': 'PC-TEST-001', 'priority': 1}
    r = request('POST', '/api/tasks', token=token, data=body)
    assert r.status_code == 201, f'Task create failed: {r.status_code} {r.data}'
    data = json.loads(r.data)
    assert data['task']['status'] == 'pending'
    print(f'  [PASS] Create task: id={data["task"]["id"]}, type={data["task"]["task_type"]}')
    return data['task']['id']


def test_task_list(token):
    r = request('GET', '/api/tasks', token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data['total'] >= 1
    print(f'  [PASS] Task list: {data["total"]} tasks')


def test_agent_submit_result():
    body = {'task_id': 1, 'status': 'completed', 'result': {'cleaned': True}}
    r = request('POST', '/api/result', token='default-agent-key', data=body)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f'  [PASS] Submit result: {data["message"]}')


def test_webui_pages(token):
    pages = [
        ('/', 'Dashboard'),
        ('/pcs', 'PC List'),
        ('/tasks', 'Task Management'),
    ]
    for path, name in pages:
        headers = {'Authorization': f'Bearer {token}'}
        r = client.get(path, headers=headers)
        assert r.status_code == 200, f'{name} failed: {r.status_code}'
        print(f'  [PASS] WebUI {name}: {r.status_code}')


def test_health_distribution(token):
    r = request('GET', '/api/dashboard/health-distribution', token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f'  [PASS] Health distribution: {json.dumps(data)}')


def test_os_breakdown(token):
    r = request('GET', '/api/dashboard/os-breakdown', token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f'  [PASS] OS breakdown: {json.dumps(data)}')


def run_all():
    print('=== PC-Ops Orchestrator API Tests ===\n')
    setup_module()
    print('[Setup] Database initialized')

    token = test_login()
    test_dashboard_stats(token)
    test_agent_collect()
    test_pc_list(token)
    test_pc_detail(token)
    task_id = test_create_task(token)
    test_task_list(token)
    test_agent_submit_result()
    test_health_distribution(token)
    test_os_breakdown(token)
    test_webui_pages(token)

    print('\n=== All tests PASSED ===')


if __name__ == '__main__':
    run_all()
