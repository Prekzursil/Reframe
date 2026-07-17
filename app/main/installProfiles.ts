// installProfiles.ts — the in-app first-run install PROFILES (WU-1c).
//
// THE SINGLE SOURCE OF TRUTH mapping each first-run PROFILE the user picks on a
// FIRST-EVER launch — Minimum / Default / Full / Custom — to the concrete set of
// asset names bootstrap.py must ensure (routed as `--assets <names…>`; bootstrap.py
// parses `--assets nargs=*`). Both the Electron supervisor (main.ts, to build the
// argv + replay the persisted profile on a WU-S2 re-bootstrap) and the renderer
// (the ProfilePicker, to show each option's approx first-run download size) import
// THIS module — so there is exactly one map, not a duplicated pair.
//
// PURE by contract: this module imports NOTHING from node/electron so the RENDERER
// can bundle it. The CORE-floor + full-set parity to the Python side lives in the
// cross-file conformance test (installProfiles.test.ts), mirroring the existing
// firstRunGate.ts <-> bootstrap.py check.
//
// THE CORE FLOOR — MIT YuNet subject tracker + LR-ASD active-speaker weight — is
// in EVERY profile, INCLUDING Minimum. Skipping it is the exact trap the
// first-run-complete marker guards against: without those weights the reframe
// engine silently CENTRE-CROPS instead of following a real subject. So Minimum is
// "app + subject tracking; everything else on demand", never "app only".
// WU-L1: the no-license S3FD weight was removed from the floor (YuNet replaced it).

/** The four first-run install profiles the picker offers. */
export const INSTALL_PROFILE_IDS = ['minimum', 'default', 'full', 'custom'] as const;
export type InstallProfileId = (typeof INSTALL_PROFILE_IDS)[number];

// ---- asset names (mirror sidecar manifest.py / tools_resolver.py) -----------
// Kept as named constants so the conformance test can pin each against the Python
// source's string VALUE (not just its constant name).
const YUNET = 'yunet-face-detection';
const LIGHTASD_ASD = 'lightasd-asd';
const WHISPER = 'whisper-large-v3-turbo';
const QWEN = 'qwen3-4b-gguf';
const LLAMA_CUDA = 'llama-server-cuda';
const LLAMA_CUDART = 'llama-server-cuda-cudart';
const LLAMA_CPU = 'llama-server-cpu';

/**
 * The CORE FLOOR — the always-on face/ASD weights that make reframing track a real
 * subject. MUST equal firstRunGate.ts `CORE_FIRST_RUN_ASSETS` and bootstrap.py
 * `core_first_run_assets()` (the conformance test pins all three). Present in every
 * profile — the no-silent-centre-crop invariant.
 */
export const CORE_FLOOR_ASSETS: readonly string[] = [YUNET, LIGHTASD_ASD];

/** Approx download size per asset (MB) — mirrors the sidecar manifest `size_mb`. */
export const ASSET_SIZES_MB: Readonly<Record<string, number>> = {
  [YUNET]: 0.3,
  [LIGHTASD_ASD]: 4,
  [WHISPER]: 1600,
  [QWEN]: 2500,
  [LLAMA_CUDA]: 260,
  [LLAMA_CUDART]: 550,
  [LLAMA_CPU]: 30,
};

// ---- optional feature bundles (what Default/Full/Custom add on the floor) ----

/** The optional feature-bundle ids a Custom install (and the fixed profiles) pick. */
export const BUNDLE_IDS = ['transcription', 'ai-director'] as const;
export type BundleId = (typeof BUNDLE_IDS)[number];

/** Display + asset content for one optional feature bundle. */
export interface BundleMeta {
  readonly id: BundleId;
  readonly label: string;
  readonly what: string;
  readonly assets: readonly string[];
}

/** The optional feature bundles offered in a Custom install (ON TOP of the floor). */
export const INSTALL_BUNDLES: readonly BundleMeta[] = [
  {
    id: 'transcription',
    label: 'Transcription & subtitles',
    what: 'Whisper speech-to-text for captions, subtitles and search.',
    assets: [WHISPER],
  },
  {
    id: 'ai-director',
    label: 'AI Director',
    what: 'The local LLM (plus its llama-server builds) that powers prompt-driven editing.',
    assets: [QWEN, LLAMA_CUDA, LLAMA_CUDART, LLAMA_CPU],
  },
];

const BUNDLE_BY_ID: ReadonlyMap<BundleId, BundleMeta> = new Map(
  INSTALL_BUNDLES.map((b) => [b.id, b]),
);

/** The optional bundles each FIXED profile pledges (Custom is user-driven). */
const FIXED_PROFILE_BUNDLES: Readonly<
  Record<Exclude<InstallProfileId, 'custom'>, readonly BundleId[]>
> = {
  minimum: [],
  default: ['transcription'],
  full: ['transcription', 'ai-director'],
};

/** Display metadata for one profile option in the picker. */
export interface ProfileMeta {
  readonly id: InstallProfileId;
  readonly label: string;
  readonly what: string;
  readonly why: string;
  /** true for the pre-selected "recommended" default option. */
  readonly recommended: boolean;
}

