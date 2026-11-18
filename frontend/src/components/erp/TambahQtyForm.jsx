/**
 * TAMBAH QTY — satu form untuk menambah stok TANPA produksi/pembelian (18 Nov 2026, owner: "tambahan fitur input
 * qty di portal gudang …" lalu "tambah juga untuk aksesoris dan kain").
 *
 * Dipakai di dua tempat, mesin server SAMA (`apply_material_adjust` + `source`/`unit_cost`). Berkas ini SENGAJA tidak
 * memuat alamat layanan / pemilih lokasi Gudang: alamat (`kirimKe`), pemilih lokasi (`renderLokasi`) dan cek stok
 * (`cekStok`) dikirim layar pemakainya — supaya centang Portal Aksesoris tidak ikut membuka penyesuaian stok Gudang
 * (peta menu → layanan membaca berkas yang diimpor layar).
 *   · Gudang › Stok & Akurasi › Penyesuaian (`mode="gudang"`): semua barang (barang jadi, kain, aksesoris) + lokasi;
 *     kain/benang menerbitkan GULUNGAN (Cutting wajib memilih roll) — jumlah roll + isi tiap roll.
 *   · Portal Aksesoris › Master & Stok (`mode="aksesoris"`): satu aksesoris dari baris, lokasi gudang aksesoris.
 * Keputusan owner: sumber "Stok lama belum tercatat" (lawan jurnal ekuitas saldo awal) / "Ditemukan saat hitung
 * ulang"; nilai per pcs diisi staf (kosong = HPP rata-rata, wajib bila HPP belum ada); langsung masuk stok.
 */
import { useEffect, useMemo, useState } from 'react';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { useToast } from '@/hooks/use-toast';
import { materialOptionLabel } from '@/lib/materialFields';
import { Notice } from './moduleAtoms';

export const SUMBER_TAMBAH = [
  { value: 'stok_lama', label: 'Stok lama belum tercatat' },
  { value: 'ditemukan', label: 'Ditemukan saat hitung ulang' },
];
// Satuan yang dilacak per gulungan — sama dengan server (core/fabric_roll_engine.ROLL_UOM / is_roll_material)
const SATUAN_ROLL = new Set(['kg', 'bal', 'ball', 'meter', 'm', 'mtr', 'rol', 'gulung', 'yard', 'yd']);
export const perGulungan = (m) => !!m && m.type !== 'fg' && !m.is_cut_panel
  && SATUAN_ROLL.has(String(m.unit || '').trim().toLowerCase());

const KOSONG = { material_id: '', location_id: '', qty: '', source: 'stok_lama', unit_cost: '', note: '', jml_roll: '1', isi_roll: '' };
const fmtRp = (v) => `Rp${Math.round(Number(v || 0)).toLocaleString('id-ID')}`;
const fmtQty = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 3 });

/** Isi tiap roll dari isian: daftar "25, 25, 24.5" atau dibagi rata sejumlah roll (fungsi murni, diuji). */
export function isiGulungan(qty, jmlRoll, isiTeks) {
  const q = Number(qty);
  const teks = String(isiTeks || '').trim();
  if (teks) {
    const isi = teks.split(/[;,\s]+/).filter(Boolean).map((x) => Number(x.replace(',', '.')));
    if (isi.some((x) => !(x > 0))) return { galat: 'Isi tiap roll harus angka lebih dari 0, dipisah koma.' };
    const total = isi.reduce((a, b) => a + b, 0);
    if (Math.abs(total - q) > 0.01) return { galat: `Jumlah isi roll (${fmtQty(total)}) harus sama dengan qty tambah (${fmtQty(q)}).` };
    return { isi };
  }
  const n = Math.floor(Number(jmlRoll));
  if (!(n >= 1)) return { galat: 'Jumlah roll minimal 1.' };
  const rata = Math.floor((q / n) * 100) / 100;
  const isi = Array.from({ length: n }, () => rata);
  isi[n - 1] = Math.round((q - rata * (n - 1)) * 100) / 100;
  if (isi.some((x) => !(x > 0))) return { galat: 'Qty terlalu kecil untuk dibagi ke roll sebanyak itu.' };
  return { isi };
}

