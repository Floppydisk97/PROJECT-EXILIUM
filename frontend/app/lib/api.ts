// Resolves the backend base URL from API_INTERNAL_URL. Render injects a bare hostname
// (via fromService), local dev uses a full URL; both normalize to a scheme + no trailing slash.
export function apiBase(): string {
  const raw = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const withScheme = /^https?:\/\//.test(raw) ? raw : `https://${raw}`;
  return withScheme.replace(/\/+$/, "");
}
