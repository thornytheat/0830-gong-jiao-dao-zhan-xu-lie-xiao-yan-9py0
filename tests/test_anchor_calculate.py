"""人工确认点参与站序匹配的单元规则。"""
import pytest

from app.business import DomainIssue
from app.modules.calculate import UncoverableError, compute
from app.modules.prepare import check_confirmation_shape, check_confirmations


def _ping(record, station, second, score):
    return {'record': record, 'station': station, 'second': second, 'score': score}


def _payload(pings, anchors, route=None, minimum=3):
    route = route or {1: 1, 2: 2, 3: 3}
    ordered = sorted(pings, key=lambda p: (p['second'], p['record']))
    return route, ordered, minimum, anchors


def test_without_anchors_matches_original_lis():
    pings = [_ping('a', 1, 1, 9), _ping('b', 3, 2, 9), _ping('c', 2, 6, 1)]
    result = compute(_payload(pings, []))
    assert result['value'] == 2 and result['evidence']['route'] == [1, 3]
    assert result['evidence']['confirmations'] == []


def test_anchor_is_counted_as_valid_stop():
    pings = [_ping('a', 1, 1, 9), _ping('b', 3, 2, 9), _ping('c', 3, 5, 9), _ping('d', 2, 6, 1)]
    result = compute(_payload(pings, [{'station': 2, 'second': 3}]))
    assert result['value'] == 3
    assert result['evidence']['route'] == [1, 2, 3]
    # 锚点本身没有定位记录，但路径里的定位点仍保留。
    assert result['evidence']['pings'] == ['a', 'c']
    assert result['evidence']['missing'] == []


def test_anchor_reuses_matching_ping_record():
    pings = [_ping('a', 1, 1, 9), _ping('b', 2, 3, 5), _ping('c', 3, 5, 9)]
    result = compute(_payload(pings, [{'station': 2, 'second': 3}]))
    assert result['evidence']['route'] == [1, 2, 3]
    # 锚点与同位定位点合并：站2 由定位 b 承载，不重复计数。
    assert result['evidence']['pings'] == ['a', 'b', 'c']
    assert result['evidence']['confidence'] == 23
    assert result['value'] == 3


def test_multiple_anchors_all_must_be_covered():
    pings = [_ping('a', 1, 1, 9)]
    result = compute(_payload(pings, [{'station': 2, 'second': 3}, {'station': 3, 'second': 5}], minimum=3))
    assert result['evidence']['route'] == [1, 2, 3]
    assert result['value'] == 3


def test_uncoverable_anchors_raise_for_pipeline_hold():
    # 锚点站序与时间矛盾：站3 早于站2，无法同时覆盖。
    pings = [_ping('a', 1, 1, 9)]
    with pytest.raises(UncoverableError):
        compute(_payload(pings, [{'station': 3, 'second': 2}, {'station': 2, 'second': 4}]))


def test_check_confirmations_detects_time_order_conflict():
    route = {1: 1, 2: 2, 3: 3}
    with pytest.raises(DomainIssue, match='CONFIRMATION_CONFLICT'):
        check_confirmations(route, 10, [{'station': 3, 'second': 2}, {'station': 2, 'second': 4}])


def test_check_confirmations_detects_duplicate_station():
    route = {1: 1, 2: 2}
    with pytest.raises(DomainIssue, match='CONFIRMATION_CONFLICT'):
        check_confirmations(route, 10, [{'station': 1, 'second': 2}, {'station': 1, 'second': 4}])


def test_check_confirmations_detects_same_second():
    route = {1: 1, 2: 2}
    with pytest.raises(DomainIssue, match='CONFIRMATION_CONFLICT'):
        check_confirmations(route, 10, [{'station': 1, 'second': 3}, {'station': 2, 'second': 3}])


def test_check_confirmation_shape_rejects_foreign_station():
    route = {1: 1, 2: 2}
    with pytest.raises(DomainIssue, match='INVALID_CONFIRMATION'):
        check_confirmation_shape(route, 10, {'station': 9, 'second': 3})


def test_check_confirmation_shape_rejects_late_second():
    route = {1: 1}
    with pytest.raises(DomainIssue, match='INVALID_CONFIRMATION'):
        check_confirmation_shape(route, 10, {'station': 1, 'second': 11})


def test_ordered_confirmations_pass():
    route = {1: 1, 2: 2, 3: 3}
    ordered = check_confirmations(route, 10, [{'station': 3, 'second': 5}, {'station': 1, 'second': 1}])
    assert [item['station'] for item in ordered] == [1, 3]
