// FirstRunSetup.tsx — the full-screen FIRST-RUN provisioning gate (WU-1b).
//
// PROBLEM it solves: App.tsx mounts the tabbed shell + Library immediately, so on
// a FIRST launch the Library's mount-time RPCs (library.list, the readiness
// roll-up) fire against a sidecar that does not exist yet — it is still being
// provisioned by the ~3-minute env/model build — producing the "sidecar is not
// running" red banners the user saw.
//
// FIX: while first-run provisioning is in flight, App renders THIS screen INSTEAD
// of the shell (see App.tsx AppGate). The Library (and its RPCs) never mount, so
// no "sidecar is not running" toast can fire. When the sidecar reaches 'running'
// the provisioning signal drops and App auto-transitions to the normal shell.
//
// FAILURE/OFFLINE (gate refinement, FIRST-CLASS): the SidecarBanner — which would
// normally surface a bootstrap failure — lives in the shell that THIS screen
// replaces, so a failure during provisioning would otherwise strand the user with
// a blank window. We therefore consume the `bootstrap.error` channel HERE and
// render the actionable failure + a Retry wired to the existing repairSetup
// (WU A5) + an offline hint. A genuine sidecar CRASH *after* provisioning is NOT
// a bootstrap error (it arrives on `sidecar.status`), so it is deliberately left
// to the in-shell SidecarBanner — this screen is already gone by then.
//
// Bridge access is STRUCTURAL (the renderer never imports the preload module),
// mirroring SidecarBanner: the gate degrades to inert when the bridge is absent
// (tests / early boot). WU-1a exposes the signals this consumes:
// onProvisioningState, onBootstrapProgress, onBootstrapError, repairSetup.
import React, { useCallback, useEffect, useState } from 'react';

import { ProgressBar, clampPct } from './ProgressBar';
import { ProfilePicker } from './ProfilePicker';
import { FirstRunChooser } from './FirstRunChooser';
import type { BundleId, InstallProfileId } from '../../../main/installProfiles';
import './firstRunSetup.css';

/**
 * WU-1d: the first-run AI-routing choice. `'privacy'` = fully LOCAL (the safe
 * default); `'bestFreeCloud'` = opt-in free-provider rotation. Mirrors the
 * FirstRunChooser prop + the `providers.firstRun` argument the Settings chooser
 * already sends — this gate step reuses that SAME path, it does not add a new one.
 */
export type RoutingChoice = 'privacy' | 'bestFreeCloud';

/** The three ordered first-run phases surfaced to the user. */
export type SetupPhase = 'building' | 'downloading' | 'finishing';

/** Human-readable heading per phase. */
const PHASE_LABEL: Record<SetupPhase, string> = {
  building: 'Building environment',
  downloading: 'Downloading core models',
  finishing: 'Finishing',
};

/** The user-facing heading for a phase. */
export function phaseLabel(phase: SetupPhase): string {
  return PHASE_LABEL[phase];
}

/** Rough one-time-setup estimate shown in the subtitle (minutes). */
export const SETUP_ESTIMATE_MIN = 3;

/** Mirror of preload BootstrapProgressEvent (WU-1a). */
export interface BootstrapProgressEvent {
  state: 'running' | 'done' | 'error';
  line: string;
}

/**
 * Mirror of preload ProvisioningState (WU-1a + WU-1c). `awaitingProfile` is true
 * ONLY on a FIRST-EVER run while the supervisor waits for the user's install-profile
 * choice before spawning bootstrap; a silent WU-S2 re-bootstrap leaves it false.
 */
export interface ProvisioningState {
  active: boolean;
  awaitingProfile?: boolean;
}

/** Mirror of preload/SidecarBanner RepairSetupResult (WU A5). */
export interface RepairSetupResult {
  ok: boolean;
  reason?: string;
}

/** Mirror of preload ChooseInstallProfileResult (WU-1c). */
export interface ChooseInstallProfileResult {
  ok: boolean;
  reason?: string;
}

