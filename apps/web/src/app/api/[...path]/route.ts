/**
 * Mandataire /api/* -> API FastAPI. L'URL interne est lue à l'exécution (API_INTERNAL_URL),
 * ce qui permet la même image en local, dans Docker Compose et dans Kubernetes.
 * Les réponses (PDF, flux SSE de l'assistant) sont relayées en continu, sans mise en mémoire.
 */
export const dynamic = "force-dynamic";

const HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length"]);

async function proxy(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const base = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  const url = new URL(req.url);
  const target = `${base}/${path.map(encodeURIComponent).join("/")}${url.search}`;
  const headers = new Headers();
  req.headers.forEach((v, k) => {
    if (!HOP.has(k.toLowerCase())) headers.set(k, v);
  });
  headers.set("x-forwarded-host", url.host);
  headers.set("x-forwarded-proto", url.protocol.replace(":", ""));
  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers, redirect: "manual" };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = req.body;
    init.duplex = "half";
  }
  const res = await fetch(target, init);
  const out = new Headers();
  res.headers.forEach((v, k) => {
    if (!HOP.has(k.toLowerCase()) && k.toLowerCase() !== "content-encoding") out.append(k, v);
  });
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
