// ThirdPartyNotices.tsx — the user-facing third-party model attributions.
//
// Reframe bundles several third-party ML models. Two of them carry copyleft /
// attribution obligations that REQUIRE a user-facing notice (security review
// HIGH#1b): ViNet-S is CC-BY-NC-SA-4.0, which mandates attribution + a
// non-commercial callout. This is the minimal "Licenses" surface reachable from
// Settings → Licenses (WU-F1); it reproduces each bundled model's attribution
// block and points at the vendored LICENSE files that carry the full text.
//
// PURE + static: the notices are compile-time constants (facts about the bundled
// build), so this component holds no state and opens no RPC — it just renders the
// notice list. The vendored LICENSE files it references live under
// `sidecar/media_studio/features/_vinet_s/LICENSE` and `_transnetv2/LICENSE`.
import React from 'react';
import './thirdPartyNotices.css';

/** One bundled third-party model's attribution + license record. */
export interface ModelNotice {
  /** Stable key + display name of the model. */
  name: string;
  /** What the model does in Reframe (one line). */
  role: string;
  /** SPDX license id (e.g. `MIT`, `Apache-2.0`, `CC-BY-NC-SA-4.0`). */
  license: string;
  /** Canonical URL of the license text. */
  licenseUrl: string;
  /** True when the license permits commercial use; false = non-commercial only. */
  commercial: boolean;
  /** Copyright / authors attribution line (reproduced verbatim). */
  attribution: string;
  /** Upstream source coordinates (repo URL). */
  source: string;
  /** Optional academic citation (paper + arXiv id). */
  paper?: string;
  /** Optional repo-relative path of the vendored full LICENSE file. */
  licenseFile?: string;
  /** Optional extra obligation callout (e.g. the non-commercial notice). */
  note?: string;
}

/**
 * The bundled third-party models, in the order they appear in the pipeline.
 * These are FACTS about the shipped build, kept in sync with the sidecar's
 * `assets/manifest.py` provenance and the vendored `_vinet_s` / `_transnetv2`
 * package headers. The ViNet-S entry carries the mandatory non-commercial notice.
 */
export const THIRD_PARTY_NOTICES: readonly ModelNotice[] = [
  {
    name: 'YuNet',
    role: 'face detector (default speaker tracking)',
    license: 'MIT',
    licenseUrl: 'https://opensource.org/license/mit',
    commercial: true,
    attribution: '© 2020 Shiqi Yu (opencv/face_detection_yunet)',
    source: 'https://github.com/opencv/opencv_zoo',
  },
  {
    name: 'EdgeTAM',
    role: 'opt-in occlusion-robust video tracker',
    license: 'Apache-2.0',
    licenseUrl: 'https://www.apache.org/licenses/LICENSE-2.0',
    commercial: true,
    attribution: '© Meta Platforms, Inc. (facebookresearch/EdgeTAM)',
    source: 'https://github.com/facebookresearch/EdgeTAM',
  },
  {
    name: 'TransNetV2',
    role: 'shot-transition / scene-cut detector',
    license: 'MIT',
    licenseUrl: 'https://opensource.org/license/mit',
    commercial: true,
    attribution: '© 2020 Tomáš Souček (soCzech/TransNetV2)',
    source: 'https://github.com/soCzech/TransNetV2',
    licenseFile: 'sidecar/media_studio/features/_transnetv2/LICENSE',
  },
  {
    name: 'LR-ASD',
    role: 'visual active-speaker detection',
    license: 'MIT',
    licenseUrl: 'https://opensource.org/license/mit',
    commercial: true,
    attribution: '© 2025 Liao Junhua (Junhua-Liao/LR-ASD)',
    source: 'https://github.com/Junhua-Liao/LR-ASD',
  },
  {
    name: 'ViNet-S / ViNet',
    role: 'video saliency model (no-face crop tracking)',
    license: 'CC-BY-NC-SA-4.0',
    licenseUrl: 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
    commercial: false,
    attribution:
      '© 2025 Rohit Girmaji, Siddharth Jain, Bhav Beri, Sarthak Bansal, Vineet Gandhi (IIIT Hyderabad)',
    source: 'https://github.com/ViNet-Saliency/vinet_v2',
    paper: 'ViNet-S / ViNet (ICASSP 2025), arXiv:2502.00397',
    licenseFile: 'sidecar/media_studio/features/_vinet_s/LICENSE',
    note:
      'NON-COMMERCIAL: this model is licensed for personal / non-commercial use only, with ' +
      'attribution and share-alike. Reframe is therefore NON-COMMERCIAL while ViNet-S is bundled — ' +
      'a future paid tier must remove or replace this model.',
  },
];

