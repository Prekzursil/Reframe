// Tests for the mstream:// protocol core (P2 U1). The Range planner and URL
// helpers are pure; the request handler is exercised end-to-end against a
// real temp file (node environment — no jsdom needed). Electron is mocked so
// no app/protocol singleton is required.
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const registerSchemesMock = vi.fn();
const handleMock = vi.fn();

vi.mock('electron', () => ({
  protocol: {
    registerSchemesAsPrivileged: (...args: unknown[]) => registerSchemesMock(...args),
    handle: (...args: unknown[]) => handleMock(...args),
  },
}));

import {
  MEDIA_SCHEME,
  SidecarUnavailableError,
  contentTypeFor,
  createMediaRequestHandler,
  parseRangeHeader,
  planRequest,
  registerMediaProtocol,
  registerMediaSchemePrivileges,
  videoIdFromUrl,
} from './mediaProtocol';

describe('parseRangeHeader', () => {
  it('treats an absent header as none (full response)', () => {
    expect(parseRangeHeader(null, 1000)).toEqual({ kind: 'none' });
    expect(parseRangeHeader(undefined, 1000)).toEqual({ kind: 'none' });
    expect(parseRangeHeader('', 1000)).toEqual({ kind: 'none' });
  });

  it('parses the open-ended range Chromium always sends (bytes=0-)', () => {
    expect(parseRangeHeader('bytes=0-', 1000)).toEqual({ kind: 'range', start: 0, end: 999 });
  });

  it('parses an open-ended range from a mid-file offset', () => {
    expect(parseRangeHeader('bytes=500-', 1000)).toEqual({ kind: 'range', start: 500, end: 999 });
  });

  it('parses a bounded range and clamps the end to size-1', () => {
    expect(parseRangeHeader('bytes=100-199', 1000)).toEqual({
      kind: 'range',
      start: 100,
      end: 199,
    });
    expect(parseRangeHeader('bytes=100-99999', 1000)).toEqual({
      kind: 'range',
      start: 100,
      end: 999,
    });
  });

  it('parses a suffix range (bytes=-N -> last N bytes)', () => {
    expect(parseRangeHeader('bytes=-500', 1000)).toEqual({ kind: 'range', start: 500, end: 999 });
    expect(parseRangeHeader('bytes=-5000', 1000)).toEqual({ kind: 'range', start: 0, end: 999 });
  });

  it('is case/whitespace tolerant', () => {
    expect(parseRangeHeader('Bytes = 0 - ', 10)).toEqual({ kind: 'range', start: 0, end: 9 });
  });

  it('ignores malformed and multi-range headers (RFC 7233)', () => {
    expect(parseRangeHeader('items=0-', 1000)).toEqual({ kind: 'none' });
    expect(parseRangeHeader('bytes=abc-def', 1000)).toEqual({ kind: 'none' });
    expect(parseRangeHeader('bytes=0-1,5-9', 1000)).toEqual({ kind: 'none' });
    expect(parseRangeHeader('bytes=-', 1000)).toEqual({ kind: 'none' });
    expect(parseRangeHeader('bytes=200-100', 1000)).toEqual({ kind: 'none' }); // end < start
  });

  it('flags unsatisfiable ranges for a 416', () => {
    expect(parseRangeHeader('bytes=1000-', 1000)).toEqual({ kind: 'unsatisfiable' });
    expect(parseRangeHeader('bytes=5000-6000', 1000)).toEqual({ kind: 'unsatisfiable' });
    expect(parseRangeHeader('bytes=-0', 1000)).toEqual({ kind: 'unsatisfiable' });
    expect(parseRangeHeader('bytes=0-', 0)).toEqual({ kind: 'unsatisfiable' }); // empty file
    expect(parseRangeHeader('bytes=-5', 0)).toEqual({ kind: 'unsatisfiable' });
  });
});

describe('planRequest', () => {
  it('plans a 200 full response with Accept-Ranges when no range is sent', () => {
    const plan = planRequest(null, 1000);
    expect(plan.status).toBe(200);
    expect(plan.start).toBe(0);
    expect(plan.end).toBe(999);
    expect(plan.headers['Accept-Ranges']).toBe('bytes');
    expect(plan.headers['Content-Length']).toBe('1000');
    expect(plan.headers['Content-Range']).toBeUndefined();
  });

  it('plans a 206 with Content-Range for the open-ended range', () => {
    const plan = planRequest('bytes=0-', 1000);
    expect(plan.status).toBe(206);
    expect(plan.start).toBe(0);
    expect(plan.end).toBe(999);
    expect(plan.headers['Content-Range']).toBe('bytes 0-999/1000');
    expect(plan.headers['Content-Length']).toBe('1000');
  });

  it('plans a 206 for a bounded mid-file range', () => {
    const plan = planRequest('bytes=200-299', 1000);
    expect(plan.status).toBe(206);
    expect(plan.start).toBe(200);
    expect(plan.end).toBe(299);
    expect(plan.headers['Content-Range']).toBe('bytes 200-299/1000');
    expect(plan.headers['Content-Length']).toBe('100');
  });

  it('plans a 416 with the */size Content-Range when unsatisfiable', () => {
    const plan = planRequest('bytes=9999-', 1000);
    expect(plan.status).toBe(416);
    expect(plan.headers['Content-Range']).toBe('bytes */1000');
  });

  it('falls back to a 200 full response on a malformed header', () => {
    const plan = planRequest('bananas', 50);
    expect(plan.status).toBe(200);
    expect(plan.headers['Content-Length']).toBe('50');
  });
});

