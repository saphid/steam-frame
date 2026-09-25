#!/bin/bash
# Frame-side: run T3 Code in its own Lepton (Android) instance whose data
# survives restarts. Lepton Development wipes its apps when it exits; a
# "steamlaunch" context (SteamAppId set) keeps them.
#
# Lives in ~/Applications/T3Code next to t3code.apk and the empty
# lepton-show-flatscreen marker (without it Lepton runs the app headless).
#
# App data (T3's pairing) lives in compatdata/<id>/internal and survives
# everything. Lepton rebuilds its Android system snapshot (compatdata/<id>/baked)
# when the APK changes or the app exits within 30 seconds of starting.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LEPTON="$HOME/.local/share/Steam/steamapps/common/Lepton/lepton"

# Without the marker Lepton runs T3 headless: Steam says "running" but no panel
# appears. Fail loudly instead.
for need in "$DIR/t3code.apk" "$DIR/lepton-show-flatscreen"; do
  [[ -f "$need" ]] || { echo "launch.sh: missing $need" >&2; exit 1; }
done
[[ -x "$LEPTON" ]] || { echo "launch.sh: Lepton not installed at $LEPTON" >&2; exit 1; }

# Any fixed number that isn't a real Steam app: it names the Lepton context.
export SteamAppId=2873873873
export STEAM_COMPAT_INSTALL_PATH="$DIR"
# Must sit under ~/.local/share/Steam: Lepton symlinks /data/data/<app> and
# /data/media/0 to host paths here, and only the Steam dir is mounted inside.
export STEAM_COMPAT_DATA_PATH="$HOME/.local/share/Steam/steamapps/compatdata/$SteamAppId"
# A Steam shortcut launch sets STEAM_FOSSILIZE_DUMP_PATH but not the shader
# path Lepton derives it from (unbound under `set -u`), so set both.
export STEAM_COMPAT_SHADER_PATH="$HOME/.local/share/Steam/steamapps/shadercache/$SteamAppId"
export STEAM_FOSSILIZE_DUMP_PATH="$STEAM_COMPAT_SHADER_PATH/fozpipelinesv6/steamapp_pipeline_cache"
mkdir -p "$STEAM_COMPAT_DATA_PATH" "$STEAM_FOSSILIZE_DUMP_PATH"

# Lepton re-execs itself through `setpgid --foreground`, which needs a
# controlling terminal that Steam shortcuts and systemd don't have. Skip that
# step and give Lepton its own session instead: its teardown kills its whole
# process group. --wait keeps this script alive so Steam sees the app running.
export IS_PARENT=true
exec setsid --wait "$LEPTON" waitforexitandrun -- "$DIR/t3code.apk"
