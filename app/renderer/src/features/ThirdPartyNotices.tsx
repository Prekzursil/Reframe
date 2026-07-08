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
    </section>
  );
}

export default ThirdPartyNotices;