/** One bundled self-hosted font's OFL attribution record. */
export interface FontNotice {
  /** Family name (matches the tokens.css lead + the fonts.css @font-face). */
  name: string;
  /** Which type token the family binds, in one line. */
  role: string;
  /** SPDX-style license id — always `OFL-1.1` for the bundled trio. */
  license: string;
  /** Canonical URL of the license text. */
  licenseUrl: string;
  /** OFL is permissive: commercial use is permitted for all three. */
  commercial: boolean;
  /** Verbatim copyright line reproduced from the upstream OFL.txt. */
  attribution: string;
  /** Upstream source repository. */
  source: string;
}

/** Repo-relative path of the vendored full OFL license + copyright notices. */
export const FONT_LICENSE_FILE = 'renderer/src/assets/fonts/OFL.txt';

/**
 * The self-hosted UI type trio (renderer/src/assets/fonts/*.woff2, bound in
 * styles/fonts.css). All three are SIL OFL 1.1 — permissive, commercial-OK — so
 * they carry no obligation like ViNet-S's; the copyright lines below are
 * reproduced verbatim from each family's upstream OFL.txt to satisfy the OFL's
 * attribution condition in the shipped UI, not just documentation.
 */
export const FONT_NOTICES: readonly FontNotice[] = [
  {
    name: 'Inter',
    role: 'UI typeface — dense-interface legibility (--font-ui)',
    license: 'OFL-1.1',
    licenseUrl: 'https://openfontlicense.org',
    commercial: true,
    attribution: 'Copyright 2020 The Inter Project Authors',
    source: 'https://github.com/rsms/inter',
  },
  {
    name: 'Newsreader',
    role: 'Editorial serif — the pull-quote voice (--font-editorial)',
    license: 'OFL-1.1',
    licenseUrl: 'https://openfontlicense.org',
    commercial: true,
    attribution: 'Copyright 2020 The Newsreader Project Authors',
    source: 'https://github.com/productiontype/Newsreader',
  },
  {
    name: 'IBM Plex Mono',
    role: 'Monospace — timecode & numerals (--font-mono)',
    license: 'OFL-1.1',
    licenseUrl: 'https://openfontlicense.org',
    commercial: true,
    attribution: 'Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"',
    source: 'https://github.com/IBM/plex',
  },
];

/**
 * A REDISTRIBUTED third-party BINARY (an executable shipped inside the installer),
 * as opposed to a model's weights. Copyleft binaries carry a source-offer
 * obligation, so this record is revision-exact where a model notice is not.
 */
export interface BinaryNotice {
  /** Display name. */
  name: string;
  /** What it does in Reframe (one line). */
  role: string;
  /** SPDX license id. */
  license: string;
  /** Canonical URL of the license text. */
  licenseUrl: string;
  /** Upstream version string, as the binary itself reports it. */
  version: string;
  /** The prebuilt-release tag the shipped artifact came from. */
  buildTag: string;
  /** The exact release asset file name. */
  asset: string;
  /** SHA-256 of that asset (the pin enforced at build-prep time). */
  sha256: string;
  /** The corresponding SOURCE at the exact revision — the GPL offer. */
  sourceUrl: string;
  /** The build recipe that produced the binary from that source. */
  buildScriptsUrl: string;
  /** Where the full license text ships, relative to the install root. */
  licenseFile: string;
  /** The obligation/scope callout shown to the user. */
  note: string;
}

/**
 * FFmpeg — the one copyleft BINARY Reframe redistributes.
 *
 * Kept in lockstep with `build/python-embed-setup.ps1` ($FfmpegUrl +
 * $ExpectedFfmpegSha256), `electron-builder.yml`, and the written offer in
 * `docs/THIRD-PARTY-LICENSES.md`. Re-pinning ffmpeg means editing all four.
 *
 * WHY GPL AND NOT LGPL: the software H.264/H.265 encoders are GPL-only, and
 * `libx264` is the encoder every Reframe export names. The LGPL build shipped
 * previously was `--disable-libx264`, so every export failed outright. Correcting
 * the pin to the GPL build is what makes the product work, and it brings the
 * source-offer obligation this notice discharges.
 */