/** The subset of the preload bridge this gate consumes. */
interface SetupBridge {
  getProvisioningState?: () => Promise<ProvisioningState>;
  onProvisioningState?: (cb: (state: ProvisioningState) => void) => () => void;
  onBootstrapProgress?: (cb: (event: BootstrapProgressEvent) => void) => () => void;
  onBootstrapError?: (cb: (message: string) => void) => () => void;
  repairSetup?: () => Promise<RepairSetupResult>;
  chooseInstallProfile?: (
    profile: InstallProfileId,
    bundles: BundleId[],
  ) => Promise<ChooseInstallProfileResult>;
  // WU-1d: the SAME JSON-RPC transport lib/rpc drives, used to apply the
  // local-vs-cloud AI-routing choice via `providers.firstRun` — the exact path
  // the Settings → Models & System chooser uses. Only reachable once provisioning
  // completes (the sidecar is 'running'), which is precisely when this step shows.
  rpc?: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>;
}

/** Read the preload-injected bridge without a global Window augmentation. */
function bridge(): SetupBridge | null {
  return (globalThis as { window?: { api?: SetupBridge } }).window?.api ?? null;
}

/** Current connectivity, used to strengthen the offline hint. */
function readOnline(): boolean {
  return navigator.onLine;
}

/** Parsed shape of a single relayed bootstrap line. */
export type ParsedLine =
  | { kind: 'assets'; pct: number }
  | { kind: 'step'; k: number; n: number }
  | { kind: 'other' };

// bootstrap.py emits `assets NN.N%  <msg>` (download progress) and
// `step k/N: <argv>` (pip env build); main.ts relays each line verbatim (often
// behind a `[bootstrap] ` prefix). We search anywhere in the line so the prefix
// never matters.
const ASSETS_RE = /assets\s+([0-9]+(?:\.[0-9]+)?)\s*%/i;
const STEP_RE = /step\s+([0-9]+)\/([0-9]+)/i;

/** Extract the progress signal (asset % or pip step) from a relayed line. */
export function parseBootstrapLine(line: string): ParsedLine {
  const pctMatch = ASSETS_RE.exec(line);
  if (pctMatch) {
    return { kind: 'assets', pct: Number.parseFloat(pctMatch[1]) };
  }
  const stepMatch = STEP_RE.exec(line);
  if (stepMatch) {
    return {
      kind: 'step',
      k: Number.parseInt(stepMatch[1], 10),
      n: Number.parseInt(stepMatch[2], 10),
    };
  }
  return { kind: 'other' };
}

