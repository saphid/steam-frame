"""Merge the F-Droid index, both APK scans and the on-device results into
site/apps.js, applying the Lepton compatibility rules in docs/apks.md.

Usage: python3 build.py   (run from apk-catalog/, after scan.py and scan2.py)
"""
import json, os, re, time
from pick import pick_version, LEPTON_SDK
import reports

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
REPO = 'https://f-droid.org/repo'
# Compose UI below this crashes on any Compose screen: it casts the missing
# clipboard service to non-null while building AndroidComposeView.
COMPOSE_OK = (1, 11)
RANK = {'works': 0, 'likely': 1, 'maybe': 2, 'unlikely': 3, 'no': 4}


def jsonl(path):
    if not os.path.exists(path):
        return {}
    return {r['pkg']: r for r in map(json.loads, open(path))}


def loc(d):
    if not isinstance(d, dict):
        return d or ''
    return d.get('en-US') or d.get('en') or next(iter(d.values()), '')


def ver_tuple(v):
    m = re.match(r'(\d+)\.(\d+)', v or '')
    return (int(m[1]), int(m[2])) if m else None


def classify(m, s, s2):
    """Return (verdict, reasons). Hard failures first, then crash signals."""
    no, bad, maybe, notes = [], [], [], []
    min_sdk = m.get('usesSdk', {}).get('minSdkVersion', 1)
    if min_sdk > LEPTON_SDK:
        no.append(f'Needs Android API {min_sdk}; Lepton is Android 11 (API 30), so it won\'t install')
    native = m.get('nativecode') or s.get('abis') or []
    if native and 'arm64-v8a' not in native:
        no.append(f'Native code only for {", ".join(native)}; Lepton is 64-bit ARM only, so it won\'t install')

    cv = s2.get('compose_ver')
    if cv and ver_tuple(cv) and ver_tuple(cv) < COMPOSE_OK:
        bad.append(f'Jetpack Compose {cv}: Compose screens crash (no clipboard service); 1.11+ is fine')
    elif s.get('compose') and not cv:
        maybe.append('Uses Jetpack Compose, version unknown: crashes if older than 1.11')
    elif cv:
        notes.append(f'Jetpack Compose {cv} (fine)')
    fw = set(s.get('frameworks', []))
    if 'sdl' in fw or s2.get('sdl3'):
        bad.append('SDL app: registers a clipboard listener at start-up and crashes')
    if 'kivy' in fw:
        bad.append('Kivy (SDL) app: crashes at start-up on the missing clipboard')
    if 'godot' in fw:
        maybe.append('Godot: 4.3 crashed (clipboard), 4.6 worked')
    if 'reactnative' in fw or 'hermes' in fw:
        notes.append('React Native: 2 of 3 tested apps worked')
    if 'qt' in fw or 'qt6' in fw:
        maybe.append('Qt app: the one tested crashed on a missing libc++ symbol')
    if 'flutter' in fw:
        notes.append('Flutter (tested apps worked)')
    if 'gdx' in fw:
        notes.append('libGDX (tested games worked)')
    if s.get('gms') or s2.get('gms_meta'):
        maybe.append('Uses Google Play Services, which Lepton lacks')
    if s2 and not s2.get('launcher'):
        if s2.get('ime'):
            maybe.append('Keyboard (IME), not an app you open; untested in Lepton')
        else:
            maybe.append('No launcher icon (widget, tile, wallpaper or plug-in)')
    feats = s2.get('features', [])
    if 'android.hardware.touchscreen.multitouch' in feats:
        notes.append('Mentions multi-touch; the Frame pointer is single-touch (inferred)')
    if any(f in feats for f in ('android.hardware.telephony', 'android.hardware.nfc')):
        notes.append('Mentions telephony or NFC, which Lepton lacks')
    if 'android.hardware.type.watch' in feats:
        maybe.append('Wear OS watch app')

    if no:
        return 'no', no + bad + maybe + notes
    if bad:
        return 'unlikely', bad + maybe + notes
    if maybe:
        return 'maybe', maybe + notes
    if not s or 'error' in s:
        return 'maybe', ['APK not scanned'] + notes
    return 'likely', notes or ['No known blockers']


def finalize(app, reps):
    """Set the shown verdict ('r', 'why', 't') from the prediction plus any reports."""
    rv = reports.verdict(reps)
    if rv:
        app['r'], lines = rv
        app['why'] = lines + ['Rule check: ' + r for r in app['pw'] if not r.startswith('No known')]
    else:
        app['r'], app['why'] = app['pr'], list(app['pw'])
    app['t'] = bool(rv)
    return app


def load_catalog(path=None):
    """Read site/apps.js back into a list (for serve.py and Frame Control)."""
    src = open(path or os.path.join(HERE, 'site', 'apps.js'), encoding='utf-8').read()
    return json.loads(src.split('window.APPS=', 1)[1].rstrip().rstrip(';'))


def main():
    idx = json.load(open(os.path.join(DATA, 'index-v2.json')))
    s1 = jsonl(os.path.join(DATA, 'scan.jsonl'))
    s2 = jsonl(os.path.join(DATA, 'scan2.jsonl'))
    pins = json.load(open(os.path.join(HERE, 'pins.json'))) if os.path.exists(os.path.join(HERE, 'pins.json')) else {}
    cats = idx.get('repo', {}).get('categories', {})
    apps = []
    for pkg, p in idx['packages'].items():
        if not p.get('versions'):
            continue
        v = pick_version(p)
        md, m = p['metadata'], v['manifest']
        verdict, why = classify(m, s1.get(pkg, {}), s2.get(pkg, {}))
        apk, sha, shown_ver = REPO + v['file']['name'], v['file'].get('sha256'), m.get('versionName')
        pin = pins.get(pkg)
        if pin:
            apk, sha, shown_ver = pin['apk'], pin['sha256'], pin['version']
            why = [pin['why']] + why
        icon = loc(md.get('icon'))
        apps.append(finalize({
            'p': pkg,
            'n': loc(md.get('name')) or pkg,
            's': loc(md.get('summary')),
            'c': [loc(cats.get(c, {}).get('name')) or c for c in md.get('categories', [])],
            'i': REPO + icon['name'] if isinstance(icon, dict) and icon.get('name') else '',
            'v': shown_ver,
            'z': v['file'].get('size'),
            'u': md.get('lastUpdated'),
            'a': apk,
            'h': sha,
            'af': sorted(v.get('antiFeatures', {}).keys()),
            'pr': verdict,
            'pw': why,
        }, None))
    apps.sort(key=lambda a: (RANK[a['r']], a['n'].lower()))
    out = os.path.join(HERE, 'site', 'apps.js')
    meta = {'built': time.strftime('%Y-%m-%d'), 'count': len(apps),
            'source': 'F-Droid main repo, rated on the newest version each app has that Lepton can install'}
    with open(out, 'w') as f:
        f.write('window.CATALOG_META=' + json.dumps(meta) + ';\n')
        f.write('window.APPS=' + json.dumps(apps, separators=(',', ':'), ensure_ascii=False) + ';\n')
    counts = {k: sum(a['r'] == k for a in apps) for k in RANK}
    print(out, counts)


if __name__ == '__main__':
    main()
