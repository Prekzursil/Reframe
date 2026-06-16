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
// `dub:<path>` id form (see WIRING-T2.md for the one-line main-process
// resolver extension; until applied the player shows the path instead).
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import {
  extractJobId,
  getApi,
  pickField,
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

/** Pull the §A3 job.done error payload message ({error:{message,type}}). */
export function doneErrorMessage(result: unknown): string | null {
  const err = pickField<{ message?: unknown }>(result, 'error');
  if (err && typeof err === 'object' && typeof err.message === 'string') {
    return err.message;
  }
  return null;
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
  // sample upload (voice clone)
  const [samplePath, setSamplePath] = useState<string>('');
  const [sampleMessage, setSampleMessage] = useState<string>('');
  // job state
  const [busy, setBusy] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [result, setResult] = useState<DubDoneResult | null>(null);

  const engineOption = useMemo(() => ENGINES.find((e) => e.id === engine) ?? ENGINES[0], [engine]);
  const engineVoices = useMemo(() => voicesForEngine(voices, engine), [voices, engine]);

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
    if (!path) return;
    setSampleMessage('');
    try {
      const res = await bridge.rpc<{ sample: VoiceSample }>('tts.sample.add', { path });
      setSampleMessage(`Added sample "${res.sample.name}"`);
      setSamplePath('');
      await refresh(); // samples surface as chatterbox voices
    } catch (err) {
      setSampleMessage(err instanceof Error ? err.message : String(err));
    }
  }, [bridge, samplePath, refresh]);

  const startDub = useCallback(async (): Promise<void> => {
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
      const done = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const errMessage = doneErrorMessage(done);
      if (errMessage) {
        setError(errMessage);
      } else if (done && typeof done === 'object') {
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

  const cancel = useCallback(async (): Promise<void> => {
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
        <button
          type="button"
          data-action="add-sample"
          className="secondary"
          onClick={() => void addSample()}
          disabled={busy || !samplePath.trim()}
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
          </li>
        ))}
      </ul>
      {audioTracks.length === 0 && <p className="audio-track-empty">No audio tracks yet.</p>}
    </section>
  );
}

export default Dub;
