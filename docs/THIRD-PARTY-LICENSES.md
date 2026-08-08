# Reframe — third-party redistributables and the FFmpeg written source offer

> **Status:** ACTIVE. · **Date:** 2026-08-08
> **Charter:** the only place Reframe's obligations for REDISTRIBUTED BINARIES are
> recorded. Bundled ML **models** and **fonts** are a different surface and are owned
> by `app/renderer/src/features/ThirdPartyNotices.tsx` (Settings → Licenses), which
> renders them in-app; this file is the binary-redistribution half, and it is where
> the GPL written offer lives because an offer has to be a durable, quotable text.

## 1. FFmpeg — GPL-3.0-or-later (the written source offer)

Reframe ships **unmodified** `ffmpeg.exe` and `ffprobe.exe` binaries inside the
Windows installer at `resources/bin/`. They are prebuilt by the BtbN FFmpeg-Builds
project, and the exact artifact is pinned by URL **and** SHA-256 in
`build/python-embed-setup.ps1`:

| field | value |
|---|---|
| project | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) |
| release tag | `autobuild-2026-06-30-13-34` |
| asset | `ffmpeg-n7.1.5-1-g7d0e842004-win64-gpl-7.1.zip` |
| asset SHA-256 | `405b190f746db40539eb453967f72c0e69d8bf260b10ceff36e0c2149a9ad22f` |
| FFmpeg version | `n7.1.5-1-g7d0e842004` (upstream commit `7d0e842004`) |
| licence | **GPL-3.0-or-later** (`--enable-gpl` **and** `--enable-version3`) |
| licence text shipped | `resources/bin/LICENSE.txt` (verbatim GNU GPL v3) |

**Written offer.** The corresponding source for these binaries is the FFmpeg source
at the exact upstream commit above, together with the build recipe that produced
them. Both are publicly available and permanently fetchable:

- FFmpeg source, exact revision:
  `https://github.com/FFmpeg/FFmpeg/tree/7d0e842004`
  (equivalently `git clone https://git.ffmpeg.org/ffmpeg.git && git checkout 7d0e842004`)
- Upstream project + release page: `https://ffmpeg.org/download.html`
- The build scripts and Dockerfiles that produced this exact binary:
  `https://github.com/BtbN/FFmpeg-Builds` at tag `autobuild-2026-06-30-13-34`
- The GPL-licensed encoder libraries linked into it, notably
  x264 (`https://code.videolan.org/videolan/x264`) and
  x265 (`https://bitbucket.org/multicoreware/x265_git`).

If you would prefer to receive the corresponding source on a physical medium rather
than by download, contact the address in [`SECURITY.md`](../SECURITY.md) and it will
be provided for no more than the cost of distribution.

**Why GPL and not LGPL — and why that does not relicense Reframe.** FFmpeg is
LGPL-2.1+ in its default configuration, but the software H.264/H.265 encoders
(`libx264`, `libx265`) are GPL-only, so a build that has them is GPL. Reframe needs
`libx264`: it is the encoder every export path names (see
`media_studio.ffmpeg.H264_ENCODER`). The previously shipped LGPL build was
configured `--disable-libx264`, which made **every export in the product fail** with
`Unknown encoder 'libx264'`.

Reframe does not link FFmpeg. The sidecar resolves an absolute path
(`media_studio/ffmpeg.py::resolve_binary`) and spawns the executable as a **separate
child process** over an argv list (`media_studio/ffmpeg.py::run`) — no library call,
no `shell=True`, no FFmpeg code in Reframe's address space. That is aggregation of
independent works, so the GPL does not extend to Reframe's own source. What it does
require, and what this section discharges, is that anyone who receives the binary can
get its corresponding source.

**If you rebuild or re-pin.** Changing `$FfmpegUrl` in
`build/python-embed-setup.ps1` changes what is redistributed, so the table above and
the `FFMPEG_NOTICE` entry in `app/renderer/src/features/ThirdPartyNotices.tsx` must
be updated in the same commit. `sidecar/tests/test_ffmpeg_encoders.py` fails the
build if the pin drifts back to a `-win64-lgpl-` asset.

## 2. Embeddable CPython — PSF-2.0

`resources/python/` and `resources/python-chatterbox/` are the unmodified
embeddable CPython distributions from python.org (3.12.10 and 3.14.0), pinned by URL
and SHA-256 in the same script. The PSF licence text ships with each distribution as
`LICENSE.txt`. It is a permissive licence with no source-offer obligation.

## 3. Bundled models and fonts

Owned by the in-app Settings → Licenses surface, not by this file:
`app/renderer/src/features/ThirdPartyNotices.tsx`. It reproduces each model's
attribution and carries the **non-commercial** callout for ViNet-S
(CC-BY-NC-SA-4.0), plus the OFL-1.1 notices for the bundled type trio.
