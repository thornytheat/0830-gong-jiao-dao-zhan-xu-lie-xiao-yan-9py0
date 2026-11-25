from app.business import DomainIssue, by_kind, prepared, single


def check_confirmation_shape(route, deadline, item):
    """单个确认点的结构校验：字段合法、站点属于班次、时点不超过截止。"""
    if not isinstance(item, dict):
        raise DomainIssue('INVALID_CONFIRMATION')
    station, second = item.get('station'), item.get('second')
    if station is None or type(second) is not int or second < 0 or second > deadline:
        raise DomainIssue('INVALID_CONFIRMATION')
    if station not in route:
        raise DomainIssue('INVALID_CONFIRMATION')
    return {'station': station, 'second': second}


def check_confirmations(route, deadline, confirmations):
    """校验一组人工确认点：结构合法，且时间与站序严格一致、无重复站点/时点。"""
    checked = [check_confirmation_shape(route, deadline, item) for item in confirmations]
    ordered = sorted(checked, key=lambda item: (item['second'], item['station']))
    for earlier, later in zip(ordered, ordered[1:]):
        same_moment = earlier['second'] == later['second']
        same_station = earlier['station'] == later['station']
        if same_moment or same_station or route[earlier['station']] >= route[later['station']]:
            raise DomainIssue('CONFIRMATION_CONFLICT')
    return ordered


def prepare(rows, confirmations=None):
    dispatch = single(rows, 'dispatch')
    stops = by_kind(rows, 'stop')
    route = {r['station']: r['ordinal'] for r in stops}
    if not route or len(route) != len(stops) or len(set(route.values())) != len(route) or 0 in route.values():
        raise DomainIssue('STOP_ORDER_CONFLICT')
    pings = by_kind(rows, 'ping')
    if len(pings) > 320 or not 0 < dispatch['minimum'] <= len(route):
        raise DomainIssue('INVALID_DISPATCH')
    if any(r['station'] not in route or not 0 < r['score'] <= 100 or r['second'] > dispatch['second'] for r in pings):
        raise DomainIssue('INVALID_PING')
    ordered = sorted(pings, key=lambda p: (p['second'], p['record']))
    anchors = check_confirmations(route, dispatch['second'], confirmations or ())
    details = {'registered_stops': len(route), 'minimum': dispatch['minimum'],
               'stations': len(route), 'confirmations': len(anchors)}
    return prepared(len(pings), details, (route, ordered, dispatch['minimum'], anchors))
