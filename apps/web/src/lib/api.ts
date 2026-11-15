import createClient from "openapi-fetch";

import type { components, paths } from "@/lib/api-types";

/** Client typé généré depuis la spécification OpenAPI de FastAPI (make openapi). */
export const api = createClient<paths>({ baseUrl: "/api", credentials: "include" });
export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function detail(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? "").join(" ");
  }
  return "Une erreur est survenue.";
}

/** Déballe une réponse openapi-fetch : lève ApiError sur erreur, redirige sur 401 / 409. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.response.status === 401 && typeof window !== "undefined") {
    window.location.href = "/connexion";
  }
  if (res.response.status === 409 && typeof window !== "undefined" && !window.location.pathname.startsWith("/accueil")) {
    window.location.href = "/accueil";
  }
  if (res.error !== undefined || res.data === undefined) {
    if (res.response.ok && res.data === undefined) return undefined as T;
    throw new ApiError(res.response.status, detail(res.error));
  }
  return res.data;
}
