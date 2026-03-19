/**
 * Bun dev server for MultiUAV UI Reimagined
 */
import { watch } from "fs";

const PORT = 3000;
const BACKEND = "http://localhost:8000";

// Proxy these path prefixes to the backend
const PROXY_PREFIXES = ["/mission", "/mcp", "/health"];

const DEBUG = process.env.NODE_ENV !== "production";
function dlog(tag: string, message: string, data?: object) {
  if (DEBUG) {
    console.log(`[${tag}] ${message}`, data || "");
  }
}

async function build() {
  console.log("[build] Started...");
  try {
    const result = await Bun.build({
      entrypoints: ["./src/main.tsx"],
      outdir: "./dist",
      target: "browser",
      sourcemap: "linked",
      minify: false,
    });

    if (!result.success) {
      console.error("[build] Failed:", result.logs);
    } else {
      console.log("[build] Success!");
    }
  } catch (err) {
    console.error("[build] Error during build:", err);
  }
}

// Initial build
await build();

const server = Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const path = url.pathname;

    // ── Proxy to backend ───────────────────────────────────────────────────
    if (PROXY_PREFIXES.some((prefix) => path.startsWith(prefix))) {
      const target = `${BACKEND}${path}${url.search}`;
      dlog("proxy", `${req.method} ${path} → ${target}`);

      try {
        // Forward headers, method, body — but strip the host header
        // so the backend sees itself, not the dev server.
        const headers = new Headers(req.headers);
        headers.delete("host");

        const upstream = await fetch(target, {
          method: req.method,
          headers,
          body: req.method !== "GET" && req.method !== "HEAD"
            ? req.body
            : undefined,
          // Required for SSE: do not buffer the response
          // @ts-ignore — Bun-specific option
          redirect: "follow",
        });

        // Pass the upstream response through unchanged.
        // This preserves Content-Type: text/event-stream for SSE.
        return new Response(upstream.body, {
          status: upstream.status,
          statusText: upstream.statusText,
          headers: upstream.headers,
        });
      } catch (err) {
        console.error(`[proxy] Failed to reach backend at ${target}:`, err);
        return new Response(
          JSON.stringify({ error: "Backend unreachable", detail: String(err) }),
          { status: 502, headers: { "Content-Type": "application/json" } }
        );
      }
    }

    // ── Static file serving ────────────────────────────────────────────────
    const filePath = path === "/" ? "/index.html" : path;

    let file = Bun.file("." + filePath);
    if (!(await file.exists())) {
      file = Bun.file("./dist" + filePath);
    }

    if (await file.exists()) {
      dlog("static", "Serving static file", { path: filePath });
      return new Response(file);
    }

    // SPA fallback — let React Router (if used) handle the path
    dlog("static", "Serving SPA fallback", { path });
    return new Response(Bun.file("./index.html"));
  },
});

console.log(`[server] Running at http://localhost:${PORT}`);
console.log(`[proxy]  /mission/* /mcp/* → ${BACKEND}`);

// Watch for changes and rebuild
watch("./src", { recursive: true }, async (event, filename) => {
  console.log(`[watch] ${filename} changed, rebuilding...`);
  await build();
});