describe('videoIdFromUrl', () => {
  it('extracts the id from the canonical mstream://media/<id> form', () => {
    expect(videoIdFromUrl('mstream://media/abc123def456')).toBe('abc123def456');
    expect(videoIdFromUrl('mstream://media/abc123def456/')).toBe('abc123def456');
  });

  it('decodes percent-encoded ids', () => {
    expect(videoIdFromUrl('mstream://media/id%20with%20spaces')).toBe('id with spaces');
  });

  it('accepts the bare host form mstream://<id>', () => {
    expect(videoIdFromUrl('mstream://abc123/')).toBe('abc123');
  });

  it('ignores query strings and extra path segments', () => {
    expect(videoIdFromUrl('mstream://media/abc123?t=5')).toBe('abc123');
    expect(videoIdFromUrl('mstream://media/abc123/extra/junk')).toBe('abc123');
  });

  it('rejects non-mstream and malformed URLs', () => {
    expect(videoIdFromUrl('https://media/abc')).toBeNull();
    expect(videoIdFromUrl('not a url')).toBeNull();
    expect(videoIdFromUrl('mstream://media/')).toBeNull();
  });

  it('decodes a P4 short: prefixed id intact (C10 single-segment round-trip)', () => {
    // shortMediaUrl(path) = mstream://media/<encodeURIComponent("short:"+path)>.
    // The whole `short:<path>` must come back as ONE id (the resolver branch
    // then strips the prefix) — a two-segment media/short/<b64> would break this.
    const path = 'C:\\exports\\shorts-vid1\\clip.mp4';
    const url = `mstream://media/${encodeURIComponent(`short:${path}`)}`;
    expect(videoIdFromUrl(url)).toBe(`short:${path}`);
  });

  it('decodes a WU-3 thumb: prefixed id intact (library poster single-segment round-trip)', () => {
    // The library-poster URL is mstream://media/<encodeURIComponent("thumb:"+path)>.
    // The whole `thumb:<path>` must come back as ONE id so the resolver branch can
    // strip the prefix and traversal-guard the absolute path it encodes — exactly
    // like short:/dub:.
    const path = 'C:\\data\\thumbnails\\vid1.jpg';
    const url = `mstream://media/${encodeURIComponent(`thumb:${path}`)}`;
    expect(videoIdFromUrl(url)).toBe(`thumb:${path}`);
  });
});

describe('contentTypeFor', () => {
  it('maps known media extensions', () => {
    expect(contentTypeFor('C:/videos/talk.mp4')).toBe('video/mp4');
    expect(contentTypeFor('/data/movie.MKV')).toBe('video/x-matroska');
    expect(contentTypeFor('clip.webm')).toBe('video/webm');
    expect(contentTypeFor('song.mp3')).toBe('audio/mpeg');
  });

  it('maps short poster-frame image extensions (P4 §6)', () => {
    expect(contentTypeFor('C:/exports/shorts-v1/clip.thumb.jpg')).toBe('image/jpeg');
    expect(contentTypeFor('clip.thumb.JPEG')).toBe('image/jpeg');
    expect(contentTypeFor('poster.png')).toBe('image/png');
  });

  it('falls back to video/mp4 for unknown extensions', () => {
    expect(contentTypeFor('weird.xyz')).toBe('video/mp4');
    expect(contentTypeFor('noext')).toBe('video/mp4');
  });
});

