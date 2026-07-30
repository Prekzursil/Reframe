import { describe, expect, it } from 'vitest';
import {
  HUB_CARDS,
  HUB_CHOICE_KEY,
  REDIRECT_ONLY_WORKSPACE_TABS,
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
    // CLASS-LEVEL INVARIANT — the guard that was missing. A `workspace` resume means
    // "resume IN PLACE"; targeting a tab that redirects AWAY on mount produces an
    // unescapable bounce loop (Edit mounts -> Workspace mounts at the redirect tab ->
    // navigates away -> Edit unmounts), which is restart-durable and has no UI to
    // clear it. Asserted over the WHOLE choice domain, not one instance, so adding a
    // future redirect-only tab cannot silently reintroduce the bug.
    it('never resumes IN PLACE to a redirect-only Workspace tab', () => {
      const choices = [...HUB_CARDS.map((c) => c.id), 'advanced', 'bogus', null];
      for (const choice of choices) {
        const r = resumeFor(choice);
        if (r.kind === 'workspace' && r.tab !== null) {
          expect(
            REDIRECT_ONLY_WORKSPACE_TABS,
            `resumeFor(${String(choice)}) resumes in place to '${r.tab}', which redirects away on mount`,
          ).not.toContain(r.tab);
        }
      }
    });

    it('resumes the genuinely in-place choices at their tab', () => {
      expect(resumeFor('subtitles')).toEqual({ kind: 'workspace', tab: 'subtitles' });
      // 'advanced' resumes into the Workspace at its own default first tab.
      expect(resumeFor('advanced')).toEqual({ kind: 'workspace', tab: null });
    });

    it('treats reframe as a SECTION, not an in-place workspace resume', () => {
      // REVISED: this previously asserted `{ kind: 'workspace', tab: 'shortmaker' }`,
      // pinning the soft-lock defect. 'shortmaker' is not an in-place tab — Workspace
      // redirects away from it on mount — so classifying it as a `workspace` resume
      // bounced the user out of the video they just opened, permanently. That is the
      // exact failure the `section` note in taskHub.ts warns about, so 'reframe'
      // belongs in `section` alongside shorts/director.
      expect(resumeFor('reframe')).toEqual({ kind: 'section' });
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