export default function TambahQtyForm({ open, onClose, onSaved, token, kirimKe, materials = [], barangTetap = null,
  mode = 'gudang', renderLokasi = null, cekStok = null }) {
  const { toast } = useToast();
  const [f, setF] = useState(KOSONG);
  const [stokLokasi, setStokLokasi] = useState(null);
  const [galat, setGalat] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const aksesoris = mode === 'aksesoris';

  useEffect(() => {
    if (open) { setF({ ...KOSONG, material_id: barangTetap?.id || '' }); setGalat(''); setStokLokasi(null); }
  }, [open, barangTetap]);

  const mat = barangTetap || materials.find((m) => m.id === f.material_id);
  const hpp = Number(mat?.unit_cost || 0);
  const roll = !aksesoris && perGulungan(mat);
  const satuan = mat?.unit || '';

  const lihatStok = async (mid, lid) => {
    if (!cekStok || !mid || !lid) return;
    try { setStokLokasi((await cekStok(mid, lid)) || { qty: 0, unit: satuan }); } catch { /* info saja */ }
  };

  const simpan = async () => {
    setGalat('');
    const qty = Number(f.qty);
    if (!f.material_id) { setGalat('Pilih barang.'); return; }
    if (!aksesoris && !f.location_id) { setGalat('Pilih lokasi.'); return; }
    if (!(qty > 0)) { setGalat('Qty tambah harus lebih dari 0.'); return; }
    const nilai = f.unit_cost === '' ? null : Number(f.unit_cost);
    if (nilai !== null && !(nilai >= 0)) { setGalat('Nilai per satuan harus angka 0 atau lebih.'); return; }
    if (!(nilai > 0) && !(hpp > 0)) { setGalat('Barang ini belum punya HPP rata-rata — isi nilai per satuan.'); return; }
    let rolls;
    if (roll) {
      const g = isiGulungan(qty, f.jml_roll, f.isi_roll);
      if (g.galat) { setGalat(g.galat); return; }
      rolls = g.isi;
    }
    const label = SUMBER_TAMBAH.find((s) => s.value === f.source)?.label || '';
    const reason = f.note.trim() ? `${label} — ${f.note.trim()}` : label;
    const body = aksesoris
      ? { acc_id: f.material_id, qty, source: f.source, unit_cost: nilai > 0 ? nilai : null, reason }
      : { material_id: f.material_id, location_id: f.location_id, qty, source: f.source, unit_cost: nilai > 0 ? nilai : null, reason, rolls };
    setMenyimpan(true);
    try {
      const r = await fetch(kirimKe, { method: 'POST', headers, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { setGalat(typeof d.detail === 'string' ? d.detail : `Gagal menambah qty (HTTP ${r.status})`); return; }
      const jurnal = d?._posting_result;
      const gulung = rolls ? ` · ${rolls.length} roll diterbitkan` : '';
      if (jurnal && jurnal.ok === false) {
        toast({ title: 'Qty bertambah, jurnal belum terbentuk', description: String(jurnal.error || ''), variant: 'destructive' });
      } else {
        toast({ title: 'Qty ditambahkan', description: `${mat?.name || ''}: +${fmtQty(qty)} ${satuan} · ${label}${gulung}` });
      }
      onSaved?.(d);
      onClose?.();
    } catch {
      setGalat('Gagal menambah qty.');
    } finally {
      setMenyimpan(false);
    }
  };

  const ubah = (k) => (e) => { const v = e.target.value; setF((x) => ({ ...x, [k]: v })); };
  const rincianRoll = roll && Number(f.qty) > 0 ? isiGulungan(f.qty, f.jml_roll, f.isi_roll) : null;

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" judul={barangTetap ? `Tambah qty · ${barangTetap.name}` : 'Tambah qty'}
      keterangan={aksesoris ? 'Stok aksesoris langsung bertambah tanpa pembelian; jurnal persediaan dibuat otomatis.'
        : 'Stok langsung bertambah di lokasi terpilih; jurnal persediaan dibuat otomatis.'}
      onSimpan={simpan} menyimpan={menyimpan} galat={galat} labelSimpan="Tambah qty" testId="tambah-form">
      {!barangTetap && (
        <Isian label="Barang" wajib htmlFor="tambah-material">
          <SmartNativeSelect id="tambah-material" value={f.material_id} className="w-full" data-testid="tambah-material"
            onChange={(e) => { const v = e.target.value; setF((x) => ({ ...x, material_id: v })); setStokLokasi(null); lihatStok(v, f.location_id); }}>
            <option value="">Pilih barang</option>
            {materials.map((m) => <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}
      {!aksesoris && renderLokasi && (
        <Isian label="Lokasi" wajib>
          {renderLokasi({ value: f.location_id,
            onChange: (v) => { setF((x) => ({ ...x, location_id: v })); setStokLokasi(null); lihatStok(f.material_id, v); } })}
        </Isian>
      )}
      {stokLokasi && <Notice tone="info" title={`Stok saat ini di lokasi ini: ${fmtQty(stokLokasi.qty)} ${stokLokasi.unit || satuan}`} />}
      <Isian label={`Qty tambah${satuan ? ` (${satuan})` : ''}`} wajib htmlFor="tambah-qty">
        <Input id="tambah-qty" type="number" inputMode="decimal" value={f.qty} placeholder="Contoh: 24"
          onChange={ubah('qty')} data-testid="tambah-qty" />
      </Isian>
      {roll && <>
        <Isian label="Jumlah roll" wajib htmlFor="tambah-jml-roll" petunjuk="Kain dilacak per gulungan; nomor roll dibuat otomatis.">
          <Input id="tambah-jml-roll" type="number" inputMode="numeric" value={f.jml_roll} disabled={!!f.isi_roll.trim()}
            onChange={ubah('jml_roll')} data-testid="tambah-jml-roll" />
        </Isian>
        <Isian label={`Isi tiap roll (${satuan})`} htmlFor="tambah-isi-roll"
          petunjuk={rincianRoll?.galat ? rincianRoll.galat
            : rincianRoll?.isi ? `Roll: ${rincianRoll.isi.map(fmtQty).join(' · ')} ${satuan}. Kosongkan untuk dibagi rata.`
              : 'Opsional, pisahkan dengan koma (mis. 25, 25, 24.5). Kosong = dibagi rata.'}>
          <Input id="tambah-isi-roll" value={f.isi_roll} placeholder="Contoh: 25, 25, 24.5"
            onChange={ubah('isi_roll')} data-testid="tambah-isi-roll" />
        </Isian>
      </>}
      <Isian label="Sumber" wajib htmlFor="tambah-sumber">
        <SmartNativeSelect id="tambah-sumber" value={f.source} searchable={false} className="w-full" data-testid="tambah-sumber"
          onChange={ubah('source')}>
          {SUMBER_TAMBAH.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label={`Nilai per ${satuan || 'satuan'} (Rp)`} wajib={!!mat && !(hpp > 0)} htmlFor="tambah-nilai"
        petunjuk={!mat ? 'Pilih barang dulu untuk melihat HPP rata-ratanya.'
          : hpp > 0 ? `HPP rata-rata sekarang ${fmtRp(hpp)}. Kosongkan untuk memakai angka ini.`
            : 'Barang ini belum punya HPP rata-rata — wajib diisi.'}>
        <Input id="tambah-nilai" type="number" inputMode="decimal" value={f.unit_cost}
          placeholder={hpp > 0 ? String(Math.round(hpp)) : 'Contoh: 45000'} onChange={ubah('unit_cost')} data-testid="tambah-nilai" />
      </Isian>
      <Isian label="Catatan" htmlFor="tambah-catatan">
        <Textarea id="tambah-catatan" rows={2} value={f.note} placeholder="Contoh: stok lama di rak belakang belum masuk saat cutoff"
          onChange={ubah('note')} data-testid="tambah-catatan" />
      </Isian>
    </FormPopup>
  );
}
