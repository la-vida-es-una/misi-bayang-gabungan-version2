/**
 * Node/Esbuild fallback for MultiUAV UI Reimagined
 * Use this if you don't have Bun installed.
 */
import * as esbuild from 'esbuild';
import http from 'http';
import fs from 'fs';
import path from 'path';

const PORT = 3001;

async function build() {
    console.log("[build] Started...");
    try {
        await esbuild.build({
            entryPoints: ['./src/main.tsx'],
            bundle: true,
            outfile: './dist/main.js',
            sourcemap: true,
            minify: false,
            format: 'esm',
            loader: { 
              '.tsx': 'tsx', 
              '.ts': 'ts', 
              '.css': 'css',
              '.png': 'dataurl',
              '.svg': 'dataurl',
              '.jpg': 'dataurl'
            },
        });
        console.log("[build] Success!");
    } catch (err) {
        console.error("[build] Error during build:", err);
    }
}

// Initial build
await build();

const server = http.createServer(async (req, res) => {
    let urlPath = req.url === "/" ? "/index.html" : req.url;
    let filePath = path.join(process.cwd(), urlPath);
    
    if (!fs.existsSync(filePath)) {
        filePath = path.join(process.cwd(), 'dist', urlPath);
    }

    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const ext = path.extname(filePath);
        const contentType = {
            '.html': 'text/html',
            '.js': 'text/javascript',
            '.css': 'text/css',
        }[ext] || 'text/plain';

        res.writeHead(200, { 'Content-Type': contentType });
        fs.createReadStream(filePath).pipe(res);
    } else {
        // SPA Fallback
        res.writeHead(200, { 'Content-Type': 'text/html' });
        fs.createReadStream(path.join(process.cwd(), 'index.html')).pipe(res);
    }
});

server.listen(PORT, () => {
    console.log(`[server] Running at http://localhost:${PORT}`);
});

// Simple watch logic
fs.watch("./src", { recursive: true }, async (event, filename) => {
    console.log(`[watch] ${filename} changed, rebuilding...`);
    await build();
});
