#!/bin/bash
# Frame-side: run one Android app in its own persistent Lepton instance.
# Copied into ~/Applications/Android/<package>/launch.sh by the Mac-side
# installer, next to app.apk, instance.id and (for 2D apps) the empty
# lepton-show-flatscreen marker. A non-Steam shortcut points at this file.
#
# Why not Lepton Development: it wipes every app it installed when it exits.
# A "steamlaunch" context (SteamAppId set) keeps app data in
# compatdata/<id>/internal across restarts and APK updates. Pattern from
# frame/t3code/launch.sh; see docs/apks.md.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LEPTON="$HOME/.local/share/Steam/steamapps/common/Lepton/lepton"
[[ -x "$LEPTON" ]] || { echo "Lepton isn't installed (Steam app 3056000)" >&2; exit 1; }
for need in "$DIR/app.apk" "$DIR/instance.id"; do
  [[ -f "$need" ]] || { echo "launch.sh: missing $need" >&2; exit 1; }
done

# A number that isn't a real Steam app; it names this app's Lepton context.
export SteamAppId="$(cat "$DIR/instance.id")"
export STEAM_COMPAT_INSTALL_PATH="$DIR"
# Must be under ~/.local/share/Steam: only that tree is mounted in the container.
export STEAM_COMPAT_DATA_PATH="$HOME/.local/share/Steam/steamapps/compatdata/$SteamAppId"
export STEAM_COMPAT_SHADER_PATH="$HOME/.local/share/Steam/steamapps/shadercache/$SteamAppId"
export STEAM_FOSSILIZE_DUMP_PATH="$STEAM_COMPAT_SHADER_PATH/fozpipelinesv6/steamapp_pipeline_cache"
mkdir -p "$STEAM_COMPAT_DATA_PATH" "$STEAM_FOSSILIZE_DUMP_PATH"

# Lepton's setpgid --foreground re-exec needs a terminal that Steam shortcuts
# and SSH don't have; give it its own session instead.
export IS_PARENT=true
exec setsid --wait "$LEPTON" waitforexitandrun -- "$DIR/app.apk"
