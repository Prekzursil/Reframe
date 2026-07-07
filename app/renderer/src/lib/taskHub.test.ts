import { describe, expect, it } from 'vitest';
import {
  HUB_CARDS,
  HUB_CHOICE_KEY,
  mergeHubChoice,
  readHubChoice,
  resumeFor,
} from './taskHub';

describe('taskHub model', () => {
  describe('HUB_CARDS', () => {
    it('lists the four job cards in landing order', () => {
      expect(HUB_CARDS.map((c) => c.id)).toEqual(['reframe', 'shorts', 'subtitles', 'director']);
      // every card carries human copy (title + blurb), never a bare id.
      for (const card of HUB_CARDS) {
        expect(card.title.length).toBeGreaterThan(0);
        expect(card.blurb.length).toBeGreaterThan(0);
      }
    });

    it('flags the dual-homed destinations (shorts/director) as also top-level, not the in-place ones', () => {
      // design-review P2: shorts + director ALSO exist as general top-level tabs,
      // so their cards wear the "for this video" cue; reframe + subtitles route
      // in-place into the per-video Workspace and carry no cue.
      const byId = Object.fromEntries(HUB_CARDS.map((c) => [c.id, c] as const));
      expect(byId.shorts.alsoTopLevel).toBe(true);
      expect(byId.director.alsoTopLevel).toBe(true);
      expect(byId.reframe.alsoTopLevel).toBeUndefined();
      expect(byId.subtitles.alsoTopLevel).toBeUndefined();
    });
  });

  describe('resumeFor', () => {
    it('resumes the workspace-scoped choices in place at their tab', () => {
      expect(resumeFor('reframe')).toEqual({ kind: 'workspace', tab: 'shortmaker' });
      expect(resumeFor('subtitles')).toEqual({ kind: 'workspace', tab: 'subtitles' });
      // 'advanced' resumes into the Workspace at its own default first tab.
      expect(resumeFor('advanced')).toEqual({ kind: 'workspace', tab: null });
    });

    it('treats section choices as non-resumable (marked, not auto-navigated)', () => {
      expect(resumeFor('shorts')).toEqual({ kind: 'section' });
      expect(resumeFor('director')).toEqual({ kind: 'section' });
    });

    it('returns none for a missing or unrecognised choice', () => {
      expect(resumeFor(null)).toEqual({ kind: 'none' });
      expect(resumeFor('bogus')).toEqual({ kind: 'none' });
    });
  });

  describe('readHubChoice', () => {
    it('reads the stored choice for the video', () => {
      const settings = { [HUB_CHOICE_KEY]: { v1: 'subtitles', v2: 'reframe' } };
      expect(readHubChoice(settings, 'v1')).toBe('subtitles');
      expect(readHubChoice(settings, 'v2')).toBe('reframe');
    });

    it('fails soft on every malformed shape', () => {
      expect(readHubChoice(null, 'v1')).toBeNull();
      expect(readHubChoice('nope', 'v1')).toBeNull();
      expect(readHubChoice({}, 'v1')).toBeNull();
      expect(readHubChoice({ [HUB_CHOICE_KEY]: null }, 'v1')).toBeNull();
      expect(readHubChoice({ [HUB_CHOICE_KEY]: 'oops' }, 'v1')).toBeNull();
      expect(readHubChoice({ [HUB_CHOICE_KEY]: { v1: 42 } }, 'v1')).toBeNull();
      expect(readHubChoice({ [HUB_CHOICE_KEY]: { other: 'x' } }, 'v1')).toBeNull();
    });
  });

  describe('mergeHubChoice', () => {
    it('sets the choice on an empty base when prev is missing/malformed', () => {
      expect(mergeHubChoice(null, 'v1', 'reframe')).toEqual({ v1: 'reframe' });
      expect(mergeHubChoice('nope', 'v1', 'reframe')).toEqual({ v1: 'reframe' });
    });

    it('preserves other videos and drops non-string entries', () => {
      const prev = { v2: 'director', junk: 99 };
      expect(mergeHubChoice(prev, 'v1', 'subtitles')).toEqual({ v2: 'director', v1: 'subtitles' });
    });

    it('overwrites the same video and does not mutate prev', () => {
      const prev = { v1: 'reframe' };
      const next = mergeHubChoice(prev, 'v1', 'advanced');
      expect(next).toEqual({ v1: 'advanced' });
      expect(prev).toEqual({ v1: 'reframe' });
    });
  });
});
