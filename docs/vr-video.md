# Watching VR video (180°/360°) on the Frame

The confidence labels are the same as in [ssh.md](ssh.md). Everything here
was checked on SteamOS 0.3.0, build 20260922.6101926.

## The short version

1. Install **DeoVR Video Player** from Steam (free, app 837380) and start it once
   in the headset. That creates its Proton prefix.
2. On the Mac: `scripts/push-vr-video.sh --launch ~/Movies/beach_180_LR.mp4`
3. In the headset, open DeoVR's local file browser → **Videos → VR** and
   pick the file.

## Why DeoVR

The Frame's Chromium can't play VR video in 3D. It has no immersive WebXR
([how-the-frame-works.md](how-the-frame-works.md)). DeoVR's Windows build
runs under Proton ARM64 + FEX as a real SteamVR app. **Verified 2026-09-25:**
it found the Steam Frame headset and controller over OpenVR, and decoded
7680×3840 and 8192×4096 H.265 VR180 side-by-side streams through AVPro's
hardware Media Foundation path, mapped onto a 180° dome or fisheye mesh.

Known quirks (verified):

- The first launch takes about 45 s while it compiles shaders.
- Grid thumbnails stay blank. Unity's own video player, which DeoVR uses for
  previews, fails with `0xc00d36bb` under Proton. Full playback uses AVPro
  and isn't affected.
- The in-app store and web content are separate from local files. You don't
  need an account to play your own files.

## Getting files onto the headset

`scripts/push-vr-video.sh` copies files with `rsync --partial`, so an
interrupted upload resumes. They go to `~/Videos/VR` on the Frame (`/home`
has about 860 GB free). The script also links that folder into DeoVR's prefix
as `C:\users\steamuser\Videos\VR`. It's reachable at
`Z:\home\steamos\Videos\VR` as well. **Verified** that the upload and link
work. **Not yet checked** whether DeoVR's file browser lands there
(open question 21).

Speed: a test upload over Wi-Fi ran at about 3–5 MB/s (verified 2026-09-25,
one sample). At that rate an 8K file of several GB takes tens of minutes, so
start big uploads before you put the headset on.

## Naming files so they play correctly

DeoVR guesses the projection from the file name. Its binary contains the tags
`_180`, `_360`, `_fisheye`, `_fisheye190`, `_mkx200`, `_vrca220` and `_rf52`
(verified). For stereo layout, the common DeoVR convention is `_LR`/`_SBS`
(side by side) and `_TB` (top/bottom) (inferred). If a video looks wrong
(doubled, warped, or flat), change the projection and stereo mode in DeoVR's
player menu.

Examples: `trip_180_LR.mp4`, `concert_360_TB.mp4`, `hike_fisheye190_LR.mp4`.

Codecs: H.265 at 8K played (verified, streamed). Local H.264 and H.265
files haven't been played yet. The test clips below cover that.

## Test clips

The script doesn't include these. To check a setup, make two 20 s clips:
3840×1920, 180° side by side, with the left eye tinted red and the right eye
cyan. In the headset each eye should see only its own colour. A single mixed
colour means the stereo split is wrong.

```sh
ffmpeg -f lavfi -i testsrc2=size=1920x1920:rate=30:duration=20 \
  -filter_complex "[0:v]split[a][b];[a]colorchannelmixer=rr=1:gg=0.3:bb=0.3[l];[b]colorchannelmixer=rr=0.3:gg=1:bb=1[r];[l][r]hstack" \
  -c:v libx264 -pix_fmt yuv420p -b:v 20M frame-test_180_LR_h264.mp4
scripts/push-vr-video.sh frame-test_180_LR_h264.mp4
```

## Streaming from the Mac instead of copying (untested)

DeoVR has a DLNA browser (the binary contains `Searching for DLNA
devices...` and a UPnP ContentDirectory client). A DLNA server on the Mac
should therefore appear in DeoVR without copying anything, for example
`brew install rclone` then `rclone serve dlna ~/Movies/VR`. This is **inferred**, not
tried. 8K VR video needs roughly 50–100 Mbit/s sustained, and the Wi-Fi
sample above (about 30–40 Mbit/s) suggests copying first is the safer default.
