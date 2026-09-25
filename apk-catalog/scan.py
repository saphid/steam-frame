"""Scan F-Droid APKs (latest version per app) for Steam Frame / Lepton signals.

Reads only the zip central directory and the resources.arsc key-string pool
through HTTP range requests. Output: one JSON line per package (resumable).
"""
import json, os, struct, sys, zlib, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import zipcd
from pick import pick_version

REPO = 'https://f-droid.org/repo'
HERE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(HERE, 'data', 'index-v2.json')
OUT = os.path.join(HERE, 'data', 'scan.jsonl')

KEYS = {
    'compose': [b'compose_view_saveable_id_tag', b'wrapped_composition_tag',
                b'androidx_compose_ui_view_compositionlocal_map'],
    'gms': [b'common_google_play_services_unknown_issue',
            b'common_google_play_services_install_title'],
    'firebase': [b'google_app_id', b'gcm_defaultSenderId'],
}
LIBS = {
    'unity': 'libunity.so', 'flutter': 'libflutter.so', 'reactnative': 'libreactnative',
    'hermes': 'libhermes', 'godot': 'libgodot_android.so', 'gdx': 'libgdx.so',
    'sdl': 'libSDL2.so', 'unreal': 'libUE4.so', 'unreal5': 'libUnreal.so',
    'xamarin': 'libmonodroid.so', 'qt': 'libQt5Core', 'qt6': 'libQt6Core',
    'cocos': 'libcocos', 'love': 'liblove.so', 'renpy': 'librenpy',
    'kivy': 'libpython', 'gomobile': 'libgojni.so',
}


def arsc_keys(url, entries):
    comp, csize, lho = entries['resources.arsc']
    h = zipcd.rng(url, lho, lho + 29)
    nl, el = struct.unpack('<HH', h[26:30])
    base = lho + 30 + nl + el
    if comp == 8:
        blob = zlib.decompress(zipcd.rng(url, base, base + csize - 1), -15)
        read = lambda o, n: blob[o:o + n]
    elif comp == 0:
        read = lambda o, n: zipcd.rng(url, base + o, base + o + n - 1)
    else:
        raise ValueError(f'arsc compression {comp}')
    th = read(0, 12)
    if struct.unpack('<H', th[:2])[0] != 2:
        raise ValueError('not a ResTable')
    off = struct.unpack('<H', th[2:4])[0]
    pools = []
    total = struct.unpack('<I', th[4:8])[0]
    while off < total:
        ch = read(off, 8)
        ctype, chdr, csz = struct.unpack('<HHI', ch)
        if ctype == 0x0200:  # package
            ph = read(off, 288)
            key_off = struct.unpack('<I', ph[8 + 4 + 256 + 8:8 + 4 + 256 + 12])[0]
            kh = read(off + key_off, 8)
            ksz = struct.unpack('<I', kh[4:8])[0]
            pools.append(read(off + key_off, ksz))
        if csz <= 0:
            break
        off += csz
    return b''.join(pools)


def scan(pkg, meta, ver):
    f = ver['file']
    url = REPO + f['name']
    m = ver['manifest']
    r = {'pkg': pkg, 'vc': m.get('versionCode'), 'vn': m.get('versionName'),
         'apk': url, 'size': f.get('size')}
    try:
        names, entries, _ = zipcd.list_names(url, f['size'])
        libs = {n for n in names if n.startswith('lib/')}
        r['frameworks'] = sorted(k for k, s in LIBS.items() if any(s in n for n in libs))
        r['abis'] = sorted({n.split('/')[1] for n in libs if n.count('/') >= 2})
        r['metainf_compose'] = any(n.startswith('META-INF/androidx.compose.ui') for n in names)
        r['assets_bin_data'] = any(n.startswith('assets/bin/Data/') for n in names)
        if 'resources.arsc' in entries:
            kp = arsc_keys(url, entries)
            for k, pats in KEYS.items():
                r[k] = any(p in kp or p.decode().encode('utf-16-le') in kp for p in pats)
        else:
            r['no_arsc'] = True
    except Exception as e:  # keep going; record the failure
        r['error'] = f'{type(e).__name__}: {e}'[:200]
    return r


def main():
    idx = json.load(open(IDX))
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try:
                r = json.loads(line)
                done.add((r['pkg'], r.get('vc')))
            except Exception:
                pass
    jobs = []
    for pkg, p in idx['packages'].items():
        if not p.get('versions'):
            continue
        ver = pick_version(p)
        if (pkg, ver['manifest'].get('versionCode')) not in done:
            jobs.append((pkg, p['metadata'], ver))
    print(f'{len(done)} done, {len(jobs)} to scan', flush=True)
    lock = threading.Lock()
    n = 0
    with open(OUT, 'a') as out, ThreadPoolExecutor(int(os.environ.get('WORKERS', '12'))) as ex:
        futs = [ex.submit(scan, *j) for j in jobs]
        for fu in as_completed(futs):
            r = fu.result()
            with lock:
                out.write(json.dumps(r) + '\n'); out.flush()
                n += 1
                if n % 100 == 0:
                    print(f'{n}/{len(jobs)}', flush=True)
    print('finished', flush=True)


if __name__ == '__main__':
    main()