export const FFMPEG_NOTICE: BinaryNotice = {
  name: 'FFmpeg',
  role: 'media decode/encode — every import, reframe, caption burn and export',
  license: 'GPL-3.0-or-later',
  licenseUrl: 'https://www.gnu.org/licenses/gpl-3.0.html',
  version: 'n7.1.5-1-g7d0e842004',
  buildTag: 'autobuild-2026-06-30-13-34',
  asset: 'ffmpeg-n7.1.5-1-g7d0e842004-win64-gpl-7.1.zip',
  sha256: '405b190f746db40539eb453967f72c0e69d8bf260b10ceff36e0c2149a9ad22f',
  sourceUrl: 'https://github.com/FFmpeg/FFmpeg/tree/7d0e842004',
  buildScriptsUrl: 'https://github.com/BtbN/FFmpeg-Builds',
  licenseFile: 'resources/bin/LICENSE.txt',
  note:
    'Reframe ships this FFmpeg build UNMODIFIED and runs it as a separate child process, ' +
    'never as a linked library. Reframe’s own source is therefore not covered by the GPL. ' +
    'You are entitled to the corresponding source for the binary itself, linked above at the ' +
    'exact revision it was built from.',
};

/**
 * An OPT-IN model: not in the shipped asset set at all, downloaded only when the
 * user enables the feature that needs it. Distinct from `ModelNotice` (bundled
 * weights) because the obligation is different in kind: these carry a
 * Responsible-AI (OpenRAIL) licence, which PERMITS commercial use but attaches
 * enforceable behavioural use-restrictions that the licence requires be passed
 * on to downstream users — so the notice has to state the restriction, not just
 * credit the author.
 */
export interface OptInModelNotice {
  /** Display name. */
  name: string;
  /** What it does in Reframe (one line). */
  role: string;
  /** The feature setting that gates the download + the code path. */
  gatedBy: string;
  /** SPDX-ish id of the WEIGHTS licence (the Hub tag). */
  weightsLicense: string;
  /** Canonical URL of the weights licence text. */
  weightsLicenseUrl: string;
  /** SPDX id of the source-CODE licence, which frequently differs. */
  codeLicense: string;
  /** True when the licence permits commercial use. OpenRAIL: true. */
  commercial: boolean;
  /** True when the licence attaches behavioural use-restrictions. OpenRAIL: true. */
  useRestricted: boolean;
  /** Copyright / authors attribution line. */
  attribution: string;
  /** Upstream weights coordinates. */
  source: string;
  /** Optional academic citation (paper + arXiv id). */
  paper?: string;
  /** The obligation/scope callout shown to the user. */
  note: string;
}

/**
 * The lip-sync engines (WU-B1) — OPT-IN, `lipSyncEnabled`-gated, never in the
 * default asset set.
 *
 * LICENCE FACTS VERIFIED 2026-08-08 by two mechanically independent probes: the
 * Hub API metadata for each repo, and a raw fetch of the repo's own README YAML
 * frontmatter. Kept in lockstep with `sidecar/media_studio/features/tts/lipsync.py`
 * `ENGINES`, and a sidecar test reads THIS FILE and fails if the two disagree —
 * a licence claim is exactly the sort of duplicated fact that must not drift.
 *
 * SCOPE OF `weightsLicenseUrl` — measured, and narrower than it looks: NEITHER
 * repo ships a licence file (`find hf://models/ByteDance/LatentSync-1.6 --name
 * '*LICENSE*'` returns nothing; MuseTalk's root is two weight dirs + README +
 * .gitattributes). The licence is declared ONLY by the Hub metadata tag, so these
 * URLs are the CANONICAL TEXT FOR THAT TAG (SDXL's Open RAIL++-M, CompVis's
 * CreativeML OpenRAIL-M) — not a document either repo published. That mapping is
 * the Hub's tag convention, which is strong but is an inference; if an upstream
 * ever ships its own modified licence text, that file governs and these links
 * must be re-pointed at it.
 *
 * WHY THESE ARE NOT CHIPPED "Commercial OK": that chip reads, in this UI, as
 * "permissive, no strings", and for an OpenRAIL model that is a materially
 * incomplete statement — the use-restrictions bind the USER too. Chipping them
 * "Non-commercial" would instead be simply false. They therefore get their own
 * chip naming the licence and the restriction, which is also why the bundled
 * models' chip counts above are untouched.
 *
 * Wav2Lip is deliberately ABSENT: it is genuinely research/non-commercial only,
 * so it is not shipped, not downloadable, and rejected by name in the sidecar.
 */
