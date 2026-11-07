/**
 * LiveSessionProductsEditor — RINCIAN PRODUK PER SESI LIVE (F18#3).
 *
 * KENAPA LAYAR INI ADA
 * --------------------
 * Sesudah live selesai, pertanyaan pertama pemilik toko selalu sama: "tadi barang
 * mana yang paling laku?" — karena jawabannya menentukan apa yang dibawakan besok
 * dan berapa yang disiapkan gudang. Sebelum ini aplikasi tidak bisa menjawab:
 * endpoint `live/analytics/product-performance` membaca `products[]` yang TIDAK
 * PUNYA SATU PUN JALAN PENGISIAN, jadi laporannya selalu kosong.
 *
 * DUA KEPUTUSAN YANG TERLIHAT DI LAYAR INI
 *   · Produk DIPILIH dari katalog toko (bukan diketik). Nama, SKU, dan HPP ikut
 *     master, supaya "produk terlaris" tidak terpecah karena beda ejaan.
 *   · Rekonsiliasi ditampilkan HIDUP: jumlah rincian vs omzet sesi. Rincian yang
 *     melebihi omzet sesi berarti uang dihitung dua kali — dan itu ditolak server,
 *     jadi lebih baik terlihat di sini sebelum tombol simpan ditekan.
 *
 * Standar UI/UX v2 (8 Nov 2026): tabel isian = ui/table (dulu <table> buatan sendiri), pilihan produk =
 * SmartNativeSelect yang bisa dicari, tombol type="button" (form kini FormPopup: tanpa itu tombol ikut
 * menyimpan), warna token, huruf besar hanya di awal. Katalog dimuat sampai 1000 produk: dulu dikirim
 * `page_size` yang diabaikan server (parameternya `limit`, bawaan 100) → produk ke-101 dst. tidak bisa dipilih
 * (katalog uji terbesar 197 produk).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2, Package, AlertTriangle, CheckCircle2, Loader2, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import axios from 'axios';

const API = process.env.REACT_APP_BACKEND_URL;
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
/**
 * Persen dengan pembulatan SAMA seperti server (`core.marketing_live_products.pct`).
 * Sebelumnya baris rekonsiliasi menghitung sendiri dan membulatkan ke bilangan
 * bulat, sehingga satu angka cakupan tampil "69%" di sini, "69.5%" di kolom
 * tabel, dan "70%" di pesan server — pada dialog yang SAMA.
 */
const fmtPct = (v) => {
  const f = Math.round((Number(v) || 0) * 10) / 10;
  return Number.isInteger(f) ? `${f}%` : `${f.toFixed(1)}%`;
};