/** Strip the `[bootstrap] ` prefix + collapse whitespace for display. */
export function cleanLine(line: string): string {
  return line
    .replace(/^\[bootstrap\]\s*/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** The reducible progress view-state. */
export interface ProgressState {
  phase: SetupPhase;
  pct: number;
  line: string;
}

/** Env build runs first, so the initial phase is 'building' at 0%. */
export const INITIAL_PROGRESS: ProgressState = { phase: 'building', pct: 0, line: '' };

/**
 * Fold one relayed bootstrap event into the progress state:
 *   - 'done'  → the finishing phase at 100% (detail cleared — the raw
 *               "bootstrap exited" line is not user-facing),
 *   - 'error' → unchanged (the actionable message arrives on the error channel),
 *   - `assets NN%` → the downloading phase at that percent,
 *   - `step k/N`   → the building phase at k/N,
 *   - anything else → keep the phase/percent, refresh the detail line.
 */
export function reduceProgress(prev: ProgressState, event: BootstrapProgressEvent): ProgressState {
  if (event.state === 'done') {
    return { phase: 'finishing', pct: 100, line: '' };
  }
  if (event.state === 'error') {
    return prev;
  }
  const parsed = parseBootstrapLine(event.line);
  const line = cleanLine(event.line);
  if (parsed.kind === 'assets') {
    return { phase: 'downloading', pct: clampPct(parsed.pct), line };
  }
  if (parsed.kind === 'step') {
    const pct = parsed.n > 0 ? clampPct((parsed.k / parsed.n) * 100) : 0;
    return { phase: 'building', pct, line };
  }
  return { ...prev, line };
}

/** The complete gate view-model produced by useFirstRunSetup. */
export interface FirstRunSetupView {
  /**
   * True once the initial provisioning state has been resolved (the mount-time
   * `getProvisioningState` query returned, or no bridge/query was available). App
   * withholds the shell while this is false so the shell's sidecar RPCs never fire
   * on the first frame of a first run.
   */
  ready: boolean;
  /** True while the full-screen gate must replace the shell. */
  visible: boolean;
  /**
   * WU-1c: true on a FIRST-EVER run while awaiting the install-profile choice —
   * the gate shows the ProfilePicker (before any download) instead of progress.
   */
  awaitingProfile: boolean;
  /**
   * WU-1d: true once provisioning has FINISHED on a FIRST-EVER run and the
   * local-vs-cloud AI-routing choice is still pending — the gate shows the
   * FirstRunChooser as the final step (AFTER the profile picker, so it never
   * changes what provisions; it is purely routing). Only ever true when the
   * profile picker was seen this session (a silent re-bootstrap / returning user
   * never sees it), so a returning user is never double-prompted.
   */
  showChooser: boolean;
  /** WU-1d: true while the routing choice is being applied (disables the chooser). */
  choosingRouting: boolean;
  /** WU-1d: LOUD inline failure if applying the routing choice failed (never swallowed). */
  choiceError: string | null;
  phase: SetupPhase;
  pct: number;
  line: string;
  /** Actionable bootstrap failure message (null while healthy). */
  error: string | null;
  /** True while a Retry re-run is in flight. */
  retrying: boolean;
  /** False when the machine is offline (strengthens the failure hint). */
  online: boolean;
  /** Re-run the idempotent bootstrap (wired to the existing repairSetup). */
  onRetry: () => void;
  /** WU-1c: commit the chosen install profile (wired to chooseInstallProfile). */
  onChooseProfile: (profile: InstallProfileId, bundles: BundleId[]) => void;
  /**
   * WU-1d: apply the local-vs-cloud AI-routing choice — wired to the SAME
   * `providers.firstRun` path (and thus the SAME `firstRunChoiceMade` flag) the
   * Settings chooser uses. Local stays the default; cloud is strictly opt-in.
   */
  onChooseRouting: (choice: RoutingChoice) => void;
}

/**
 * Owns the provisioning gate state: subscribes (structurally) to the WU-1a
 * signals and derives `visible`. The gate is shown while provisioning is active,
 * while a failure is unresolved, or while a Retry is in flight — so it never
 * flickers back to a shell whose RPCs would hit a dead sidecar. On success the
 * provisioning signal drops, error stays null, and `visible` becomes false so
 * App hands off to the normal shell.
 */
export function useFirstRunSetup(): FirstRunSetupView {
  const [ready, setReady] = useState(false);
  const [active, setActive] = useState(false);
  const [awaitingProfile, setAwaitingProfile] = useState(false);
  const [progress, setProgress] = useState<ProgressState>(INITIAL_PROGRESS);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [online, setOnline] = useState<boolean>(() => readOnline());
  // WU-1d: latches true the moment the install-profile step is seen — i.e. this
  // is a FIRST-EVER run (a silent re-bootstrap never sets awaitingProfile). Gating
  // the routing chooser on this proves "never double-prompt a returning user"
  // without needing a sidecar read (the sidecar is down for the whole gate window
  // except the final handoff frame, so firstRunChoiceMade cannot be read earlier).
  const [sawProfile, setSawProfile] = useState(false);
  // WU-1d: true once the routing choice has been applied (providers.firstRun ok),
  // so the chooser step drops and the gate hands off to the shell.
  const [routingChosen, setRoutingChosen] = useState(false);
  const [choosingRouting, setChoosingRouting] = useState(false);
  const [choiceError, setChoiceError] = useState<string | null>(null);

  // Resolve the INITIAL provisioning state at mount (push events miss the first
  // frame). A missing bridge/query resolves `ready` immediately so the app is
  // never stranded blank.
  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.getProvisioningState !== 'function') {
      setReady(true);
      return;
    }
    let cancelled = false;
    api
      .getProvisioningState()
      .then((state) => {
        if (cancelled) return;
        setActive(Boolean(state?.active));
        setAwaitingProfile(Boolean(state?.awaitingProfile));
        if (state?.awaitingProfile) setSawProfile(true);
        setReady(true);
      })
      .catch(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.onProvisioningState !== 'function') return;
    return api.onProvisioningState((state) => {
      setActive(Boolean(state?.active));
      setAwaitingProfile(Boolean(state?.awaitingProfile));
      if (state?.awaitingProfile) setSawProfile(true);
    });
  }, []);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.onBootstrapProgress !== 'function') return;
    return api.onBootstrapProgress((event) => setProgress((prev) => reduceProgress(prev, event)));
  }, []);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.onBootstrapError !== 'function') return;
    return api.onBootstrapError((message) => setError(message ? message : null));
  }, []);

  useEffect(() => {
    const update = (): void => setOnline(readOnline());
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);

  const onRetry = useCallback(() => {
    const api = bridge();
    if (!api || typeof api.repairSetup !== 'function') return;
    setRetrying(true);
    api
      .repairSetup()
      .then((result) => {
        setRetrying(false);
        if (result.ok === true) {
          // Success: clear the stale error so the (imminent) 'running' handoff
          // isn't blocked by a lingering failure message.
          setError(null);
        } else if (result.reason) {
          // Loud failure with a fresh reason — surface it and re-offer Retry.
          setError(result.reason);
        }
        // A reason-less failure keeps the prior actionable message (the
        // bootstrap-error channel re-pushes the FAILED line) and re-offers Retry.
      })
      .catch(() => {
        // Never swallow: drop the in-flight state so Retry is offered again.
        setRetrying(false);
      });
  }, []);

  // WU-1c: commit the install-profile choice. The supervisor validates + persists
  // it and flips the gate from awaiting-profile to provisioning (via the
  // provisioning push), so success needs no local state change here. A LOUD
  // validation failure (an invalid choice) is surfaced as the actionable error so
  // the user isn't stranded on a frozen picker — no silent swallow.
  const onChooseProfile = useCallback((profile: InstallProfileId, bundles: BundleId[]) => {
    const api = bridge();
    if (!api || typeof api.chooseInstallProfile !== 'function') return;
    api
      .chooseInstallProfile(profile, bundles)
      .then((result) => {
        if (result && result.ok === false && result.reason) {
          setError(result.reason);
        }
      })
      .catch(() => {
        // Never swallow silently: surface a generic actionable failure.
        setError('Could not start setup for the selected profile. Please retry.');
      });
  }, []);

  // WU-1d: apply the local-vs-cloud AI-routing choice through the SAME
  // `providers.firstRun` path the Settings chooser uses (it flips the shared
  // `firstRunChoiceMade` flag sidecar-side). Reachable here because this step only
  // shows once provisioning finished — the sidecar is 'running'. On success the
  // step drops (routingChosen) and the gate hands off to the shell. A failure is
  // surfaced LOUDLY inline and the chooser stays up for a retry — never a silent
  // fallback, never a silent hand-off as if a choice were made.
  const onChooseRouting = useCallback((choice: RoutingChoice) => {
    const api = bridge();
    if (!api || typeof api.rpc !== 'function') return;
    setChoosingRouting(true);
    setChoiceError(null);
    api
      .rpc('providers.firstRun', { choice })
      .then(() => {
        setChoosingRouting(false);
        setRoutingChosen(true);
      })
      .catch(() => {
        setChoosingRouting(false);
        setChoiceError('Could not save your choice. Please try again.');
      });
  }, []);

  // WU-1d: the routing chooser is the FINAL first-run step — shown only after
  // provisioning finished (!active), on a first-ever run (sawProfile), while the
  // choice is still pending (!routingChosen), and never while a bootstrap error
  // owns the gate (error === null). The picker (awaitingProfile) and a retry both
  // imply active/error, so those are covered transitively; the presentational
  // layer also checks the error + picker branches BEFORE this one, so it can never
  // render on top of them.
  const showChooser = sawProfile && !routingChosen && !active && error === null;

  const visible = active || error !== null || retrying || awaitingProfile || showChooser;
  return {
    ready,
    visible,
    awaitingProfile,
    showChooser,
    choosingRouting,
    choiceError,
    phase: progress.phase,
    pct: progress.pct,
    line: progress.line,
    error,
    retrying,
    online,
    onRetry,
    onChooseProfile,
    onChooseRouting,
  };
}

