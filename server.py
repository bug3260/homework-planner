#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暑假作业小管家 - 局域网同步服务器
静态托管本目录 + /api/state 同步接口（GET/PUT/OPTIONS）。
同步数据保存在同目录 data.json（可用环境变量 HW_DATA_FILE 覆盖，便于测试），原子写入。
"""
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.environ.get('HW_DATA_FILE') or os.path.join(ROOT, 'data.json')
MAX_BODY = 1024 * 1024
_lock = threading.Lock()

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.svg': 'image/svg+xml',
    '.webmanifest': 'application/manifest+json',
    '.json': 'application/json; charset=utf-8',
    '.ico': 'image/x-icon',
    '.txt': 'text/plain; charset=utf-8',
    '.py': 'text/plain; charset=utf-8',
    '.bat': 'text/plain; charset=utf-8',
    '.ps1': 'text/plain; charset=utf-8',
}


def read_store():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get('state'), dict) and isinstance(d.get('rev'), int):
            return d
    except Exception:
        pass
    return {'rev': 0, 'state': None}


def write_store(store):
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


def union_events(a, b):
    out = []
    seen = set()
    for ev in (a or []) + (b or []):
        if not isinstance(ev, dict):
            continue
        eid = ev.get('id')
        if not eid or eid in seen:
            continue
        seen.add(eid)
        out.append({
            'id': str(eid),
            'd': str(ev.get('d') or ''),
            'sid': str(ev.get('sid') or ''),
            'n': int(ev.get('n') or 0),
            't': str(ev.get('t') or '')[:5]
        })
    return out


def recompute_log(state):
    log = {}
    for ev in state.get('logEvents') or []:
        d, sid, n = ev.get('d'), ev.get('sid'), ev.get('n', 0)
        if not d or not sid or not n:
            continue
        log.setdefault(d, {})
        log[d][sid] = (log[d].get(sid, 0) or 0) + n
    for d in list(log.keys()):
        for sid in list(log[d].keys()):
            if log[d][sid] <= 0:
                del log[d][sid]
        if not log[d]:
            del log[d]
    state['log'] = log
    return state


def state_has_data(st):
    st = st or {}
    return bool(st.get('subjects')) or bool(st.get('logEvents')) or bool(st.get('log')) or bool(st.get('subjectGraves'))


def norm_subject(x):
    if not isinstance(x, dict) or not x.get('id'):
        return None

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    color = str(x.get('color') or '')
    return {
        'id': str(x.get('id')),
        'name': str(x.get('name') or ''),
        'emoji': str(x.get('emoji') or '📖'),
        'color': color if re.match(r'^#[0-9a-fA-F]{6}$', color) else '#8e7cff',
        'unit': str(x.get('unit') or '页'),
        'total': max(0, int(num(x.get('total')))),
        'done': max(0, int(num(x.get('done')))),
        'mod': max(0, int(num(x.get('mod')))),
    }


def merge_subjects(ss, inc):
    best = {}
    order = []

    def put(x, prefer):
        n = norm_subject(x)
        if not n:
            return
        sid = n['id']
        if sid not in best:
            best[sid] = n
            order.append(sid)
            return
        cur = best[sid]
        if n['mod'] > cur['mod'] or (n['mod'] == cur['mod'] and prefer):
            best[sid] = n

    for x in (inc.get('subjects') or []):
        put(x, True)
    for x in (ss.get('subjects') or []):
        put(x, False)
    graves = {}
    for m in (ss.get('subjectGraves'), inc.get('subjectGraves')):
        if not isinstance(m, dict):
            continue
        for sid, v in m.items():
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            if not sid or v <= 0:
                continue
            sid = str(sid)
            if sid not in graves or v > graves[sid]:
                graves[sid] = v
    subjects = []
    for sid in order:
        sub = best[sid]
        if sid in graves and graves[sid] >= sub['mod']:
            continue
        subjects.append(sub)
        graves.pop(sid, None)
    return subjects, graves


def filter_for_subjects(state, subjects):
    ids = set(s['id'] for s in subjects)
    state['logEvents'] = [e for e in (state.get('logEvents') or []) if isinstance(e, dict) and e.get('sid') in ids]
    overrides = {}
    for d, rec in (state.get('overrides') or {}).items():
        if not isinstance(rec, dict):
            continue
        keep = {sid: v for sid, v in rec.items() if sid in ids}
        if keep:
            overrides[d] = keep
    state['overrides'] = overrides
    return state


def merge(server_state, incoming):
    ss, inc = server_state or {}, incoming or {}
    ss_has = state_has_data(ss)
    inc_has = state_has_data(inc)
    # 首次接触：有数据的一边胜出（防空设备用新时间戳覆盖云端），两边都有/都没数据时才按 updatedAt
    if not (ss.get('hasSynced') and inc.get('hasSynced')):
        if (inc.get('resetCount') or 0) > (ss.get('resetCount') or 0):
            return dict(inc)
        if (ss.get('resetCount') or 0) > (inc.get('resetCount') or 0):
            return dict(ss)
        if ss_has and not inc_has:
            base = ss
        elif inc_has and not ss_has:
            base = inc
        else:
            base = inc if (inc.get('updatedAt') or 0) >= (ss.get('updatedAt') or 0) else ss
        merged = dict(base)
        merged['subjects'], merged['subjectGraves'] = merge_subjects(ss, inc)
        merged['logEvents'] = union_events(ss.get('logEvents'), inc.get('logEvents'))
        merged = filter_for_subjects(merged, merged['subjects'])
        merged = recompute_log(merged)
        merged['hasSynced'] = True
        return merged
    # 清空数据：resetCount 大者整体胜出
    if (inc.get('resetCount') or 0) > (ss.get('resetCount') or 0):
        return dict(inc)
    if (ss.get('resetCount') or 0) > (inc.get('resetCount') or 0):
        return dict(ss)
    # 空设备不覆盖有数据的云端
    if ss_has and not inc_has:
        return dict(ss)
    # 常规冲突：打卡事件按 id 并集相加，其余字段以最后到达者为准；科目按 id 合并、删除用墓碑
    merged = dict(inc)
    merged['subjects'], merged['subjectGraves'] = merge_subjects(ss, inc)
    merged['logEvents'] = union_events(ss.get('logEvents'), inc.get('logEvents'))
    merged = filter_for_subjects(merged, merged['subjects'])
    merged = recompute_log(merged)
    merged['hasSynced'] = True
    return merged


class Handler(BaseHTTPRequestHandler):
    server_version = 'hw-sync/1.0'

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stdout.write('[%s] %s\n' % (self.log_date_time_string(), fmt % args))

    def _api_path(self):
        return self.path.split('?')[0].split('#')[0].rstrip('/') == '/api/state'

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if self._api_path():
            with _lock:
                store = read_store()
            self._json(200, {'rev': store['rev'], 'state': store['state']})
            return
        self._static()

    def do_PUT(self):
        if not self._api_path():
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length > MAX_BODY:
                self._json(413, {'error': 'too large'})
                return
            raw = self.rfile.read(length)
            body = json.loads(raw.decode('utf-8'))
            incoming = body.get('state')
            base_rev = int(body.get('baseRev') or 0)
            if not isinstance(incoming, dict):
                raise ValueError('bad state')
        except Exception as e:
            self._json(400, {'error': 'bad request: %s' % e})
            return
        with _lock:
            store = read_store()
            if store['state'] is None or base_rev == store['rev']:
                if (store['state'] and state_has_data(store['state'])
                        and not state_has_data(incoming)
                        and not (incoming.get('resetCount') or 0) > (store['state'].get('resetCount') or 0)):
                    merged = dict(store['state'])
                else:
                    merged = dict(incoming)
                    merged['hasSynced'] = True
            else:
                merged = merge(store['state'], incoming)
            store['state'] = merged
            store['rev'] = store['rev'] + 1
            write_store(store)
        self._json(200, {'rev': store['rev'], 'state': merged})

    def _static(self):
        path = self.path.split('?')[0].split('#')[0]
        if path in ('', '/'):
            path = '/index.html'
        rel = path.lstrip('/')
        target = os.path.normpath(os.path.join(ROOT, rel))
        if not target.startswith(ROOT) or not os.path.isfile(target):
            self.send_error(404)
            return
        ext = os.path.splitext(target)[1].lower()
        with open(target, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self._cors()
        self.send_header('Content-Type', MIME.get(ext, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    httpd = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print('暑假作业小管家同步服务器已启动: http://0.0.0.0:%d' % port)
    print('同步数据保存在: %s' % DATA_FILE)
    print('手机和电脑打开页面后会自动同步，按 Ctrl+C 结束。')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