function authHeader(token) {
  return { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
}

export function reconcileLocal(lines, sessionRevenue) {
  const totalRevenue = lines.reduce((a, l) => a + num(l.revenue), 0);
  const totalUnits = lines.reduce((a, l) => a + num(l.units_sold), 0);
  const sRev = num(sessionRevenue);
  const over = sRev > 0 && totalRevenue > sRev * 1.02;
  const unallocated = Math.max(sRev - totalRevenue, 0);
  const coverage = sRev > 0 ? Math.round((totalRevenue / sRev) * 1000) / 10 : 0;
  return { totalRevenue, totalUnits, sRev, over, unallocated, coverage };
}

/** Baris rincian: produk (pilihan katalog) + unit + omzet. */
function Row({ items, line, onChange, onRemove, index, disabled }) {
  const item = items.find((i) => i.id === line.catalog_item_id) || null;
  const priceAvg = num(line.units_sold) ? num(line.revenue) / num(line.units_sold) : 0;
  const margin = item ? num(line.revenue) - num(item.hpp) * num(line.units_sold) : null;

  return (
    <TableRow className="align-top" data-testid={`lp-row-${index}`}>
      <TableCell className="min-w-[220px]">
        <SmartNativeSelect
          value={line.catalog_item_id || ''}
          onChange={(e) => onChange({ ...line, catalog_item_id: e.target.value })}
          disabled={disabled || items.length === 0}
          searchable
          data-testid={`lp-item-${index}`}
        >
          <option value="">{items.length ? 'Pilih produk katalog…' : 'Katalog kosong'}</option>
          {items.map((i) => <option key={i.id} value={i.id}>{`${i.sku ? `${i.sku} · ` : ''}${i.name}`}</option>)}
        </SmartNativeSelect>
        {item && (
          <p className="mt-1 text-xs text-muted-foreground">
            HPP master {rp(item.hpp)} · harga jual {rp(item.harga_jual || item.price)}
          </p>
        )}
      </TableCell>
      <TableCell className="w-[110px]">
        <Input type="number" min="0" className="tabular-nums" aria-label="Unit terjual"
          value={line.units_sold ?? ''} disabled={disabled}
          data-testid={`lp-units-${index}`}
          onChange={(e) => onChange({ ...line, units_sold: e.target.value })} />
      </TableCell>
      <TableCell className="w-[150px]">
        <MoneyInput className="tabular-nums" aria-label="Omzet"
          value={line.revenue ?? ''} disabled={disabled}
          data-testid={`lp-revenue-${index}`}
          onChange={(e) => onChange({ ...line, revenue: e.target.value })} />
      </TableCell>
      <TableCell className="w-[110px]">
        <Input type="number" min="0" className="tabular-nums" aria-label="Pesanan"
          value={line.orders ?? ''} disabled={disabled}
          data-testid={`lp-orders-${index}`}
          onChange={(e) => onChange({ ...line, orders: e.target.value })} />
      </TableCell>
      <TableCell className="whitespace-nowrap text-sm tabular-nums text-muted-foreground">
        {rp(Math.round(priceAvg))}
        {margin !== null && (
          <div className={margin >= 0 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}>
            margin {rp(Math.round(margin))}
          </div>
        )}
      </TableCell>
      <TableCell>
        <Button type="button" variant="ghost" size="icon-sm" className="text-[hsl(var(--danger-text))]"
          disabled={disabled} data-testid={`lp-remove-${index}`} title="Hapus baris" aria-label="Hapus baris"
          onClick={onRemove}>
          <Trash2 />
        </Button>
      </TableCell>
    </TableRow>
  );
}

export default function LiveSessionProductsEditor({
  token, accountId, lines, onChange, sessionRevenue = 0, disabled = false,
}) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!accountId) { setItems([]); return; }
      setLoading(true);
      try {
        const cats = await axios.get(`${API}/api/marketing/catalogs`, {
          headers: authHeader(token), params: { account_id: accountId },
        });
        const list = cats.data?.catalogs || cats.data?.data || [];
        const all = [];
        for (const c of list) {
          const r = await axios.get(`${API}/api/marketing/catalogs/${c.id}/items`, {
            headers: authHeader(token), params: { page_size: 200, limit: 1000 },
          });
          all.push(...(r.data?.items || r.data?.data || []));
        }
        if (alive) setItems(all);
      } catch (e) {
        if (alive) setItems([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [token, accountId]);

  const rec = useMemo(() => reconcileLocal(lines || [], sessionRevenue),
    [lines, sessionRevenue]);

  const setLine = (i, next) => {
    const copy = [...lines];
    copy[i] = next;
    onChange(copy);
  };
  const removeLine = (i) => onChange(lines.filter((_, idx) => idx !== i));
  const addLine = () => onChange([...(lines || []),
    { catalog_item_id: '', units_sold: '', revenue: '', orders: '' }]);

  const dupe = useMemo(() => {
    const seen = new Set();
    for (const l of lines || []) {
      if (!l.catalog_item_id) continue;
      if (seen.has(l.catalog_item_id)) return true;
      seen.add(l.catalog_item_id);
    }
    return false;
  }, [lines]);

  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--glass-border)] bg-card"
      data-testid="live-products-editor">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--glass-border)] px-3 py-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <Package className="h-4 w-4" /> Rincian produk terjual
          <span className="font-normal text-muted-foreground">— barang mana yang paling laku saat live</span>
        </p>
        <Button type="button" size="sm" variant="outline" onClick={addLine}
          disabled={disabled || !accountId} data-testid="live-products-add">
          <Plus /> Tambah produk
        </Button>
      </div>

      {!accountId ? (
        <p className="px-3 py-4 text-sm text-muted-foreground">
          Pilih toko dulu — produk hanya boleh diambil dari katalog toko itu.
        </p>
      ) : loading ? (
        <p className="flex items-center gap-1.5 px-3 py-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Memuat katalog toko…
        </p>
      ) : items.length === 0 ? (
        <p className="flex items-start gap-1.5 px-3 py-4 text-sm text-[hsl(var(--warning-text))]">
          <AlertTriangle className="mt-px h-4 w-4 shrink-0" />
          <span>Katalog toko ini masih kosong. Isi dulu di <b>Manajemen katalog</b> — rincian live harus menunjuk
            produk master supaya bisa dijumlahkan per produk.</span>
        </p>
      ) : (lines || []).length === 0 ? (
        <div className="flex items-start gap-1.5 px-3 py-4 text-sm text-muted-foreground">
          <Info className="mt-px h-4 w-4 shrink-0" />
          <span>
            Belum ada rincian. Tekan <b>Tambah produk</b> untuk mencatat apa saja yang
            laku di sesi ini — atau impor massal lewat <b>Impor data › Rincian produk per sesi live</b>.
            Total sesi tetap terhitung tanpa rincian, hanya laporan per produk yang kosong.
          </span>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              {['Produk (katalog toko)', 'Unit terjual', 'Omzet (Rp)', 'Pesanan', 'Harga rata-rata', ''].map((h) => (
                <TableHead key={h} className="whitespace-nowrap">{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {lines.map((l, i) => (
              <Row key={l.id || `new-${i}`} items={items} line={l} index={i}
                disabled={disabled}
                onChange={(n) => setLine(i, n)} onRemove={() => removeLine(i)} />
            ))}
          </TableBody>
        </Table>
      )}

      {/* Rekonsiliasi — satu tempat, angka sama dengan yang dipakai server */}
      {(lines || []).length > 0 && (
        <div className="space-y-1.5 border-t border-[var(--glass-border)] px-3 py-2" data-testid="live-products-recon">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm tabular-nums">
            <span>Rincian: <b>{rec.totalUnits}</b> unit · <b>{rp(rec.totalRevenue)}</b></span>
            <span className="text-muted-foreground">Omzet sesi: {rp(rec.sRev)}</span>
            {rec.sRev > 0 && !rec.over && (
              <span className="text-muted-foreground">
                Belum terinci: <b>{rp(rec.unallocated)}</b> ({fmtPct(rec.coverage)} terinci)
              </span>
            )}
          </div>
          {rec.sRev > 0 && (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div className={`h-full ${rec.over ? 'bg-[hsl(var(--destructive))]' : 'bg-[hsl(var(--success))]'}`}
                style={{ width: `${Math.min(rec.coverage, 100)}%` }} />
            </div>
          )}
          {dupe && (
            <p className="flex items-start gap-1 text-sm text-[hsl(var(--danger-text))]">
              <AlertTriangle className="mt-px h-4 w-4 shrink-0" />
              Ada produk yang sama dua kali. Gabungkan jadi satu baris — kalau dobel,
              “produk terlaris” menghitungnya dua kali.
            </p>
          )}
          {rec.over && (
            <p className="flex items-start gap-1 text-sm text-[hsl(var(--danger-text))]">
              <AlertTriangle className="mt-px h-4 w-4 shrink-0" />
              Rincian ({rp(rec.totalRevenue)}) melebihi omzet sesi ({rp(rec.sRev)}).
              Salah satunya keliru — server akan menolak sampai diperbaiki.
            </p>
          )}
          {!rec.over && rec.sRev > 0 && rec.unallocated <= Math.max(rec.sRev * 0.02, 1) && (
            <p className="flex items-center gap-1 text-sm text-[hsl(var(--success-text))]">
              <CheckCircle2 className="h-4 w-4" /> Rincian sudah menjelaskan seluruh omzet sesi.
            </p>
          )}
          {rec.sRev <= 0 && rec.totalRevenue > 0 && (
            <p className="text-sm text-[hsl(var(--warning-text))]">
              Omzet sesi masih Rp 0 sementara rincian sudah {rp(rec.totalRevenue)}.
              Isi omzet sesi, atau pakai tombol <b>Samakan total sesi</b> sesudah disimpan.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
