/**
 * Backend API access.
 *
 * The browser calls the Python API directly; the Cloudflare Worker serves this
 * app but does not proxy the backend. Identity travels as plain actor/role
 * query parameters or body fields, which the backend documents as a demo
 * simulation — there is no auth layer in front of it yet.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  `http://localhost:${process.env.AGENTIC_CM_API_PORT ?? 8000}`;

export type Identity = { actor: string; role: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    /** The backend's `detail`, when it sent one. Safe to show to the user. */
    readonly detail?: string,
  ) {
    super(detail ?? `${path} responded ${status}`);
    this.name = "ApiError";
  }
}

/** Whether a rejection is an aborted request rather than a real failure. */
export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function url(path: string, query?: Record<string, string | undefined>): string {
  const target = new URL(`${API_BASE}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) target.searchParams.set(key, value);
  }
  return target.toString();
}

async function request<T>(
  path: string,
  init: RequestInit,
  query?: Record<string, string | undefined>,
): Promise<T> {
  const response = await fetch(url(path, query), init);
  if (!response.ok) {
    // FastAPI reports domain failures as {"detail": "..."}; surface it so the
    // caller can show the real reason instead of a bare status code.
    const body = await response.json().catch(() => null);
    const detail = body && typeof body.detail === "string" ? body.detail : undefined;
    throw new ApiError(response.status, path, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function apiGet<T>(
  path: string,
  query?: Record<string, string | undefined>,
  signal?: AbortSignal,
): Promise<T> {
  return request<T>(path, { signal }, query);
}

export async function apiGetText(
  path: string,
  query?: Record<string, string | undefined>,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(url(path, query), { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body && typeof body.detail === "string" ? body.detail : undefined;
    throw new ApiError(response.status, path, detail);
  }
  return response.text();
}

export function apiUrl(path: string, query?: Record<string, string | undefined>): string {
  return url(path, query);
}

export function apiPost<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
}
