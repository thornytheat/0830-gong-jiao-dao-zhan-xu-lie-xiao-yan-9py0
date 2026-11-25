"""人工确认点接口与并发语义。"""


def _run(client, sample='clean'):
    return client.post('/api/runs', data={'sample': sample}).json


def test_list_confirmations_starts_empty(client):
    run = _run(client)
    response = client.get(f"/api/runs/{run['id']}/confirmations")
    assert response.status_code == 200 and response.json == {'items': []}


def test_add_confirmation_returns_updated_run(client):
    run = _run(client)
    response = client.post(f"/api/runs/{run['id']}/confirmations",
                           json={'revision': 0, 'case': '0001', 'station': 8, 'second': 25})
    assert response.status_code == 200
    body = response.json
    assert body['revision'] == 1
    assert body['report']['confirmations'][0]['station'] == 8
    listed = client.get(f"/api/runs/{run['id']}/confirmations").json['items']
    assert len(listed) == 1 and listed[0]['case'] == '0001'


def test_conflict_is_stored_and_makes_batch_unreleasable(client):
    run = _run(client)
    client.post(f"/api/runs/{run['id']}/confirmations",
                json={'revision': 0, 'case': '0001', 'station': 7, 'second': 10})
    response = client.post(f"/api/runs/{run['id']}/confirmations",
                           json={'revision': 1, 'case': '0001', 'station': 7, 'second': 20})
    # 冲突确认点正常落库（200），但业务组进入 CONFIRMATION_CONFLICT，整批不可签发。
    assert response.status_code == 200
    body = response.json
    case = next(item for item in body['report']['cases'] if item['case'] == '0001')
    assert case['status'] == 'CONFIRMATION_CONFLICT'
    assert body['report']['balance']['releasable'] is False
    held = client.patch(f"/api/runs/{run['id']}",
                        json={'revision': 2, 'status': 'APPROVED', 'note': '带冲突签发'})
    assert held.status_code == 409 and held.json['code'] == 'UNRESOLVED_ISSUES'


def test_invalid_confirmation_returns_422(client):
    run = _run(client)
    response = client.post(f"/api/runs/{run['id']}/confirmations",
                           json={'revision': 0, 'case': '0001', 'station': 'X', 'second': 1})
    assert response.status_code == 422 and response.json['code'] == 'INVALID_CONFIRMATION'


def test_withdraw_confirmation_recomputes(client):
    run = _run(client)
    added = client.post(f"/api/runs/{run['id']}/confirmations",
                        json={'revision': 0, 'case': '0001', 'station': 8, 'second': 25}).json
    target = added['report']['confirmations'][0]
    response = client.delete(f"/api/runs/{run['id']}/confirmations/{target['id']}",
                             json={'revision': 1})
    assert response.status_code == 200 and response.json['revision'] == 2
    assert client.get(f"/api/runs/{run['id']}/confirmations").json == {'items': []}


def test_withdraw_missing_returns_404(client):
    run = _run(client)
    response = client.delete(f"/api/runs/{run['id']}/confirmations/ghost", json={'revision': 0})
    assert response.status_code == 404 and response.json['code'] == 'CONFIRMATION_NOT_FOUND'


def test_stale_revision_blocks_confirmation(client):
    run = _run(client)
    client.post(f"/api/runs/{run['id']}/confirmations",
                json={'revision': 0, 'case': '0001', 'station': 8, 'second': 25})
    response = client.post(f"/api/runs/{run['id']}/confirmations",
                           json={'revision': 0, 'case': '0001', 'station': 9, 'second': 30})
    assert response.status_code == 409 and response.json['code'] == 'STALE_REVIEW'


def test_confirmation_on_missing_run_is_404(client):
    response = client.post('/api/runs/unknown/confirmations',
                           json={'revision': 0, 'case': '0001', 'station': 8, 'second': 25})
    assert response.status_code == 404


def test_withdraw_then_approve_with_old_revision_fails(client):
    """撤回一旦生效，携带旧 revision 的签发被拒，需读取新版本后重试。"""
    run = _run(client)
    added = client.post(f"/api/runs/{run['id']}/confirmations",
                        json={'revision': 0, 'case': '0001', 'station': 8, 'second': 25}).json
    target = added['report']['confirmations'][0]
    withdrawn = client.delete(f"/api/runs/{run['id']}/confirmations/{target['id']}",
                              json={'revision': 1}).json
    assert withdrawn['revision'] == 2
    stale = client.patch(f"/api/runs/{run['id']}",
                         json={'revision': 1, 'status': 'APPROVED', 'note': '旧复核单签发'})
    assert stale.status_code == 409 and stale.json['code'] == 'STALE_REVIEW'
    fresh = client.patch(f"/api/runs/{run['id']}",
                         json={'revision': 2, 'status': 'APPROVED', 'note': '刷新后签发'})
    assert fresh.status_code == 200 and fresh.json['status'] == 'APPROVED'


def test_confirmation_endpoints_do_not_accept_stage_payload(client):
    run = _run(client)
    response = client.post(f"/api/runs/{run['id']}/confirmations",
                           data={'sample': 'clean'})
    assert response.status_code == 422
