const MEDIA_PROTOCOLS = new Set(["http:", "https:", "blob:"]);
const EXTERNAL_PROTOCOLS = new Set(["http:", "https:"]);

function parseSafe(raw: string | null | undefined): URL | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    return new URL(trimmed, window.location.origin);
  } catch {
    return null;
  }
}

function hasCredentials(url: URL): boolean {
  return Boolean(url.username || url.password);
}

export function toSafeUrl(raw: string | null | undefined): string | null {
  return toSafeMediaUrl(raw);
}

export function toSafeMediaUrl(raw: string | null | undefined): string | null {
  const parsed = parseSafe(raw);
  if (!parsed) return null;
  if (!MEDIA_PROTOCOLS.has(parsed.protocol)) return null;
  if (hasCredentials(parsed)) return null;
  return parsed.toString();
}

export function toSafeExternalUrl(raw: string | null | undefined): string | null {
  const parsed = parseSafe(raw);
  if (!parsed) return null;
  if (!EXTERNAL_PROTOCOLS.has(parsed.protocol)) return null;
  if (hasCredentials(parsed)) return null;
  return parsed.toString();
}
