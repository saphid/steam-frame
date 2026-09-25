"""Second pass: Compose UI version, launcher activity, GMS meta-data, uses-feature
strings from AndroidManifest.xml (binary XML string pool). Resumable JSONL."""
import json, os, struct, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import zipcd

HERE = os.path.dirname(os.path.abspath(__file__))
IN = os.path.join(HERE, 'data', 'scan.jsonl')
OUT = os.path.join(HERE, 'data', 'scan2.jsonl')
FEATURES = ['android.hardware.touchscreen.multitouch', 'android.hardware.telephony',
            'android.hardware.nfc', 'android.hardware.bluetooth_le', 'android.hardware.usb.host',
            'android.hardware.camera', 'android.hardware.vr.high_performance',
            'android.software.leanback', 'android.hardware.type.watch']


def axml_strings(b):
    # ResXMLTree_header (8) then string pool chunk
    off = struct.unpack('<H', b[2:4])[0]
    t, hs, sz, cnt, _styles, flags, sstart, _ = struct.unpack('<HHIIIIII', b[off:off + 28])
    utf8 = flags & 0x100
    offs = struct.unpack(f'<{cnt}I', b[off + hs:off + hs + 4 * cnt])
    base = off + sstart
    out = []
    for o in offs:
        p = base + o
        if utf8:
            n = b[p]; p += 2 if n & 0x80 else 1
            n = b[p]; hi = n & 0x80
            if hi:
                n = ((n & 0x7f) << 8) | b[p + 1]; p += 2
            else:
                p += 1
            out.append(b[p:p + n].decode('utf-8', 'replace'))
        else:
            n = struct.unpack('<H', b[p:p + 2])[0]; p += 2
            if n & 0x8000:
                n = ((n & 0x7fff) << 16) | struct.unpack('<H', b[p:p + 2])[0]; p += 2
            out.append(b[p:p + 2 * n].decode('utf-16-le', 'replace'))
    return out


def scan(r):
    o = {'pkg': r['pkg'], 'vc': r.get('vc')}
    try:
        names, ent, _ = zipcd.list_names(r['apk'], r['size'])
        for n in ('META-INF/androidx.compose.ui_ui.version', 'META-INF/androidx.compose.ui_ui-android.version'):
            if n in ent:
                o['compose_ver'] = zipcd.read_entry(r['apk'], ent, n).decode().strip()
                break
        o['sdl3'] = any(n.endswith('/libSDL3.so') for n in names)
        s = set(axml_strings(zipcd.read_entry(r['apk'], ent, 'AndroidManifest.xml')))
        o['launcher'] = 'android.intent.category.LAUNCHER' in s
        o['leanback_launcher'] = 'android.intent.category.LEANBACK_LAUNCHER' in s
        o['gms_meta'] = 'com.google.android.gms.version' in s
        o['ime'] = 'android.view.InputMethod' in s
        o['features'] = [f for f in FEATURES if f in s]
    except Exception as e:
        o['error2'] = f'{type(e).__name__}: {e}'[:200]
    return o


def main():
    rows = list({r['pkg']: r for r in map(json.loads, open(IN))}.values())  # latest per app
    done = set()
    if os.path.exists(OUT):
        done = {(o['pkg'], o.get('vc')) for o in map(json.loads, open(OUT))}
    rows = [r for r in rows if (r['pkg'], r.get('vc')) not in done and 'error' not in r]
    print(len(done), 'done', len(rows), 'todo', flush=True)
    lock = threading.Lock(); n = 0
    with open(OUT, 'a') as out, ThreadPoolExecutor(int(os.environ.get('WORKERS', '40'))) as ex:
        for fu in as_completed([ex.submit(scan, r) for r in rows]):
            with lock:
                out.write(json.dumps(fu.result()) + '\n'); out.flush(); n += 1
                if n % 200 == 0:
                    print(n, flush=True)
    print('finished', flush=True)


if __name__ == '__main__':
    main()
