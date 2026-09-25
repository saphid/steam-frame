#!/usr/bin/env python3
"""Frame-side: manage non-Steam shortcuts through the Steam client's CEF debug
port (127.0.0.1:8080, target SharedJSContext), without restarting Steam.
Python stdlib only; the Mac runs it with `ssh frame python3 - <args> < this`.

  steam_shortcuts.py add NAME EXE START_DIR [ICON]  -> prints the shortcut app id
  steam_shortcuts.py list                           -> JSON [{appid, name, exe}]
  steam_shortcuts.py remove APPID
"""
import base64, json, os, socket, struct, sys, urllib.request

DEVTOOLS = 'http://127.0.0.1:8080/json'


def target_ws():
    for t in json.load(urllib.request.urlopen(DEVTOOLS, timeout=5)):
        if t.get('title') == 'SharedJSContext':
            return t['webSocketDebuggerUrl']
    sys.exit('SharedJSContext not found: is the Steam client running?')


class WS:
    """Just enough RFC 6455 for one CDP request/response on loopback."""

    def __init__(self, url):
        host_port, path = url[len('ws://'):].split('/', 1)
        host, port = host_port.split(':')
        self.s = socket.create_connection((host, int(port)), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f'GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\n'
                        f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                        'Sec-WebSocket-Version: 13\r\n\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.s.recv(4096)
        if b' 101 ' not in buf.split(b'\r\n', 1)[0]:
            sys.exit('websocket handshake failed')
        self.rest = buf.split(b'\r\n\r\n', 1)[1]

    def _read(self, n):
        while len(self.rest) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise EOFError
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, text):
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + struct.pack('>H', n) if n < 65536 else
                                bytes([0x80 | 127]) + struct.pack('>Q', n))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b''
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7f
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            msg += self._read(n)
            if b0 & 0x80:
                return msg.decode()


def evaluate(js):
    ws = WS(target_ws())
    ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
        'expression': js, 'awaitPromise': True, 'returnByValue': True}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == 1:
            break
    res = r.get('result', {})
    if 'exceptionDetails' in res:
        sys.exit('JS error: ' + json.dumps(res['exceptionDetails'])[:500])
    return res.get('result', {}).get('value')


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == 'add':
        name, exe, start_dir = args[:3]
        icon = args[3] if len(args) > 3 else ''
        js = f'''(async () => {{
          const id = await SteamClient.Apps.AddShortcut({json.dumps(name)}, {json.dumps(exe)}, "", "");
          SteamClient.Apps.SetShortcutName(id, {json.dumps(name)});
          SteamClient.Apps.SetShortcutStartDir(id, {json.dumps(start_dir)});
          if ({json.dumps(icon)}) SteamClient.Apps.SetShortcutIcon(id, {json.dumps(icon)});
          return id;
        }})()'''
        print(evaluate(js))
    elif cmd == 'list':
        js = '''(() => appStore.allApps.filter(a => a.app_type === 1073741824)
                  .map(a => ({appid: a.appid, name: a.display_name})))()'''
        print(json.dumps(evaluate(js)))
    elif cmd == 'remove':
        evaluate(f'SteamClient.Apps.RemoveShortcut({int(args[0])})')
        print('removed')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
