"""人工确认点的补传、撤回与重核算。"""
import pytest

from app.business import DomainIssue
from app.review.service import add_confirmation, execute, review, withdraw_confirmation
from app.review.store import Store


def _case(run, case_id):
    return next(case for case in run['report']['cases'] if case['case'] == case_id)


def _route_of(run, case_id):
    return _case(run, case_id)['measure']['evidence']['route']


def test_confirmation_forces_longer_route_covering_all_anchors(store, dirty):
    """自动定位的长路径漏掉确认点时，存在包含全部确认点的达标路径则可重算签发。"""
    run = execute(store, dirty)
    # 0001 自动路径 7->8->9；补传站 8 在秒 25 的人工确认，路径仍须经过 8。
    updated = add_confirmation(store, run['id'], dict(revision=0, case='0001', station=8, second=25))
    assert updated['revision'] == 1
    case = _case(updated, '0001')
    evidence = case['measure']['evidence']
    assert evidence['route'] == [7, 8, 9]
    assert evidence['confirmations'] == [{'station': 8, 'second': 25}]
    assert len(store.confirmations(run['id'])) == 1
    # 补传后该组仍达标（minimum=3，路径 3 站）；整批因其他异常组本就不可签发，
    # 这里核对目标组判定已恢复 READY。
    assert case['status'] == 'READY'


def test_confirmation_keeps_clean_batch_releasable_and_approvable(store, clean):
    """可签发样例补传确认点后，达标路径仍支持整批签发。"""
    run = execute(store, clean)
    updated = add_confirmation(store, run['id'], dict(revision=0, case='0001', station=8, second=25))
    case = _case(updated, '0001')
    assert case['measure']['evidence']['route'] == [7, 8, 9]
    assert updated['report']['balance']['releasable'] is True
    approved = review(store, run['id'], dict(revision=1, status='APPROVED', note='确认点已覆盖，同意签发'))
    assert approved['status'] == 'APPROVED'


def test_confirmation_can_replace_auto_path_that_skips_anchor(tmp_path):
    """构造自动最优路径绕开晚到确认点的场景，确认点把路径拉回达标解。"""
    from conftest import csv_data
    rows = [
        ['s1', 'c1', 'stop', '1', '1', '0', '0', '0', '站序'],
        ['s2', 'c1', 'stop', '2', '2', '0', '0', '0', '站序'],
        ['s3', 'c1', 'stop', '3', '3', '0', '0', '0', '站序'],
        ['p1', 'c1', 'ping', '1', '0', '1', '9', '0', '定位'],
        ['p2', 'c1', 'ping', '3', '0', '2', '9', '0', '定位站3'],
        ['p3', 'c1', 'ping', '2', '0', '6', '1', '0', '迟到的逆序定位站2'],
        ['p4', 'c1', 'ping', '3', '0', '5', '9', '0', '锚点后的定位站3'],
        ['d1', 'c1', 'dispatch', '0', '0', '10', '0', '3', '班次'],
    ]
    store = Store(tmp_path / 'runs.db')
    run = execute(store, csv_data(rows))
    # 无确认点时：站2 定位(秒6)晚于最后的站3(秒5)，时间与站序逆序被排除，自动路径 1->3 缺站2。
    assert _route_of(run, 'c1') == [1, 3]
    assert _case(run, 'c1')['status'] == 'MISSING_STOPS'
    # 人工确认站 2 在秒 3：锚点在两个站3 之间，把自动路径漏掉的站2 补进 1 与 3 之间。
    updated = add_confirmation(store, run['id'], dict(revision=0, case='c1', station=2, second=3))
    case = _case(updated, 'c1')
    assert case['status'] == 'READY'
    assert _route_of(updated, 'c1') == [1, 2, 3]
    assert updated['report']['balance']['releasable'] is True


