const ALLOWED_PROTOCOLS = new Set(["http:", "https:", "blob:"]);

export function toSafeUrl(raw: string | null | undefined): string | null {
  if (!raw) {
    return null;
  }

  try {
    const parsed = new URL(raw, window.location.origin);
    if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}
