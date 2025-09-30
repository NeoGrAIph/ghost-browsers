function parseVncUrl(raw?: string | null): URL | null {
  if (!raw) return null;

  const createUrl = (value: string) => {
    if (typeof window !== 'undefined') {
      return new URL(value, window.location.origin);
    }
    return new URL(value);
  };

  try {
    const url = createUrl(raw);
    const targetPort = url.searchParams.get('target_port');
    const pathValue = url.searchParams.get('path');

    if (targetPort && pathValue) {
      const [pathBase, rawQuery] = pathValue.split('?', 2);
      const pathQuery = new URLSearchParams(rawQuery ?? '');
      if (!pathQuery.has('target_port')) {
        pathQuery.set('target_port', targetPort);
        const serialisedQuery = pathQuery.toString();
        url.searchParams.set('path', serialisedQuery ? `${pathBase}?${serialisedQuery}` : pathBase);
      }
    }

    url.searchParams.set('autoconnect', '1');
    url.searchParams.set('reconnect', 'true');
    return url;
  } catch (error) {
    console.warn('Failed to build VNC URL', error);
    return null;
  }
}

export function buildVncEmbedUrl(raw?: string | null): string | null {
  const url = parseVncUrl(raw);
  if (!url) return raw ?? null;
  url.searchParams.set('resize', 'scale');
  url.searchParams.set('view_only', 'true');
  return url.toString();
}

export function buildVncViewerUrl(raw?: string | null): string | null {
  const url = parseVncUrl(raw);
  if (!url) return raw ?? null;
  url.searchParams.set('view_only', 'true');
  return url.toString();
}