def test_conflicting_confirmations_hold_even_when_auto_route_ready(store, clean):
    """两处确认点时间与站序冲突时，即使自动定位已达标也要暂缓。"""
    run = execute(store, clean)
    assert run['report']['balance']['releasable'] is True
    # 0001 站序 7->8->9；先补一个顺序合理的确认点（站7,秒10），自动路径仍达标。
    first = add_confirmation(store, run['id'], dict(revision=0, case='0001', station=7, second=10))
    assert first['revision'] == 1 and _case(first, '0001')['status'] == 'READY'
    # 再补与站序矛盾的确认点（站8,秒5，早于站7 的确认时点），整组暂缓。
    second = add_confirmation(store, run['id'], dict(revision=1, case='0001', station=8, second=5))
    # 冲突确认点仍落库，但该组判定为 CONFIRMATION_CONFLICT，整批暂缓、不可签发。
    assert _case(second, '0001')['status'] == 'CONFIRMATION_CONFLICT'
    assert second['revision'] == 2 and len(store.confirmations(run['id'])) == 2
    assert second['report']['balance']['releasable'] is False
    with pytest.raises(DomainIssue, match='UNRESOLVED_ISSUES'):
        review(store, run['id'], dict(revision=2, status='APPROVED', note='带冲突仍试图签发'))


def test_second_confirmation_conflicts_status_and_blocks_release(store, clean):
    """确认点互相冲突时，业务组进入 CONFIRMATION_CONFLICT，整批不可签发。"""
    run = execute(store, clean)
    add_confirmation(store, run['id'], dict(revision=0, case='0001', station=7, second=10))
    # 同站重复确认即冲突（路径严格递增，同一站无法出现两次）。
    updated = add_confirmation(store, run['id'], dict(revision=1, case='0001', station=7, second=20))
    case = _case(updated, '0001')
    assert case['status'] == 'CONFIRMATION_CONFLICT'
    assert updated['report']['balance']['releasable'] is False
    with pytest.raises(DomainIssue, match='UNRESOLVED_ISSUES'):
        review(store, run['id'], dict(revision=2, status='APPROVED', note='试图带冲突签发'))


def test_withdraw_recomputes_and_restores_ready(store, clean):
    """撤回确认点后按剩余确认点重新核算。"""
    run = execute(store, clean)
    first = add_confirmation(store, run['id'], dict(revision=0, case='0001', station=8, second=25))
    second = add_confirmation(store, run['id'], dict(revision=1, case='0001', station=8, second=30))
    assert _case(second, '0001')['status'] == 'CONFIRMATION_CONFLICT'
    target = store.confirmations(run['id'])[1]
    restored = withdraw_confirmation(store, run['id'], target['id'], dict(revision=2))
    assert restored['revision'] == 3
    assert _case(restored, '0001')['status'] == 'READY'
    assert len(store.confirmations(run['id'])) == 1
    assert restored['report']['balance']['releasable'] is True


def test_withdraw_unknown_confirmation_is_404(store, clean):
    run = execute(store, clean)
    with pytest.raises(DomainIssue, match='CONFIRMATION_NOT_FOUND'):
        withdraw_confirmation(store, run['id'], 'nope', dict(revision=0))


def test_invalid_confirmation_station_and_second(store, dirty):
    run = execute(store, dirty)
    with pytest.raises(DomainIssue, match='INVALID_CONFIRMATION'):
        add_confirmation(store, run['id'], dict(revision=0, case='0001', station='X', second=10))
    with pytest.raises(DomainIssue, match='INVALID_CONFIRMATION'):
        add_confirmation(store, run['id'], dict(revision=0, case='0001', station=7, second=99))
    assert store.load(run['id'])['revision'] == 0


def test_confirmation_for_unknown_case(store, clean):
    run = execute(store, clean)
    with pytest.raises(DomainIssue, match='CONFIRMATION_CASE_UNKNOWN'):
        add_confirmation(store, run['id'], dict(revision=0, case='9999', station=7, second=10))