/** The four profile options, in display order (Default is recommended/pre-selected). */
export const INSTALL_PROFILES: readonly ProfileMeta[] = [
  {
    id: 'minimum',
    label: 'Minimum',
    what: 'The app plus subject tracking, so reframing works right away. Everything else downloads the first time you use it.',
    why: 'Smallest first-run download — get started fast.',
    recommended: false,
  },
  {
    id: 'default',
    label: 'Default',
    what: 'Adds offline transcription, so captions, subtitles and search work out of the box.',
    why: 'The balanced choice for most people.',
    recommended: true,
  },
  {
    id: 'full',
    label: 'Full',
    what: 'Everything up front — also installs the local AI Director model so nothing downloads later.',
    why: 'Best for offline use or a one-and-done setup.',
    recommended: false,
  },
  {
    id: 'custom',
    label: 'Custom',
    what: 'Choose exactly which feature packs to install now; the rest stay on demand.',
    why: 'Pick only what you need.',
    recommended: false,
  },
];

/** A validated install choice: the profile, its bundle set, and resolved assets. */
export interface ResolvedInstallChoice {
  readonly profile: InstallProfileId;
  readonly bundles: readonly BundleId[];
  readonly assets: readonly string[];
}

/** A typed invalid-choice failure — surfaced loudly, never silently defaulted. */
export class InstallProfileError extends Error {}

/** Whether `value` is one of the four profile ids. */
export function isInstallProfileId(value: unknown): value is InstallProfileId {
  return typeof value === 'string' && (INSTALL_PROFILE_IDS as readonly string[]).includes(value);
}

/** Whether `value` is a known optional bundle id. */
export function isBundleId(value: unknown): value is BundleId {
  return typeof value === 'string' && (BUNDLE_IDS as readonly string[]).includes(value);
}

/** Deduplicate while preserving first-seen order. */
function dedupe(values: readonly string[]): string[] {
  return [...new Set(values)];
}

/**
 * Resolve a profile (+ Custom bundles) to the concrete first-run asset set — the
 * SINGLE resolution used to build `--assets` AND to size the picker. The CORE
 * FLOOR is prepended unconditionally, so every profile — Minimum included — pins
 * the tracker/ASD weights (no silent centre-crop). FAILS LOUD (throws
 * {@link InstallProfileError}) on an unknown profile or bundle id — never a silent
 * fallback to some default set.
 */
export function resolveInstallChoice(
  profile: unknown,
  bundles: readonly unknown[] = [],
): ResolvedInstallChoice {
  if (!isInstallProfileId(profile)) {
    throw new InstallProfileError(`unknown install profile: ${JSON.stringify(profile)}`);
  }
  // Non-custom profiles are fully determined by the profile id; a Custom install
  // uses the user-picked bundles (validated + order-preserving deduped).
  let selected: BundleId[];
  if (profile === 'custom') {
    selected = [];
    for (const b of bundles) {
      if (!isBundleId(b)) {
        throw new InstallProfileError(`unknown install bundle: ${JSON.stringify(b)}`);
      }
      selected.push(b);
    }
    selected = [...new Set(selected)];
  } else {
    selected = [...FIXED_PROFILE_BUNDLES[profile]];
  }
  const bundleAssets = selected.flatMap((id) => {
    const meta = BUNDLE_BY_ID.get(id);
    // Unreachable: `selected` only holds validated ids, but fail loud rather than
    // silently drop assets if the bundle table and id list ever drift.
    /* v8 ignore next 3 -- defensive: validated ids are always in the table */
    if (!meta) {
      throw new InstallProfileError(`bundle has no asset mapping: ${id}`);
    }
    return meta.assets;
  });
  return {
    profile,
    bundles: selected,
    assets: dedupe([...CORE_FLOOR_ASSETS, ...bundleAssets]),
  };
}

/** Total approx first-run download size (MB) for a resolved asset set. */
export function assetsSizeMb(assets: readonly string[]): number {
  return assets.reduce((sum, name) => sum + (ASSET_SIZES_MB[name] ?? 0), 0);
}

/** Human "~90 MB" / "~1.7 GB" size label for a total in MB. */
export function formatSize(mb: number): string {
  if (mb < 1000) {
    return `~${Math.round(mb)} MB`;
  }
  return `~${(mb / 1000).toFixed(1)} GB`;
}

/**
 * The picker's approx download-size label for a profile (+ Custom bundles). Pure
 * over the map, so the number the user sees can never drift from the asset set the
 * supervisor actually installs.
 */
export function profileSizeLabel(
  profile: InstallProfileId,
  bundles: readonly BundleId[] = [],
): string {
  return formatSize(assetsSizeMb(resolveInstallChoice(profile, bundles).assets));
}

// ---- persistence (read/replay the chosen profile on a re-bootstrap) ---------

/** The persisted install-profile file at the data root (sibling of the marker). */
export const INSTALL_PROFILE_FILE = '.first-run-profile.json';

/** The persisted profile record (profile id + Custom bundle selection). */
export interface PersistedInstallProfile {
  readonly profile: InstallProfileId;
  readonly bundles: readonly BundleId[];
}

/**
 * Parse a persisted install-profile file body. Returns the validated record, or
 * `null` when the file is absent / corrupt / from a legacy pre-WU-1c install — the
 * caller (a SILENT WU-S2 re-bootstrap) then falls back to the argless default set
 * (which still includes the core floor, so never a silent centre-crop). Unknown
 * bundle ids are dropped defensively rather than failing the whole re-bootstrap.
 */
export function parsePersistedInstallProfile(raw: unknown): PersistedInstallProfile | null {
  if (typeof raw !== 'object' || raw === null) {
    return null;
  }
  const record = raw as { profile?: unknown; bundles?: unknown };
  if (!isInstallProfileId(record.profile)) {
    return null;
  }
  const bundles = Array.isArray(record.bundles) ? record.bundles.filter(isBundleId) : [];
  return { profile: record.profile, bundles: [...new Set(bundles)] };
}
