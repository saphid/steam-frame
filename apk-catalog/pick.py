"""Choose which F-Droid version of an app to rate and install.

F-Droid often publishes one APK per ABI under different version codes, and
the highest code is frequently the x86_64 build. Prefer the newest version
Lepton can install (arm64-v8a or no native code, minSdk <= 30), else the newest.
"""
LEPTON_SDK = 30


def installable(v):
    m = v['manifest']
    native = m.get('nativecode') or []
    return (not native or 'arm64-v8a' in native) and \
        m.get('usesSdk', {}).get('minSdkVersion', 1) <= LEPTON_SDK


def pick_version(p):
    vs = sorted(p['versions'].values(), key=lambda v: v['manifest'].get('versionCode', 0), reverse=True)
    return next((v for v in vs if installable(v)), vs[0])
