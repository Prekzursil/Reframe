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
