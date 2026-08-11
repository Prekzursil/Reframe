// Dub feature panel (PLAN-P2 T2 / CONTRACTS.md A2).
//
// Drives the TTS voiceover/dub pipeline:
//   tts.voices()                 -> {voices:[{id,engine,lang,name}]}
//   tts.sample.add({path})       -> {sample: VoiceSample}
//   tts.dub.start({videoId, trackId, engine, voice?, sampleId?, targetLang?})
//        -> {jobId} -> job.done {audioTrack, path}
//   tracks.list({videoId})       -> {tracks}        (the cue source picker)
//   tracks.audio.list({videoId}) -> {audioTracks}   (the A3 AudioTrack list)
//
// Consumes the FROZEN window.api bridge via the shared local helpers in
// `./_api` (the same pattern as the sibling panels). The finished dub WAV is
// auditioned directly in an <audio> tag through the mstream:// protocol's
// `dub:<path>` id form (see docs/wiring/WIRING-T2.md for the one-line main-process
// resolver extension; until applied the player shows the path instead).
//
// W20: this panel also hosts the LIP-SYNC section (`./LipSync`), the only entry
// point to `tts.lipsync.start` — which was registered unconditionally
// (`features/tts/__init__.py:141`) and frozen into the RPC surface, yet this file
// was 519 lines with ZERO `lipSync`/`lipsync` references, so no user could reach
// it. It lives here because a re-lip consumes a FINISHED dub AudioTrack, and it is
// a separate component (not more code in this file) because this file was already
// long and that section carries four independent fail-closed gates.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { AiAudioBadge, AiDisclosurePanel, isAiGeneratedAudioTrack } from './AiDisclosure';
import LipSync from './LipSync';
import {
  extractJobId,
  getApi,
  waitForJobDone,
  type MediaStudioApi,
  type SubtitleTrack,
} from './_api';

// --- A2/A3 wire shapes (field names FROZEN, identical to the Python side) --
export interface TtsVoice {
  id: string;
  engine: string;
  lang: string;
  name: string;
}

export interface VoiceSample {
  id: string;
  name: string;
  path: string;
  durationSec: number;
  /** WU-A2 consent record — the sidecar refuses to store a clone without it. */
  consentAttested?: boolean;
  consentAt?: string | null;
  consentNote?: string | null;
}

/**
 * WU-A2 (docs/plans/v1.5/flagship-lip-sync-dub.md §4/§5.1) — the exact
 * attestation the user makes. It MUST match
 * `voices.CONSENT_ATTESTATION_TEXT` in the sidecar: the backend quotes this
 * sentence in its refusal, so a drifting UI copy would promise the user
 * something different from what is actually enforced and recorded.
 */
export const CONSENT_ATTESTATION_TEXT =
  "I own this voice or have the speaker's documented permission to clone it.";

/** Build the WU-A2 `tts.sample.add` params. `consentAttested` is never optional. */
export function buildSampleAddParams(args: {
  path: string;
  consentNote?: string;
}): Record<string, unknown> {
  const params: Record<string, unknown> = {
    path: args.path.trim(),
    consentAttested: true,
  };
  const note = (args.consentNote ?? '').trim();
  if (note) params.consentNote = note;
  return params;
}

export interface AudioTrack {
  id: string;
  lang: string;
  name: string;
  kind: 'original' | 'dub';
  voice?: string;
  path: string;
}

export interface DubDoneResult {
  audioTrack: AudioTrack;
  path: string;
}

// --- engines (A4: exactly these three; edgetts is labeled ONLINE) ----------
export interface EngineOption {
  id: string;
  label: string;
  online: boolean;
  voiceClone: boolean;
}

export const ENGINES: EngineOption[] = [
  { id: 'kokoro', label: 'Kokoro (local)', online: false, voiceClone: false },
  { id: 'edgetts', label: 'Edge TTS (ONLINE)', online: true, voiceClone: false },
  { id: 'chatterbox', label: 'Chatterbox (voice clone)', online: false, voiceClone: true },
];

// --- pure helpers (exported for tests) -------------------------------------
/** The voices belonging to one engine (the picker's filtered list). */
export function voicesForEngine(voices: TtsVoice[], engine: string): TtsVoice[] {
  return voices.filter((v) => v.engine === engine);
}

