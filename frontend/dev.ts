/**
 * Bun dev server for MultiUAV UI Reimagined
 */
import { watch } from "fs";

const PORT = 3000;

// Simple debug logger
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
    let path = url.pathname === "/" ? "/index.html" : url.pathname;
    
    // Serve from root or dist
    let file = Bun.file("." + path);
    if (!(await file.exists())) {
      file = Bun.file("./dist" + path);
    }

    if (await file.exists()) {
      dlog("static", "Serving static file", { path });
      return new Response(file);
    }

    // SPA fallback
    dlog("static", "Serving SPA fallback", { path });
    return new Response(Bun.file("./index.html"));
  },
});

console.log(`[server] Running at http://localhost:${PORT}`);

// Watch for changes
watch("./src", { recursive: true }, async (event, filename) => {
  console.log(`[watch] ${filename} changed, rebuilding...`);
  await build();
});