/** The offline hint shown when the machine has lost connectivity. */
function OfflineHint(): React.ReactElement {
  return (
    <p className="first-run-setup__offline">
      You appear to be offline. First-run setup downloads models and packages, so it needs an
      internet connection — reconnect to continue.
    </p>
  );
}

interface ProgressViewProps {
  phase: SetupPhase;
  pct: number;
  line: string;
  retrying: boolean;
  online: boolean;
}

/** The in-progress body: phase heading, progress bar, live detail, offline hint. */
function FirstRunProgress({
  phase,
  pct,
  line,
  retrying,
  online,
}: ProgressViewProps): React.ReactElement {
  return (
    <div className="first-run-setup__progress" role="status" aria-live="polite">
      <p className="first-run-setup__phase" data-phase={phase}>
        {retrying ? 'Retrying setup…' : phaseLabel(phase)}
      </p>
      <ProgressBar pct={pct} />
      {line !== '' ? <p className="first-run-setup__detail">{line}</p> : null}
      {online ? null : <OfflineHint />}
    </div>
  );
}

interface ErrorViewProps {
  message: string;
  online: boolean;
  onRetry: () => void;
}

/** The failure body: actionable message, offline/generic hint, Retry action. */
function FirstRunError({ message, online, onRetry }: ErrorViewProps): React.ReactElement {
  return (
    <div className="first-run-setup__error" role="alert" aria-live="assertive">
      <p className="first-run-setup__error-title">Setup couldn’t finish</p>
      <p className="first-run-setup__error-message">{message}</p>
      {online ? (
        <p className="first-run-setup__hint">
          If this keeps happening, check that the data folder is writable and has free disk space,
          then retry.
        </p>
      ) : (
        <OfflineHint />
      )}
      <button
        type="button"
        className="first-run-setup__retry"
        data-action="retry"
        onClick={onRetry}
      >
        Retry setup
      </button>
    </div>
  );
}

