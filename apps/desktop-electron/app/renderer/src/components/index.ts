// Barrel for the shared shell components & helpers (CONTRACTS.md §1: components/*).
export { TabBar, default as TabBarDefault, type TabDef, type TabBarProps } from './TabBar';
export {
  ProgressBar,
  default as ProgressBarDefault,
  clampPct,
  type ProgressBarProps,
} from './ProgressBar';
export { useJob, default as useJobDefault, type JobState } from './useJob';
export {
  rpc,
  onProgress,
  hasApi,
  type MediaApi,
  type ProgressEvent,
  type Word,
  type Segment,
  type Transcript,
  type Cue,
  type SubtitleTrack,
  type Candidate,
  type Video,
  type Project,
} from './api';
