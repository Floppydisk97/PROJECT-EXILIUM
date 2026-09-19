// Resolves the backend base URL from API_INTERNAL_URL: wherever the API answers from the
// server side, which is not the same address in every deployment. Under docker compose it is
// the service name on the internal network; on Render it is deliberately the *public* URL,
// because a private-network call does not wake a sleeping free instance -- see render.yaml.
// A bare hostname gets https://; a full URL is kept as is. Either way, no trailing slash.
export function apiBase(): string {
  const raw = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const withScheme = /^https?:\/\//.test(raw) ? raw : `https://${raw}`;
  return withScheme.replace(/\/+$/, "");
}