interface RoutingStepProps {
  busy: boolean;
  choiceError: string | null;
  onChoose: (choice: RoutingChoice) => void;
}

/**
 * WU-1d: the final first-run step — the local-vs-cloud AI-routing chooser. Reuses
 * the SAME FirstRunChooser the Settings panel renders (local is the always-labelled
 * recommended default; cloud is opt-in), plus a LOUD inline error if the apply
 * failed so the choice is never silently swallowed.
 */
function FirstRunRoutingStep({
  busy,
  choiceError,
  onChoose,
}: RoutingStepProps): React.ReactElement {
  return (
    <div className="first-run-setup__chooser">
      <FirstRunChooser onChoose={onChoose} busy={busy} />
      {choiceError !== null ? (
        <p className="first-run-setup__choice-error" role="alert" aria-live="assertive">
          {choiceError}
        </p>
      ) : null}
    </div>
  );
}

export interface FirstRunSetupProps {
  view: FirstRunSetupView;
}

/**
 * The full-screen first-run gate. Renders the failure body when a bootstrap error
 * is unresolved (and not mid-retry); the profile PICKER before any download; the
 * routing CHOOSER once provisioning finished (WU-1d); otherwise the progress body.
 * App mounts this INSTEAD of the tabbed shell whenever `view.visible` is true.
 */
export function FirstRunSetup({ view }: FirstRunSetupProps): React.ReactElement {
  const {
    awaitingProfile,
    showChooser,
    choosingRouting,
    choiceError,
    phase,
    pct,
    line,
    error,
    retrying,
    online,
    onRetry,
    onChooseProfile,
    onChooseRouting,
  } = view;
  const showError = error !== null && !retrying;
  // WU-1c: before any download, a first-ever run shows the profile PICKER. A
  // failure (e.g. the folder became busy after launch) takes precedence so the
  // user isn't stuck on a picker whose choice can't proceed.
  const showPicker = awaitingProfile && !showError && !retrying;
  // WU-1d: the routing chooser is the LAST step (after provisioning). `showChooser`
  // from the hook already excludes the error / picker / retry states, so it never
  // collides with the branches above.
  const choosing = showPicker || showChooser;
  return (
    <div className="first-run-setup">
      <div className="first-run-setup__panel">
        <header className="first-run-setup__header">
          <span className="first-run-setup__brand">Reframe</span>
          <h1 className="first-run-setup__title">
            {choosing ? 'Set up Reframe' : 'Setting up Reframe'}
          </h1>
          <p className="first-run-setup__subtitle">
            {showPicker
              ? 'Choose what to install now. This one-time setup runs once.'
              : showChooser
                ? 'Almost done — choose how Reframe runs AI. You can change this later.'
                : `This one-time setup takes about ${SETUP_ESTIMATE_MIN} minutes. You only see it once.`}
          </p>
        </header>
        {showError ? (
          <FirstRunError message={error} online={online} onRetry={onRetry} />
        ) : showPicker ? (
          <ProfilePicker onChoose={onChooseProfile} />
        ) : showChooser ? (
          <FirstRunRoutingStep
            busy={choosingRouting}
            choiceError={choiceError}
            onChoose={onChooseRouting}
          />
        ) : (
          <FirstRunProgress
            phase={phase}
            pct={pct}
            line={line}
            retrying={retrying}
            online={online}
          />
        )}
      </div>
    </div>
  );
}

export default FirstRunSetup;