/** Build the FROZEN tts.dub.start params from the picker state. */
export function buildDubParams(args: {
  videoId: string;
  trackId: string;
  engine: string;
  voice?: string;
  sampleId?: string;
  targetLang?: string;
}): Record<string, unknown> {
  const params: Record<string, unknown> = {
    videoId: args.videoId,
    trackId: args.trackId,
    engine: args.engine,
  };
  const cloning = ENGINES.find((e) => e.id === args.engine)?.voiceClone ?? false;
  if (cloning) {
    if (args.sampleId) params.sampleId = args.sampleId;
  } else if (args.voice) {
    params.voice = args.voice;
  }
  if (args.targetLang && args.targetLang.trim()) {
    params.targetLang = args.targetLang.trim();
  }
  return params;
}

/**
 * The playable URL for a dub WAV. Rides the U1 mstream:// protocol with the
 * `dub:<absolute path>` id form (WIRING-T2.md adds the resolver branch in
 * main.ts; the path stays a single encoded path segment).
 */
export function dubMediaUrl(path: string): string {
  return `mstream://media/${encodeURIComponent(`dub:${path}`)}`;
}

/**
 * W62 — may this row's audio be edited (`tracks.audio.replace`) or dropped
 * (`tracks.audio.strip`) from here?
 *
 * ONLY a dub. Both RPCs branch on `kind`, and the two branches have very
 * different contracts:
 *
 *   * a DUB's audio is a standalone file, so both ops are pure MANIFEST edits —
 *     no ffmpeg, nothing else on disk changes
 *     (`sidecar/media_studio/features/tracks_audio.py:528-532` / `:572-577`);
 *   * an ORIGINAL is a real container stream, so both ops re-mux the WHOLE
 *     container into a NEW derived file — and that path is **returned but never
 *     written back to the project** (`:533-554` / `:578-588` only mutate the
 *     track row). The app would carry on resolving the untouched source while
 *     the manifest row vanished, i.e. a control that looks like it edits the
 *     video and does not.
 *
 * So the gate is a deliberate refusal to ship the second shape, not an
 * oversight. Making original-track editing real needs the sidecar to re-point
 * the project at the derivative — sidecar work, outside this lane.
 */
export function canEditAudioTrack(track: Pick<AudioTrack, 'kind'>): boolean {
  return track.kind === 'dub';
}

/**
 * The `kind` an IMPORTED audio track is registered under. Fixed, never a user
 * choice: `isAiGeneratedAudioTrack` withholds the AI-generated badge for
 * exactly one value, `"original"` (`AiDisclosure.tsx:83-85`), so a kind picker
 * would hand the user a switch that turns the Article-50 label off. Marking an
 * imported human recording is the disclosed, recoverable error direction —
 * `AI_AUDIO_BADGE_TITLE` says so in the badge itself (`AiDisclosure.tsx:45-58`).
 */
export const IMPORTED_AUDIO_TRACK_KIND = 'dub';

/**
 * True when the import row carries everything `tracks.audio.mux` demands.
 * `path`, `lang` and `name` are each `_require_str` on the sidecar
 * (`sidecar/media_studio/features/tracks_audio.py:494-497`), so a blank one is
 * gated here rather than sent to earn an INVALID_PARAMS round-trip.
 */
export function canImportAudioTrack(fields: { path: string; lang: string; name: string }): boolean {
  return Boolean(fields.path.trim() && fields.lang.trim() && fields.name.trim());
}

