from app.business import measured


def _lis(pings, route):
    """以每个定位点为终点的最优严格递增链，沿用原最长站序动态规划。"""
    ranked = []
    for i, ping in enumerate(pings):
        eligible = [ranked[j] for j, prev in enumerate(pings[:i])
                    if prev['second'] < ping['second'] and route[prev['station']] < route[ping['station']]]
        _, negative_score, chain = min(eligible, default=(0, 0, ()))
        followed = (*chain, i)
        ranked.append((-len(followed), negative_score - ping['score'], followed))
    return ranked


def _anchored_lis(pings, route, anchors):
    """在定位点之外加入必中锚点，求覆盖全部锚点的最优严格递增路径。

    节点统一为字典；锚点 required=True、无置信度、record 为 None，且必须出现在结果中。
    动态规划对每个终点分别保留“已覆盖锚点集合”不同的最优状态，
    再在覆盖全部锚点的状态里按站数、置信度、记录键择优。
    """
    nodes = [
        {'station': p['station'], 'second': p['second'], 'score': p['score'],
         'record': p['record'], 'required': False}
        for p in pings
    ]
    # 锚点与同站同时的定位点合并：确认该定位点（标记 required），不重复成站。
    for anchor in anchors:
        match = next((node for node in nodes
                      if node['station'] == anchor['station'] and node['second'] == anchor['second']), None)
        if match is not None:
            match['required'] = True
        else:
            nodes.append({'station': anchor['station'], 'second': anchor['second'], 'score': 0,
                          'record': None, 'required': True})
    nodes.sort(key=lambda n: (n['second'], n['station'], 0 if n['required'] else 1))
    required_indices = frozenset(i for i, n in enumerate(nodes) if n['required'])
    # states[i]：以节点 i 结尾时，按已覆盖锚点集合区分的最优状态。
    states = [dict() for _ in nodes]
    for i, node in enumerate(nodes):
        own = frozenset({i}) if node['required'] else frozenset()
        candidates = [{'length': 0, 'score': 0, 'key': (), 'chain': (), 'anchors': frozenset()}]
        for j, prev in enumerate(nodes[:i]):
            if not (prev['second'] < node['second'] and route[prev['station']] < route[node['station']]):
                continue
            candidates.extend(states[j].values())
        for chosen in candidates:
            anchors_held = chosen['anchors'] | own
            key = (*chosen['key'], node['record']) if node['record'] is not None else chosen['key']
            state = {'length': chosen['length'] + 1, 'score': chosen['score'] + node['score'],
                     'key': key, 'chain': (*chosen['chain'], i), 'anchors': anchors_held}
            current = states[i].get(anchors_held)
            if current is None or (state['length'], state['score'], state['key']) > \
                    (current['length'], current['score'], current['key']):
                states[i][anchors_held] = state
    feasible = [state for bucket in states for state in bucket.values() if required_indices <= state['anchors']]
    if not feasible:
        return None
    winner = max(feasible, key=lambda item: (item['length'], item['score'], item['key']))
    return [nodes[i] for i in winner['chain']]


def compute(data):
    route, pings, minimum, anchors = data
    if anchors:
        nodes = _anchored_lis(pings, route, anchors)
        if nodes is None:
            # 无路径能覆盖全部锚点：交由上层按确认点冲突暂缓处理。
            raise UncoverableError
        visited = [node['station'] for node in nodes]
        ping_records = [node['record'] for node in nodes if node['record'] is not None]
        confidence = sum(node['score'] for node in nodes)
        length = len(nodes)
    else:
        _, negative_score, path = min(_lis(pings, route), default=(0, 0, ()))
        length = len(path)
        visited = [pings[i]['station'] for i in path]
        confidence = -negative_score
        ping_records = [pings[i]['record'] for i in path]
    anchor_points = [{'station': item['station'], 'second': item['second']} for item in anchors]
    return measured(length, minimum, '站', {
        'route': visited,
        'pings': ping_records,
        'missing': [k for k in sorted(route, key=route.get) if k not in visited],
        'confidence': confidence,
        'confirmations': anchor_points,
    })


class UncoverableError(Exception):
    pass