def test_confirmation_uses_optimistic_revision(store, clean):
    run = execute(store, clean)
    add_confirmation(store, run['id'], dict(revision=0, case='0001', station=8, second=25))
    with pytest.raises(DomainIssue, match='STALE_REVIEW'):
        add_confirmation(store, run['id'], dict(revision=0, case='0001', station=9, second=30))


def test_finalized_run_rejects_confirmation_change(store, clean):
    run = execute(store, clean)
    review(store, run['id'], dict(revision=0, status='APPROVED', note='批次完成签发'))
    with pytest.raises(DomainIssue, match='RUN_FINALIZED'):
        add_confirmation(store, run['id'], dict(revision=1, case='0001', station=8, second=25))
    target = store.confirmations(run['id'])
    assert target == []


def test_withdraw_and_approve_race_old_revision_loses(store, clean):
    """撤回与签发同时提交：撤回生效后推进版本号，旧复核单不能签发。"""
    run = execute(store, clean)
    added = add_confirmation(store, run['id'], dict(revision=0, case='0001', station=8, second=25))
    target = store.confirmations(run['id'])[0]
    # 两个操作都基于 revision=1 的旧复核单；撤回先落库并把版本号推进到 2。
    withdrawn = withdraw_confirmation(store, run['id'], target['id'], dict(revision=1))
    assert withdrawn['revision'] == 2
    # 撤回一旦生效，仍携带 revision=1 的签发必须失败。
    with pytest.raises(DomainIssue, match='STALE_REVIEW'):
        review(store, run['id'], dict(revision=1, status='APPROVED', note='撤回同时签发'))
    final = store.load(run['id'])
    assert final['status'] != 'APPROVED'
    assert store.confirmations(run['id']) == []
    assert final['revision'] == 2


def test_parallel_withdraw_and_approve_serializes(store, clean):
    """并发提交时写操作串行化，且撤回后旧版本号无法再签发。"""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    run = execute(store, clean)
    add_confirmation(store, run['id'], dict(revision=0, case='0001', station=8, second=25))
    target = store.confirmations(run['id'])[0]
    barrier = Barrier(2)

    def withdraw():
        barrier.wait(3)
        try:
            return ('withdrawn', withdraw_confirmation(store, run['id'], target['id'], dict(revision=1))['revision'])
        except DomainIssue as error:
            return ('withdraw-error', error.code)

    def approve():
        barrier.wait(3)
        try:
            return ('approved', review(store, run['id'], dict(revision=1, status='APPROVED', note='撤回同时签发'))['status'])
        except DomainIssue as error:
            return ('approve-error', error.code)

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = dict(threads.map(lambda fn: fn(), [withdraw, approve]))
    final = store.load(run['id'])
    if 'withdrawn' in results:
        # 撤回成功：确认点已清空，最终版本号为 2，批次不可能被旧复核单签发。
        assert store.confirmations(run['id']) == []
        assert final['revision'] == 2
        assert results.get('approve-error') == 'STALE_REVIEW' or final['status'] != 'APPROVED'
    else:
        # 签发先到：批次已最终化，撤回被旧版本号或最终化拦截。
        assert final['status'] == 'APPROVED'
        assert results['withdraw-error'] in ('RUN_FINALIZED', 'STALE_REVIEW')


def test_recomputed_report_keeps_manifest_and_lists_confirmations(store, clean):
    run = execute(store, clean)
    updated = add_confirmation(store, run['id'], dict(revision=0, case='0001', station=8, second=25))
    assert updated['report']['manifest'] == run['report']['manifest']
    assert updated['report']['confirmations'][0]['station'] == 8
    evidence = updated['measure'] if 'measure' in updated else None
    # 证据导出包含确认点快照。
    from app.evidence.render import artifact
    import json
    packet = json.loads(artifact(updated))
    assert packet['confirmations'][0]['case'] == '0001'
    assert packet['cases'][0]['measure']['evidence']['confirmations'] == [{'station': 8, 'second': 25}]
    assert evidence is None
