// schemas.test.ts — module-load + type-conformance coverage for lib/rpc/schemas.ts.
//
// schemas.ts is the §1/§3 frozen-surface TYPE module (128 interfaces/types, no
// runtime exports). It still sits inside the renderer's 100% v8 gate, and a file
// that no test ever imports is reported at 0% — so this file (a) executes the
// module (a VALUE import, not `import type`, so the transformed module actually
// loads under vitest) and (b) pins the load-bearing parts of the frozen surface
// with expectTypeOf assertions: the additive-optional rule (Cue.speaker), the
// word/segment numeric pair, and the shape of the §1 bridge surface the client
// proxies to. If someone renames a frozen field, `vitest typecheck`-style
// assertion failures point here before the sidecar drifts.

import { describe, expect, it } from 'vitest';
import { expectTypeOf } from 'vitest';

// VALUE import: forces the (types-only) module to be transformed + executed so
// v8 records it as loaded instead of an untouched 0% file.
import * as schemas from './schemas';

describe('lib/rpc/schemas module surface', () => {
  it('loads as an ES module (types-only file, no runtime exports expected)', () => {
    // A types-only module compiles to an empty module: its namespace object
    // exists but carries no own runtime exports. Assert exactly that so a
    // future accidental RUNTIME export (which would need real coverage tests)
    // is caught here rather than silently shipping untested code.
    const runtimeKeys = Object.keys(schemas).sort();
    expect(runtimeKeys).toEqual([]);
  });

  it('declares Cue.speaker as optional-and-additive (CONTRACTS.md §A3a)', () => {
    type Cue = schemas.Cue;
    expectTypeOf<Cue>().toHaveProperty('speaker').toEqualTypeOf<string | undefined>();
    // Frozen fields stay required.
    expectTypeOf<Cue['index']>().toEqualTypeOf<number>();
    expectTypeOf<Cue['start']>().toEqualTypeOf<number>();
    expectTypeOf<Cue['end']>().toEqualTypeOf<number>();
    expectTypeOf<Cue['text']>().toEqualTypeOf<string>();
  });

  it('declares the transcript word/segment timing pair', () => {
    expectTypeOf<schemas.Word['text']>().toEqualTypeOf<string>();
    expectTypeOf<schemas.Word['start']>().toEqualTypeOf<number>();
    expectTypeOf<schemas.Word['end']>().toEqualTypeOf<number>();
    expectTypeOf<schemas.Segment['words']>().toEqualTypeOf<schemas.Word[]>();
    expectTypeOf<schemas.Transcript['durationSec']>().toEqualTypeOf<number>();
  });

  it('declares the union codecs the §2 call surface keys on', () => {
    expectTypeOf<schemas.SubtitleFormat>().toEqualTypeOf<'srt' | 'ass' | 'vtt'>();
    expectTypeOf<schemas.TrackKind>().toEqualTypeOf<'soft' | 'hard'>();
    expectTypeOf<schemas.BilingualOrder>().toEqualTypeOf<'original-first' | 'translation-first'>();
    expectTypeOf<schemas.NleFormat>().toEqualTypeOf<'edl' | 'csv'>();
  });

  it('declares the §1 bridge surface the runtime client proxies to', () => {
    // rpc/onProgress are the required members every client wrapper calls; the
    // on* subscriptions and pickers are optional bridges (older hosts omit them).
    expectTypeOf<schemas.MediaApi['rpc']>().toBeFunction();
    expectTypeOf<schemas.MediaApi['onProgress']>().toBeFunction();
    expectTypeOf<schemas.MediaApi['onJobDone']>().toEqualTypeOf<
      ((cb: (event: schemas.DoneEvent) => void) => () => void) | undefined
    >();
    expectTypeOf<schemas.MediaApi['getDataFolder']>().toEqualTypeOf<
      (() => Promise<string>) | undefined
    >();
  });
});
