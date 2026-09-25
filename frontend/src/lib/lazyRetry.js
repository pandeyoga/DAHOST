import { lazy } from 'react';
import { isChunkLoadError, reloadOnceForNewBuild } from '../components/ErrorBoundary';

// lazy() yang tahan ChunkLoadError: coba ulang impor 2× (jeda 800 ms), lalu muat ulang halaman
// sekali bila server sudah memakai build baru (hash chunk berubah setelah rebuild).
export function lazyRetry(factory, retries = 2) {
  const attempt = (n) => factory().catch((err) => {
    if (!isChunkLoadError(err)) throw err;
    if (n > 0) return new Promise((r) => setTimeout(r, 800)).then(() => attempt(n - 1));
    if (reloadOnceForNewBuild()) return new Promise(() => {}); // halaman sedang dimuat ulang
    throw err;
  });
  return lazy(() => attempt(retries));
}