export const OPT_IN_MODEL_NOTICES: readonly OptInModelNotice[] = [
  {
    name: 'LatentSync',
    role: 'lip-sync — re-lips the on-screen mouth to a generated dub (default engine)',
    gatedBy: 'lipSyncEnabled',
    weightsLicense: 'openrail++',
    weightsLicenseUrl:
      'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md',
    codeLicense: 'Apache-2.0',
    commercial: true,
    useRestricted: true,
    attribution: '© ByteDance Ltd. (bytedance/LatentSync)',
    source: 'https://huggingface.co/ByteDance/LatentSync-1.6',
    paper: 'LatentSync: audio-conditioned latent diffusion lip-sync, arXiv:2412.09262',
    note:
      'Commercial use IS permitted — this is a Responsible-AI (OpenRAIL++) licence, not a ' +
      'non-commercial one. What it adds is a list of prohibited USES (Attachment A) that binds ' +
      'you as well, and an obligation to pass those same restrictions on to anyone you give the ' +
      'model or its output to. Reframe additionally requires you to attest that you have the ' +
      'right to modify the on-screen person’s likeness before it will run.',
  },
  {
    name: 'MuseTalk',
    role: 'lip-sync — real-time-capable alternative engine',
    gatedBy: 'lipSyncEnabled',
    weightsLicense: 'creativeml-openrail-m',
    weightsLicenseUrl: 'https://huggingface.co/spaces/CompVis/stable-diffusion-license',
    codeLicense: 'MIT',
    commercial: true,
    useRestricted: true,
    attribution: '© Tencent Music Entertainment Lyra Lab (TMElyralab/MuseTalk)',
    source: 'https://huggingface.co/TMElyralab/MuseTalk',
    note:
      'Commercial use IS permitted under CreativeML OpenRAIL-M, subject to the same ' +
      'Attachment A prohibited-use list and the same pass-through obligation. Reframe drives ' +
      'this engine with its own MIT YuNet face boxes so the unlicensed S3FD detector bundled ' +
      'with the upstream pipeline is never fetched or used.',
  },
];