describe('createMediaRequestHandler (end-to-end against a temp file)', () => {
  const CONTENT = '0123456789ABCDEFGHIJ'; // 20 bytes
  let dir: string;
  let filePath: string;

  beforeAll(() => {
    dir = mkdtempSync(join(tmpdir(), 'mstream-test-'));
    filePath = join(dir, 'video with spaces.mp4');
    writeFileSync(filePath, CONTENT, 'utf-8');
  });

  afterAll(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  function handler(resolver?: (id: string) => string | null) {
    return createMediaRequestHandler(resolver ?? ((id) => (id === 'vid1' ? filePath : null)));
  }

  it('serves the whole file with 200 when no Range is sent', async () => {
    const res = await handler()(new Request('mstream://media/vid1'));
    expect(res.status).toBe(200);
    expect(res.headers.get('Accept-Ranges')).toBe('bytes');
    expect(res.headers.get('Content-Type')).toBe('video/mp4');
    expect(res.headers.get('Content-Length')).toBe(String(CONTENT.length));
    expect(await res.text()).toBe(CONTENT);
  });

  it('serves a 206 slice for the Chromium open-ended range (bytes=0-)', async () => {
    const req = new Request('mstream://media/vid1', { headers: { Range: 'bytes=0-' } });
    const res = await handler()(req);
    expect(res.status).toBe(206);
    expect(res.headers.get('Content-Range')).toBe(`bytes 0-19/${CONTENT.length}`);
    expect(await res.text()).toBe(CONTENT);
  });

  it('serves exactly the requested byte slice', async () => {
    const req = new Request('mstream://media/vid1', { headers: { Range: 'bytes=5-9' } });
    const res = await handler()(req);
    expect(res.status).toBe(206);
    expect(res.headers.get('Content-Range')).toBe(`bytes 5-9/${CONTENT.length}`);
    expect(res.headers.get('Content-Length')).toBe('5');
    expect(await res.text()).toBe('56789');
  });

  it('serves a suffix range', async () => {
    const req = new Request('mstream://media/vid1', { headers: { Range: 'bytes=-4' } });
    const res = await handler()(req);
    expect(res.status).toBe(206);
    expect(await res.text()).toBe('GHIJ');
  });

  it('responds 416 to an unsatisfiable range', async () => {
    const req = new Request('mstream://media/vid1', { headers: { Range: 'bytes=999-' } });
    const res = await handler()(req);
    expect(res.status).toBe(416);
    expect(res.headers.get('Content-Range')).toBe(`bytes */${CONTENT.length}`);
  });

  it('responds 404 for an unknown videoId', async () => {
    const res = await handler()(new Request('mstream://media/nope'));
    expect(res.status).toBe(404);
  });

  it('responds 404 when the resolved file does not exist', async () => {
    const res = await handler(() => join(dir, 'gone.mp4'))(new Request('mstream://media/vid1'));
    expect(res.status).toBe(404);
  });

  it('responds 404 when the resolver throws a generic error (treated as unresolvable)', async () => {
    const throwing = createMediaRequestHandler(() => Promise.reject(new Error('sidecar down')));
    const res = await throwing(new Request('mstream://media/vid1'));
    expect(res.status).toBe(404);
  });

  it('responds 503 (not 404) when the resolver throws SidecarUnavailableError', async () => {
    // G1 robustness: a dead/throwing sidecar is TRANSIENT (retry) and must be
    // diagnosably distinct from a genuinely-absent id (404) in DevTools Network.
    const down = createMediaRequestHandler(() =>
      Promise.reject(new SidecarUnavailableError('sidecar restarting')),
    );
    const res = await down(new Request('mstream://media/vid1'));
    expect(res.status).toBe(503);
    expect(await res.text()).toContain('sidecar unavailable');
  });

  it('responds 400 for a URL without a videoId', async () => {
    const res = await handler()(new Request('mstream://media/'));
    expect(res.status).toBe(400);
  });

  it('supports an async resolver', async () => {
    const res = await createMediaRequestHandler(async () => filePath)(
      new Request('mstream://media/vid1', { headers: { Range: 'bytes=0-' } }),
    );
    expect(res.status).toBe(206);
    expect(await res.text()).toBe(CONTENT);
  });
});

describe('SidecarUnavailableError', () => {
  it('defaults its message and carries its name', () => {
    const e = new SidecarUnavailableError();
    expect(e).toBeInstanceOf(Error);
    expect(e.name).toBe('SidecarUnavailableError');
    expect(e.message).toBe('sidecar unavailable');
  });

  it('accepts a custom message', () => {
    expect(new SidecarUnavailableError('boom').message).toBe('boom');
  });
});

describe('registration plumbing', () => {
  it('registerMediaSchemePrivileges declares mstream as standard+stream', () => {
    registerMediaSchemePrivileges();
    expect(registerSchemesMock).toHaveBeenCalledTimes(1);
    const arg = registerSchemesMock.mock.calls[0][0] as Array<{
      scheme: string;
      privileges: Record<string, unknown>;
    }>;
    expect(arg[0].scheme).toBe(MEDIA_SCHEME);
    expect(arg[0].privileges.standard).toBe(true);
    expect(arg[0].privileges.stream).toBe(true);
  });

  it('registerMediaProtocol mounts a handler on the mstream scheme', () => {
    registerMediaProtocol(() => null);
    expect(handleMock).toHaveBeenCalledTimes(1);
    expect(handleMock.mock.calls[0][0]).toBe(MEDIA_SCHEME);
    expect(typeof handleMock.mock.calls[0][1]).toBe('function');
  });
});