export interface DubProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function Dub({ videoId, api }: DubProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  // catalog + pickers
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [tracks, setTracks] = useState<SubtitleTrack[]>([]);
  const [audioTracks, setAudioTracks] = useState<AudioTrack[]>([]);
  const [engine, setEngine] = useState<string>(ENGINES[0].id);
  const [voice, setVoice] = useState<string>('');
  const [trackId, setTrackId] = useState<string>('');
  const [targetLang, setTargetLang] = useState<string>('');
  // sample upload (voice clone) + the WU-A2 blocking consent attestation
  const [samplePath, setSamplePath] = useState<string>('');
  const [sampleMessage, setSampleMessage] = useState<string>('');
  const [consentAttested, setConsentAttested] = useState<boolean>(false);
  const [consentNote, setConsentNote] = useState<string>('');
  // job state
  const [busy, setBusy] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [result, setResult] = useState<DubDoneResult | null>(null);
  // W62 audio-track ops (mux / replace / strip). One in-flight flag + one
  // outcome line for all three: each op re-reads the list on success, so two
  // overlapping ops would race the refresh.
  const [audioBusy, setAudioBusy] = useState<boolean>(false);
  const [audioMessage, setAudioMessage] = useState<string>('');
  // The id of the track whose "Replace audio" disclosure is open ('' = none).
  const [replaceFor, setReplaceFor] = useState<string>('');
  const [replacePath, setReplacePath] = useState<string>('');
  const [importPath, setImportPath] = useState<string>('');
  const [importLang, setImportLang] = useState<string>('');
  const [importName, setImportName] = useState<string>('');

  // `engine` is only ever set from the engine <select> whose options ARE ENGINES,
  // so the `?? ENGINES[0]` fallback is defensive.
  /* v8 ignore next */
  const engineOption = useMemo(() => ENGINES.find((e) => e.id === engine) ?? ENGINES[0], [engine]);
  const engineVoices = useMemo(() => voicesForEngine(voices, engine), [voices, engine]);
  // Every W62 audio-track control is gated on the SAME flag: a dub job in flight
  // is about to append a track, and a second audio op would race its refresh.
  const audioLocked = busy || audioBusy;

  const refresh = useCallback(async (): Promise<void> => {
    setError('');
    try {
      const [voicesRes, tracksRes, audioRes] = await Promise.all([
        bridge.rpc<{ voices: TtsVoice[] }>('tts.voices'),
        videoId
          ? bridge.rpc<{ tracks: SubtitleTrack[] }>('tracks.list', { videoId })
          : Promise.resolve({ tracks: [] as SubtitleTrack[] }),
        videoId
          ? bridge.rpc<{ audioTracks: AudioTrack[] }>('tracks.audio.list', { videoId })
          : Promise.resolve({ audioTracks: [] as AudioTrack[] }),
      ]);
      setVoices(Array.isArray(voicesRes?.voices) ? voicesRes.voices : []);
      setTracks(Array.isArray(tracksRes?.tracks) ? tracksRes.tracks : []);
      setAudioTracks(Array.isArray(audioRes?.audioTracks) ? audioRes.audioTracks : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [bridge, videoId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // keep the voice picker valid when the engine flips
  useEffect(() => {
    if (!engineVoices.some((v) => v.id === voice)) {
      setVoice(engineVoices[0]?.id ?? '');
    }
  }, [engineVoices, voice]);

  // relay job.progress for the active dub job only
  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const addSample = useCallback(async (): Promise<void> => {
    const path = samplePath.trim();
    // The Add-sample button is disabled when the path is blank OR the consent
    // box is unticked, so this guard is defensive.
    /* v8 ignore next */
    if (!path || !consentAttested) return;
    setSampleMessage('');
    try {
      const res = await bridge.rpc<{ sample: VoiceSample }>(
        'tts.sample.add',
        buildSampleAddParams({ path, consentNote }),
      );
      setSampleMessage(`Added sample "${res.sample.name}"`);
      setSamplePath('');
      // A fresh attestation is required per clone: one tick must never carry
      // over to the NEXT voice the user adds.
      setConsentNote('');
      setConsentAttested(false);
      await refresh(); // samples surface as chatterbox voices
    } catch (err) {
      // On FAILURE the tick stays, so a retry after fixing the path does not
      // force the user to re-attest for the same voice.
      setSampleMessage(err instanceof Error ? err.message : String(err));
    }
  }, [bridge, samplePath, consentAttested, consentNote, refresh]);

  const startDub = useCallback(async (): Promise<void> => {
    // The Start-dub button is disabled while busy and without a video/track/voice,
    // so this guard is defensive.
    /* v8 ignore next */
    if (busy || !videoId || !trackId) return;
    setBusy(true);
    setError('');
    setResult(null);
    setPct(0);
    setMessage('Starting…');
    try {
      const params = buildDubParams({
        videoId,
        trackId,
        engine,
        voice,
        // for a clone engine the picked "voice" IS the sampleId (samples
        // surface as chatterbox voices — voices.py samples_as_voices)
        sampleId: engineOption.voiceClone ? voice : undefined,
        targetLang,
      });
      // §2 long job: rpc resolves immediately with {jobId}; the terminal
      // payload arrives via job.done (see _api.ts waitForJobDone note).
      const res = await bridge.rpc<{ jobId: string }>('tts.dub.start', params);
      const id = extractJobId(res) ?? null;
      setJobId(id);
      // F1: waitForJobDone REJECTS on an {error} job.done payload (surfaced by
      // the catch below) — no more silent doneErrorMessage swallow.
      const done = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      if (done && typeof done === 'object') {
        const payload = done as DubDoneResult;
        if (payload.audioTrack && payload.path) setResult(payload);
        setPct(100);
        setMessage('Done');
        await refresh(); // pull the new AudioTrack row
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      setJobId(null);
    }
  }, [bridge, busy, engine, engineOption.voiceClone, refresh, targetLang, trackId, videoId, voice]);

  /**
   * Run one audio-track mutation, report its outcome, and re-read the list so
   * the panel shows the post-op truth. Returns whether it succeeded, so a caller
   * clears its inputs only on success — a failed op must not eat the path the
   * user typed. The list is deliberately NOT re-read on failure: nothing changed.
   *
   * The outcome rides a local flag and the single `return` sits AFTER the
   * `finally`, mirroring `startDub` below. A `return` INSIDE a `try` that has a
   * `finally` adds a completion path v8 counts as a branch and no test can reach
   * (measured: `Dub.tsx:373` arm 0, the one branch short of the renderer's 100%
   * gate). Restructuring removes it honestly; a `v8 ignore` would only have
   * hidden it.
   */
  const runAudioOp = useCallback(
    async (done: string, op: () => Promise<unknown>): Promise<boolean> => {
      setAudioBusy(true);
      setAudioMessage('');
      let ok = false;
      try {
        await op();
        setAudioMessage(done);
        await refresh();
        ok = true;
      } catch (err) {
        setAudioMessage(err instanceof Error ? err.message : String(err));
      } finally {
        setAudioBusy(false);
      }
      return ok;
    },
    [refresh],
  );

  const stripTrack = useCallback(
    async (track: AudioTrack): Promise<void> => {
      await runAudioOp(`Removed "${track.name}"`, () =>
        bridge.rpc<{ path: string }>('tracks.audio.strip', {
          videoId,
          audioTrackId: track.id,
        }),
      );
    },
    [bridge, runAudioOp, videoId],
  );

  const replaceTrackAudio = useCallback(
    async (track: AudioTrack): Promise<void> => {
      const path = replacePath.trim();
      // The Save button is disabled while the path is blank, so this is defensive.
      /* v8 ignore next */
      if (!path) return;
      const ok = await runAudioOp(`Replaced the audio of "${track.name}"`, () =>
        bridge.rpc<{ audioTrack: AudioTrack }>('tracks.audio.replace', {
          videoId,
          audioTrackId: track.id,
          path,
        }),
      );
      if (ok) {
        setReplaceFor('');
        setReplacePath('');
      }
    },
    [bridge, replacePath, runAudioOp, videoId],
  );

  const importTrack = useCallback(async (): Promise<void> => {
    const fields = { path: importPath, lang: importLang, name: importName };
    // The Import button is disabled until all three are filled, so this is defensive.
    /* v8 ignore next */
    if (!canImportAudioTrack(fields)) return;
    const name = fields.name.trim();
    const ok = await runAudioOp(`Imported "${name}"`, () =>
      bridge.rpc<{ audioTrack: AudioTrack }>('tracks.audio.mux', {
        videoId,
        path: fields.path.trim(),
        lang: fields.lang.trim(),
        name,
        kind: IMPORTED_AUDIO_TRACK_KIND,
      }),
    );
    if (ok) {
      setImportPath('');
      setImportLang('');
      setImportName('');
    }
  }, [bridge, importLang, importName, importPath, runAudioOp, videoId]);

  const cancel = useCallback(async (): Promise<void> => {
    // The Cancel button renders only while `busy && jobId`, so this guard is
    // defensive.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // best-effort: the job may already have finished
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  return (
    <section className="feature-panel dub-panel" aria-label="Dub">
      <h2>Dub / Voiceover</h2>
      <p className="dub-intro">
        Synthesize a dubbed audio track from a subtitle track — locally (Kokoro), hosted (Edge TTS,
        ONLINE) or cloning a voice sample (Chatterbox).
      </p>

      <div className="dub-pickers">
        <label>
          Subtitle track{' '}
          <select
            data-picker="track"
            value={trackId}
            onChange={(e) => setTrackId(e.target.value)}
            disabled={busy}
          >
            <option value="">— pick a track —</option>
            {tracks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.lang})
              </option>
            ))}
          </select>
        </label>

        <label>
          Engine{' '}
          <select
            data-picker="engine"
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            disabled={busy}
          >
            {ENGINES.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          {engineOption.voiceClone ? 'Voice sample' : 'Voice'}{' '}
          <select
            data-picker="voice"
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            disabled={busy || engineVoices.length === 0}
          >
            {engineVoices.length === 0 && (
              <option value="">
                {engineOption.voiceClone ? '— add a voice sample below —' : '— no voices —'}
              </option>
            )}
            {engineVoices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.lang})
              </option>
            ))}
          </select>
        </label>

        <label>
          Target language{' '}
          <input
            data-picker="lang"
            type="text"
            placeholder="(keep original) e.g. de, fr, ro"
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            disabled={busy}
          />
        </label>
      </div>

      {/* W21 — consent gate 3: label the generated result, and be explicit
          about what the label does NOT cover. */}
      <AiDisclosurePanel engineId={engine} />

      <div className="dub-sample-upload">
        <label>
          Voice sample (wav/mp3 path for cloning){' '}
          <input
            data-input="sample-path"
            type="text"
            placeholder="C:\\path\\to\\my-voice.wav"
            value={samplePath}
            onChange={(e) => setSamplePath(e.target.value)}
            disabled={busy}
          />
        </label>
        {/* WU-A2 — BLOCKING consent attestation. Cloning a person's voice
            without the right to do so is the flagship's headline legal
            exposure (EU AI Act Art. 50), so this is a first-class gate, not a
            notice: the button stays disabled until it is ticked, and the
            sidecar refuses the add independently even if it were bypassed. */}
        <fieldset className="dub-consent" data-testid="dub-consent">
          <legend>Voice-clone consent (required)</legend>
          <label className="dub-consent-attest" data-testid="consent-attest-label">
            <input
              data-input="consent-attest"
              type="checkbox"
              checked={consentAttested}
              onChange={(e) => setConsentAttested(e.target.checked)}
              disabled={busy}
            />{' '}
            {CONSENT_ATTESTATION_TEXT}
          </label>
          <label className="dub-consent-note">
            Note (optional — e.g. where the written permission is filed){' '}
            <input
              data-input="consent-note"
              type="text"
              placeholder="signed release 2026-08-01"
              value={consentNote}
              onChange={(e) => setConsentNote(e.target.value)}
              disabled={busy}
            />
          </label>
          <p className="dub-consent-hint">
            Recorded locally with the sample — the attestation and its timestamp never leave this
            machine.
          </p>
        </fieldset>
        <button
          type="button"
          data-action="add-sample"
          className="secondary"
          onClick={() => void addSample()}
          disabled={busy || !samplePath.trim() || !consentAttested}
        >
          Add sample
        </button>
        {sampleMessage && <span className="dub-sample-message">{sampleMessage}</span>}
      </div>

      <div className="actions">
        <button
          type="button"
          data-action="start-dub"
          onClick={() => void startDub()}
          disabled={busy || !videoId || !trackId || !voice}
        >
          {engineOption.online ? 'Start dub (ONLINE)' : 'Start dub'}
        </button>
        {busy && jobId && (
          <button
            type="button"
            data-action="cancel"
            className="secondary"
            onClick={() => void cancel()}
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          data-action="refresh"
          className="secondary"
          onClick={() => void refresh()}
          disabled={busy}
        >
          Refresh
        </button>
      </div>

      {busy && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="dub-result" data-testid="dub-result">
          <h3>Dub ready</h3>
          <p className="dub-result-name">
            {result.audioTrack.name} · {result.audioTrack.lang}
            {result.audioTrack.voice ? ` · voice ${result.audioTrack.voice}` : ''}
            {isAiGeneratedAudioTrack(result.audioTrack) && (
              <>
                {' '}
                <AiAudioBadge />
              </>
            )}
          </p>
          {/* audition the WAV directly (plan: play the dub WAV) */}
          <audio controls src={dubMediaUrl(result.path)} data-testid="dub-audio" />
          <p className="dub-result-path" title={result.path}>
            {result.path}
          </p>
        </div>
      )}

      <h3>Audio tracks</h3>
      <ul className="audio-track-list">
        {audioTracks.map((t) => (
          <li key={t.id} className="audio-track-row" data-audio-track={t.id}>
            <span className="audio-track-name">{t.name}</span>
            <span className="audio-track-lang">{t.lang}</span>
            <span className={`audio-track-kind audio-track-kind--${t.kind}`}>{t.kind}</span>
            {t.voice && <span className="audio-track-voice">{t.voice}</span>}
            {isAiGeneratedAudioTrack(t) && <AiAudioBadge />}
            {/* W62 — the reachable end of `tracks.audio.replace` / `.strip`.
                Offered for a dub only; see canEditAudioTrack for why the
                original-recording branch is deliberately not surfaced. */}
            {canEditAudioTrack(t) ? (
              <span className="audio-track-actions">
                <button
                  type="button"
                  className="secondary"
                  data-action="replace-audio"
                  // Clearing the draft here is load-bearing, not tidiness. `replacePath` is ONE
                  // component-level state shared by every row and the input below is controlled
                  // by it, while the only other reset (:414-415) sits inside the SUCCESS branch.
                  // Without this, typing a path for row A and then opening row B pre-filled B
                  // with A's path AND armed its Save, so one click sent A's file to B's
                  // audioTrackId — and `tracks_audio.py` assigns `track.path = audio_path`
                  // keeping no record of the previous value, so B's correct audio pointer was
                  // destroyed and the export played A's language under B's label. Pinned by
                  // "does not carry a typed replace path from one dub row to another".
                  onClick={() => {
                    setReplaceFor(replaceFor === t.id ? '' : t.id);
                    setReplacePath('');
                  }}
                  disabled={audioLocked}
                >
                  Replace audio…
                </button>
                <button
                  type="button"
                  className="secondary"
                  data-action="strip-audio"
                  onClick={() => void stripTrack(t)}
                  disabled={audioLocked}
                >
                  Remove
                </button>
              </span>
            ) : (
              <span className="audio-track-locked">
                Source audio — edit it in the video, not here
              </span>
            )}
            {replaceFor === t.id && (
              <span className="audio-track-replace">
                <label>
                  New audio file{' '}
                  <input
                    data-input="replace-audio-path"
                    type="text"
                    placeholder="C:\\path\\to\\better-dub.wav"
                    value={replacePath}
                    onChange={(e) => setReplacePath(e.target.value)}
                    disabled={audioLocked}
                  />
                </label>
                <button
                  type="button"
                  data-action="replace-audio-save"
                  onClick={() => void replaceTrackAudio(t)}
                  disabled={audioLocked || !replacePath.trim()}
                >
                  Save
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
      {audioTracks.length === 0 && <p className="audio-track-empty">No audio tracks yet.</p>}

      {/* W62 — the reachable end of `tracks.audio.mux`: register an audio file
          that was produced elsewhere as a track on this video, so the ShortMaker
          export picker (fed by the same `tracks.audio.list`) can mux it into a
          short. `kind` is fixed — see IMPORTED_AUDIO_TRACK_KIND. */}
      <div className="audio-track-import">
        <h4>Import an audio track</h4>
        <p className="audio-track-import-hint">
          Register an existing audio file (an externally-produced dub or voiceover) as a track on
          this video. It is marked as AI-generated audio like any non-source track — Reframe errs
          toward marking.
        </p>
        <label>
          File{' '}
          <input
            data-input="import-audio-path"
            type="text"
            placeholder="C:\\path\\to\\voiceover.wav"
            value={importPath}
            onChange={(e) => setImportPath(e.target.value)}
            disabled={audioLocked}
          />
        </label>
        <label>
          Language{' '}
          <input
            data-input="import-audio-lang"
            type="text"
            placeholder="e.g. ro"
            value={importLang}
            onChange={(e) => setImportLang(e.target.value)}
            disabled={audioLocked}
          />
        </label>
        <label>
          Name{' '}
          <input
            data-input="import-audio-name"
            type="text"
            placeholder="e.g. Romanian voiceover"
            value={importName}
            onChange={(e) => setImportName(e.target.value)}
            disabled={audioLocked}
          />
        </label>
        <button
          type="button"
          className="secondary"
          data-action="import-audio"
          onClick={() => void importTrack()}
          disabled={
            audioLocked ||
            !canImportAudioTrack({ path: importPath, lang: importLang, name: importName })
          }
        >
          Import
        </button>
      </div>

      {audioMessage && (
        <p className="audio-track-message" aria-live="polite">
          {audioMessage}
        </p>
      )}

      {/* W20 — lip-sync sits AFTER the track list because it consumes a finished
          dub from it. `audioTracks` is handed down rather than re-fetched, so the
          section adds no second `tracks.audio.list` call, and the SAME bridge is
          passed so an injected test api reaches it too. */}
      <LipSync videoId={videoId} audioTracks={audioTracks} api={bridge} />
    </section>
  );
}

export default Dub;
