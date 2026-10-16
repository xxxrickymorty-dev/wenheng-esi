import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB_MODULES = path.resolve(HERE, '../../../web/node_modules');
const EVIDENCE_DIR = path.resolve(HERE, '..', 'material-evidence');

function serveMaterialEvidence() {
  return {
    name: 'serve-material-evidence',
    configureServer(server) {
      server.middlewares.use('/material-evidence', (req, res, next) => {
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(EVIDENCE_DIR, rel);
        if (!file.startsWith(EVIDENCE_DIR)) {
          res.statusCode = 403;
          res.end('forbidden');
          return;
        }
        if (fs.existsSync(file) && fs.statSync(file).isFile()) {
          res.setHeader('Content-Type', file.endsWith('.json') ? 'application/json' : 'image/png');
          res.setHeader('Cache-Control', 'no-cache');
          fs.createReadStream(file).pipe(res);
          return;
        }
        next();
      });
    },
  };
}

// Plain object export: importing `vite` here fails because the preview folder has no
// node_modules of its own; the aliases resolve everything from the web workspace.
export default {
  root: '.',
  server: { port: 5199, strictPort: true, host: '127.0.0.1' },
  plugins: [serveMaterialEvidence()],
  resolve: {
    alias: {
      three: path.join(WEB_MODULES, 'three'),
    },
  },
};
