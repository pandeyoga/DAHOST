/**
 * NegativeStockModule — laporan "Stok Minus" (mode sementara sebelum stock opname).
 *
 * 2026-09-23, keputusan owner: klien belum opname tetapi produksi harus jalan, jadi
 * pengeluaran material boleh membuat saldo minus (setelan `inventory_allow_negative`).
 * Layar ini = daftar yang HARUS dibetulkan lewat opname; saat opname, qty aktual
 * menimpa nilai minus.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

export default function NegativeStockModule({ token }) {
  const [rows, setRows] = useState([]);
  const [flag, setFlag] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const headers = { Authorization: `Bearer ${token}` };
    try {
      const [r, c] = await Promise.all([
        fetch('/api/rahaza/material-stock?negative=1', { headers }).then(x => (x.ok ? x.json() : [])),
        fetch('/api/dewi/system/config/inventory_allow_negative', { headers }).then(x => (x.ok ? x.json() : null)),
      ]);
      setRows(Array.isArray(r) ? r : []);
      setFlag(c);
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const on = flag ? (flag.value === true || String(flag.value).toLowerCase() === 'true') : null;

  return (
    <div className="space-y-4" data-testid="negative-stock-module">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base md:text-lg font-bold text-foreground">Stok Minus</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Baris stok bersaldo negatif akibat pengeluaran material sebelum stock opname. Betulkan lewat Opname Stok
            — qty hasil hitung fisik akan menimpa nilai minus.
          </p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-1.5 text-xs px-3 h-8 rounded-lg border border-border hover:bg-muted/50"
          data-testid="negative-stock-refresh">
          <RefreshCw size={13} /> Muat ulang
        </button>
      </div>

      {on !== null && (
        <div className={`rounded-lg border px-3 py-2 text-xs flex items-center gap-2 ${on ? 'border-amber-300 bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300' : 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300'}`}
          data-testid="negative-stock-mode">
          <AlertTriangle size={14} />
          {on
            ? 'Mode "Stok Boleh Minus" AKTIF — pengeluaran material tidak ditolak walau stok kurang. Matikan di Administrasi Sistem → Konfigurasi Sistem → Gudang & Stok setelah opname selesai.'
            : 'Mode "Stok Boleh Minus" NONAKTIF — pengeluaran material ditolak bila stok kurang.'}
        </div>
      )}

      <div className="rounded-xl border border-border overflow-hidden">
        <table className="w-full text-xs" data-testid="negative-stock-table">
          <thead className="bg-muted/40">
            <tr>
              <th className="text-left px-3 py-2">Kode</th>
              <th className="text-left px-3 py-2">Material</th>
              <th className="text-left px-3 py-2">Lokasi</th>
              <th className="text-right px-3 py-2">Qty</th>
              <th className="text-left px-3 py-2">Satuan</th>
              <th className="text-left px-3 py-2">Terakhir berubah</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">Memuat…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground" data-testid="negative-stock-empty">
                Tidak ada stok minus.
              </td></tr>
            ) : rows.map(r => (
              <tr key={r.id || `${r.material_id}-${r.location_id}`} className="border-t border-border/60 bg-rose-50/40 dark:bg-rose-500/5"
                data-testid={`negative-stock-row-${r.material_code}`}>
                <td className="px-3 py-1.5 font-mono text-blue-700">{r.material_code}</td>
                <td className="px-3 py-1.5">{r.material_name}</td>
                <td className="px-3 py-1.5">{r.location_code || '-'} {r.location_name ? `· ${r.location_name}` : ''}</td>
                <td className="px-3 py-1.5 text-right font-bold text-rose-700">{fmt(r.qty)}</td>
                <td className="px-3 py-1.5">{r.unit || '-'}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{r.updated_at ? new Date(r.updated_at).toLocaleString('id-ID') : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="negative-stock-count">{rows.length} baris stok minus.</p>
      )}
    </div>
  );
}
