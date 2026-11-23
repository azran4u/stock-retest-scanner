import { defineConfig } from 'vite';
import { rmSync, readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// Default: built into ../app (old GitHub Pages path /stock-retest-scanner/app/).
// New host (Cloudflare Pages / Vercel, 2026-10-30): SRS_BASE=/ SRS_OUT=../dist npm run build -> site root = the app.
// App data is NOT part of the site any more: it lives in the private Supabase Storage bucket 'app-data' (read after login).
// ../app/data (local export output, gitignored) must survive builds, so emptyOutDir is off and only old hashed assets go.
const base = process.env.SRS_BASE || '/stock-retest-scanner/app/';
const outDir = process.env.SRS_OUT || '../app';
export default defineConfig({
  base,
  build: { outDir, emptyOutDir: false, target: 'es2020', chunkSizeWarningLimit: 900 },
  plugins: [{
    name: 'clean-assets',
    buildStart() { rmSync(resolve(__dirname, outDir, 'assets'), { recursive: true, force: true }); },
  }, {
    // Dev-only: serve the private lives JSON. Never emitted into app/ or dist/.
    // A file under app/ would be publicly reachable without login.
    name: 'lives-dev-json',
    configureServer(server) {
      const file = resolve('/workspace/lives/lives.json');
      server.middlewares.use((req, res, next) => {
        const url = req.url?.split('?')[0] || '';
        if (!url.endsWith('/lives-dev.json') && url !== '/lives-dev.json') return next();
        if (!existsSync(file)) { res.statusCode = 404; res.end('not found'); return; }
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(readFileSync(file));
      });
    },
  }],
});
