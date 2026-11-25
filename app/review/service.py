import re
from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.intake.service import inspect
from app.modules.grouping import case_groups
from app.modules.pipeline import run
from app.modules.prepare import check_confirmation_shape


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    run_id = sha256(f'{RULE_VERSION}:{fingerprint}'.encode()).hexdigest()
    try:
        return store.load(run_id)
    except DomainIssue as error:
        if error.code != 'RUN_NOT_FOUND':
            raise
    report = run(data)
    report['manifest'] = dict(sha256=fingerprint, version=RULE_VERSION, created=now(),
                              duration_ms=round((monotonic() - start) * 1000, 3), bytes=len(data), run_id=run_id)
    return store.register(run_id, report, data)


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue('REVIEW_FIELDS')
    revision, status, note = (values.get(key) for key in ('revision', 'status', 'note'))
    if type(revision) is not int or revision < 0 or status not in ('APPROVED', 'HELD') or not isinstance(note, str) or not (3 <= len(note.strip()) <= 200):
        raise DomainIssue('REVIEW_FIELDS')
    current = store.load(run_id)
    if revision != current['revision']:
        raise DomainIssue('STALE_REVIEW')
    if current['status'] == 'APPROVED':
        raise DomainIssue('RUN_FINALIZED')
    if status == 'APPROVED' and not current['report']['balance']['releasable']:
        raise DomainIssue('UNRESOLVED_ISSUES')
    return store.revise(run_id, revision, status, note.strip(), now())


def _case_rows(store, run_id, case_id):
    """重新采信来源并取出指定业务组的原始行。"""
    intake = inspect(store.source(run_id))
    grouped = dict(case_groups(intake['rows']))
    if case_id not in grouped:
        raise DomainIssue('CONFIRMATION_CASE_UNKNOWN')
    return grouped[case_id]


def _case_route(rows):
    from app.business import by_kind, single
    dispatch = single(rows, 'dispatch')
    route = {r['station']: r['ordinal'] for r in by_kind(rows, 'stop')}
    return route, dispatch['second']


def _recalculate(store, run_id, confirmations):
    """按给定确认点集合重新核算整批报告，保留原清单。"""
    current = store.load(run_id)
    report = run(store.source(run_id), confirmations=confirmations)
    report['manifest'] = current['report']['manifest']
    return report


def _station_key(value):
    """工作台 JSON 里站点可能按字符串提交，归一化为来源 CSV 的整数站点键。"""
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value.strip()):
        return int(value.strip())
    return value


def add_confirmation(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue('REVIEW_FIELDS')
    revision = values.get('revision')
    case_id, station, second = values.get('case'), _station_key(values.get('station')), values.get('second')
    if type(revision) is not int or revision < 0 or not isinstance(case_id, str) or not case_id:
        raise DomainIssue('REVIEW_FIELDS')
    if not isinstance(station, str) and not type(station) is int:
        raise DomainIssue('INVALID_CONFIRMATION')
    if not station or type(second) is not int or second < 0:
        raise DomainIssue('INVALID_CONFIRMATION')
    current = store.load(run_id)
    if current['status'] == 'APPROVED':
        raise DomainIssue('RUN_FINALIZED')
    if revision != current['revision']:
        raise DomainIssue('STALE_REVIEW')
    rows = _case_rows(store, run_id, case_id)
    route, deadline = _case_route(rows)
    # 结构预检：站点属于班次、时点合法才落库；时间与站序冲突留给重核算阶段判定暂缓。
    check_confirmation_shape(route, deadline, {'station': station, 'second': second})
    stamp = now()
    confirmation_id = sha256(f'{run_id}:{case_id}:{station}:{second}:{stamp}'.encode()).hexdigest()[:16]
    confirmation = {'id': confirmation_id, 'case': case_id, 'station': station, 'second': second, 'created': stamp}
    confirmations = [*store.confirmations(run_id), confirmation]
    report = _recalculate(store, run_id, confirmations)
    return store.add_confirmation(run_id, revision, confirmation, report, stamp)


def withdraw_confirmation(store, run_id, confirmation_id, values):
    if not isinstance(values, dict) or type(values.get('revision')) is not int or values.get('revision') < 0:
        raise DomainIssue('REVIEW_FIELDS')
    revision = values['revision']
    current = store.load(run_id)
    if current['status'] == 'APPROVED':
        raise DomainIssue('RUN_FINALIZED')
    if revision != current['revision']:
        raise DomainIssue('STALE_REVIEW')
    stored = store.confirmations(run_id)
    if not any(item['id'] == confirmation_id for item in stored):
        raise DomainIssue('CONFIRMATION_NOT_FOUND')
    remaining = [item for item in stored if item['id'] != confirmation_id]
    # 撤回后按剩余确认点重新核算。
    report = _recalculate(store, run_id, remaining)
    return store.remove_confirmation(run_id, revision, confirmation_id, report)
