#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暑假作业小管家 - 局域网同步服务器
静态托管本目录 + /api/state 同步接口（GET/PUT/OPTIONS）。
同步数据保存在同目录 data.json（可用环境变量 HW_DATA_FILE 覆盖，便于测试），原子写入。
"""
import json
import os
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
    return bool(st.get('subjects')) or bool(st.get('logEvents')) or bool(st.get('log'))


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
        merged['logEvents'] = union_events(ss.get('logEvents'), inc.get('logEvents'))
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
    # 常规冲突：打卡事件按 id 并集相加，其余字段以最后到达者为准
    merged = dict(inc)
    merged['logEvents'] = union_events(ss.get('logEvents'), inc.get('logEvents'))
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
