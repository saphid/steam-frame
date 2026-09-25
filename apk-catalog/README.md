# Android app catalogue and compatibility reports

The data behind Frame Control's **Android apps** section: every app in the
F-Droid main repo, rated for Lepton (the Frame's Android container), plus our
own compatibility reports. No ProtonDB-style database for sideloaded Android
apps on the Frame existed as of 2026-09-25 (Steam Frame Hub and Valve's
"Great on Frame" cover Steam games only), so we keep our own.

```sh
scripts/frame-ui.sh        # Frame Control → Android apps: search, Install, Test, Report
scripts/apk-catalog.sh     # refresh the F-Droid data (only scans what changed)
```

## Verdicts

| Verdict | Meaning |
|---|---|
| Works on Frame | The latest report says it runs (automated Test or a person's rating) |
| Should work | No known blocker found in the APK |
| Might work | Something uncertain: Compose version unknown, Godot, Qt, Play Services, no launcher icon (widgets, tiles, keyboards), or a report of issues |
| Probably crashes | Compose UI < 1.11, SDL or Kivy |
| Won't work | Needs Android 12+ or has no 64-bit ARM build, or a report says it's broken |

"Should work" means the app opens. Features that need something Lepton lacks
(browser links, file picker, Play Services, camera app) can still fail. The
rules and the evidence behind them are in [docs/apks.md](../docs/apks.md).

## Compatibility reports

Reports live in Frame Control's private database, a Lakebed capsule at
`https://frame-compat.lakebed.app` that only the app can read or write (see
[compat-db/README.md](../compat-db/README.md), including backups). **Test**
records whether an app stays up in its own instance (`result`); **Report**
(on any installed app, catalogue card, or **+ Report an APK** for anything else, e.g. an
APK file or your own build) records `works`, `issues` or `broken`, how it was run
(own instance, Lepton Development, other), where the APK came from, and notes. Each report carries
the SteamOS `BUILD_ID` and the Lepton build id. Newest wins, and a person's
rating beats an automated result (`reports.py`).

## Files

| File | Role |
|---|---|
| `zipcd.py` | Reads an APK's zip directory and single entries with HTTP range requests |
| `scan.py` | Per app: native ABIs, frameworks (from `lib/*.so`), Compose/GMS/Firebase resource names from `resources.arsc`. Writes `data/scan.jsonl` |
| `scan2.py` | Per app: Compose UI version, launcher/IME/feature strings from `AndroidManifest.xml`. Writes `data/scan2.jsonl` |
| `pick.py` | Which version to rate and install: newest with an arm64 build (or no native code) and minSdk ≤ 30 |
| `pins.json` | Versions pinned by hand (F-Droid 1.17.2) |
| `reports.py` | How reports override predictions (the reports are in compat-db) |
| `build.py` | Applies the rules and writes `site/apps.js` (predictions; Frame Control adds reports at runtime) |

Frame Control's `ui/frame_catalog.py` loads `site/apps.js`, applies the
reports from `ui/frame_compat_db.py`, downloads APKs (SHA-256 checked against the
F-Droid index), and installs them with `ui/frame_android.py`.

Both scans skip apps whose version hasn't changed. Compose is detected by its
resource ids (`compose_view_saveable_id_tag`) because many apps strip the
`META-INF` version files; those apps are rated "Might work".