/** The Settings → Licenses surface: bundled third-party model attributions. */
export function ThirdPartyNotices(): React.ReactElement {
  return (
    <section className="tpn" aria-label="Third-party notices">
      <h2 className="tpn__title">Third-party notices</h2>
      <p className="tpn__intro">
        Reframe bundles the third-party machine-learning models below. Their licenses and required
        attributions are reproduced here; the full license text for the vendored models ships in the
        listed LICENSE files.
      </p>
      <ul className="tpn__list">
        {THIRD_PARTY_NOTICES.map((n) => (
          <li key={n.name} className="tpn__item" data-license={n.license}>
            <header className="tpn__head">
              <span className="tpn__name">{n.name}</span>
              <span
                className={`tpn__chip ${n.commercial ? 'tpn__chip--ok' : 'tpn__chip--nc'}`}
                data-commercial={n.commercial ? 'yes' : 'no'}
              >
                {n.commercial ? 'Commercial OK' : 'Non-commercial'}
              </span>
            </header>
            <p className="tpn__role">{n.role}</p>
            <p className="tpn__attr">{n.attribution}</p>
            <p className="tpn__license">
              License:{' '}
              <a href={n.licenseUrl} target="_blank" rel="noreferrer">
                {n.license}
              </a>{' '}
              · Source:{' '}
              <a href={n.source} target="_blank" rel="noreferrer">
                {n.source}
              </a>
            </p>
            {n.paper ? <p className="tpn__paper">{n.paper}</p> : null}
            {n.licenseFile ? (
              <p className="tpn__file">
                Full license: <code>{n.licenseFile}</code>
              </p>
            ) : null}
            {n.note ? (
              <p className="tpn__note" role="note">
                {n.note}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="tpn__binaries">
        <h3 className="tpn__subtitle">Bundled programs</h3>
        <p className="tpn__intro">
          Reframe also ships a complete third-party program inside the installer. Because it is
          copyleft-licensed, you are entitled to its source code — the exact revision is linked
          below, and the full license text ships beside the executable.
        </p>
        <ul className="tpn__list">
          <li className="tpn__item" data-license={FFMPEG_NOTICE.license}>
            <header className="tpn__head">
              <span className="tpn__name">{FFMPEG_NOTICE.name}</span>
              <span className="tpn__chip tpn__chip--copyleft" data-commercial="yes">
                {FFMPEG_NOTICE.license}
              </span>
            </header>
            <p className="tpn__role">{FFMPEG_NOTICE.role}</p>
            <p className="tpn__attr">
              Version <code>{FFMPEG_NOTICE.version}</code> · build{' '}
              <code>{FFMPEG_NOTICE.buildTag}</code>
            </p>
            <p className="tpn__license">
              License:{' '}
              <a href={FFMPEG_NOTICE.licenseUrl} target="_blank" rel="noreferrer">
                {FFMPEG_NOTICE.license}
              </a>{' '}
              · Source (this exact revision):{' '}
              <a href={FFMPEG_NOTICE.sourceUrl} target="_blank" rel="noreferrer">
                {FFMPEG_NOTICE.sourceUrl}
              </a>
            </p>
            <p className="tpn__license">
              Build scripts:{' '}
              <a href={FFMPEG_NOTICE.buildScriptsUrl} target="_blank" rel="noreferrer">
                {FFMPEG_NOTICE.buildScriptsUrl}
              </a>{' '}
              · asset <code>{FFMPEG_NOTICE.asset}</code>
            </p>
            <p className="tpn__file">
              Full license: <code>{FFMPEG_NOTICE.licenseFile}</code>
            </p>
            <p className="tpn__note" role="note">
              {FFMPEG_NOTICE.note}
            </p>
          </li>
        </ul>
      </div>
      <div className="tpn__optin">
        <h3 className="tpn__subtitle">Optional downloads</h3>
        <p className="tpn__intro">
          These models are not shipped with Reframe. They are downloaded only if you turn on the
          feature that needs them, and they are licensed under a Responsible-AI licence: commercial
          use is permitted, but the licence forbids certain USES and requires you to pass those same
          restrictions on to anyone you share the model or its output with.
        </p>
        <ul className="tpn__list">
          {OPT_IN_MODEL_NOTICES.map((n) => (
            <li key={n.name} className="tpn__item" data-optin-license={n.weightsLicense}>
              <header className="tpn__head">
                <span className="tpn__name">{n.name}</span>
                <span
                  className="tpn__chip tpn__chip--userestricted"
                  data-commercial={n.commercial ? 'yes' : 'no'}
                  data-use-restricted={n.useRestricted ? 'yes' : 'no'}
                >
                  {n.weightsLicense} · commercial OK, use-restricted
                </span>
              </header>
              <p className="tpn__role">{n.role}</p>
              <p className="tpn__attr">
                {n.attribution} · off unless <code>{n.gatedBy}</code> is enabled
              </p>
              <p className="tpn__license">
                Weights:{' '}
                <a href={n.weightsLicenseUrl} target="_blank" rel="noreferrer">
                  {n.weightsLicense}
                </a>{' '}
                · Code: {n.codeLicense} · Source:{' '}
                <a href={n.source} target="_blank" rel="noreferrer">
                  {n.source}
                </a>
              </p>
              {n.paper ? <p className="tpn__paper">{n.paper}</p> : null}
              <p className="tpn__note" role="note">
                {n.note}
              </p>
            </li>
          ))}
        </ul>
      </div>
      <div className="tpn__fonts">
        <h3 className="tpn__subtitle">Bundled fonts</h3>
        <p className="tpn__intro">
          Reframe self-hosts its UI type trio. All three are licensed under the SIL Open Font
          License 1.1 (permissive; commercial use permitted). The full license text and verbatim
          copyright notices ship beside the binaries at <code>{FONT_LICENSE_FILE}</code>.
        </p>
        <ul className="tpn__list">
          {FONT_NOTICES.map((f) => (
            <li key={f.name} className="tpn__item" data-font={f.name}>
              <header className="tpn__head">
                <span className="tpn__name">{f.name}</span>
                <span className="tpn__chip tpn__chip--ofl" data-commercial="yes">
                  {f.license}
                </span>
              </header>
              <p className="tpn__role">{f.role}</p>
              <p className="tpn__attr">{f.attribution}</p>
              <p className="tpn__license">
                License:{' '}
                <a href={f.licenseUrl} target="_blank" rel="noreferrer">
                  {f.license}
                </a>{' '}
                · Source:{' '}
                <a href={f.source} target="_blank" rel="noreferrer">
                  {f.source}
                </a>
              </p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export default ThirdPartyNotices;
