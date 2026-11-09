/**
 * Impor roll kain massal untuk STOK AWAL (2026-11-09, klarifikasi owner C5).
 *
 * Alur: unduh template → isi kode kain, lokasi, lot, jumlah roll, isi per roll (kosong = rata-rata 25 kg /
 * 115 yard, ditandai "rata-rata") → Periksa (pratinjau, tanpa menulis) → Terapkan. Terapkan membuat roll
 * (menunggu persetujuan) + satu sesi "Opname stok awal" per lokasi; stok kain & nilainya masuk setelah
 * Keuangan/owner menyetujui sesi itu di Gudang → Sesi Opname. Berkas yang sama tidak diimpor dua kali.
 */
import { useState } from 'react';
import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TabelData from '@/components/ui/tabel-data';
import { apiFetch } from '@/lib/api';
import { toast } from 'sonner';
import { Notice } from '../moduleAtoms';

const BASE = '/api/wms/fabric-rolls/import';
const fmt = (n, d = 2) => new Intl.NumberFormat('id-ID', { maximumFractionDigits: d }).format(n ?? 0);
const errText = (d, fb) => (typeof d?.detail === 'string' ? d.detail : d?.detail?.message || fb);

export default function RollImportPopup({ open, onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const tutup = () => { if (!busy) { setFile(null); setPreview(null); setErr(''); onClose(); } };

  const unduhTemplate = async () => {
    try {
      const r = await apiFetch(`${BASE}/template`);
      if (!r.ok) { toast.error('Template gagal diunduh'); return; }
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement('a');
      a.href = url; a.download = 'template_impor_roll_kain.xlsx'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) { toast.error(e.message); }
  };

  const kirim = async (path) => {
    const fd = new FormData();
    fd.append('file', file);
    const r = await apiFetch(`${BASE}/${path}`, { method: 'POST', body: fd });
    const d = await r.json().catch(() => ({}));
    return [r, d];
  };

  const periksa = async () => {
    if (!file) { setErr('Pilih berkas Excel dulu.'); return; }
    setBusy(true); setErr('');
    try {
      const [r, d] = await kirim('preview');
      if (!r.ok) { setErr(errText(d, 'Pratinjau gagal')); return; }
      setPreview(d);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const terapkan = async () => {
    setBusy(true); setErr('');
    try {
      const [r, d] = await kirim('apply');
      if (!r.ok) {
        const list = d?.detail?.errors;
        setErr(list?.length ? `${errText(d, 'Gagal')} ${list.slice(0, 3).join(' · ')}` : errText(d, 'Impor gagal'));
        return;
      }
      toast.success(d.message || 'Impor roll diterapkan');
      onDone?.(d);
      setFile(null); setPreview(null); onClose();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const siap = preview?.ok;
  const t = preview?.totals || {};
  return (
    <FormPopup open={open} onClose={tutup} ukuran="panjang" testId="roll-import-dialog"
      judul="Impor roll kain (stok awal)"
      keterangan="Satu baris = satu kelompok roll. Isi per roll kosong = rata-rata 25 kg / 115 yard (ditandai). Stok & nilai kain masuk setelah Keuangan menyetujui sesi Opname stok awal."
      onSimpan={siap ? terapkan : periksa} menyimpan={busy} galat={err}
      labelSimpan={siap ? 'Terapkan' : 'Periksa berkas'} bisaSimpan={!!file}
      aksiKiri={<Button type="button" variant="outline" onClick={unduhTemplate} data-testid="roll-import-template"><Download />Template</Button>}>
      <Isian label="Berkas Excel (.xlsx)" wajib htmlFor="roll-import-file">
        <input id="roll-import-file" type="file" accept=".xlsx" data-testid="roll-import-file"
          className="block w-full text-sm"
          onChange={(e) => { setFile(e.target.files?.[0] || null); setPreview(null); setErr(''); }} />
      </Isian>
      {preview && (
        <>
          <p className="text-sm text-muted-foreground" data-testid="roll-import-summary">
            {fmt(t.rolls, 0)} roll dalam {fmt(t.groups, 0)} kain × lokasi ({fmt(t.locations, 0)} lokasi) · nilai {`Rp ${fmt(t.value, 0)}`}
            {t.average_rolls ? ` · ${fmt(t.average_rolls, 0)} roll memakai rata-rata` : ''}
          </p>
          {(preview.errors || []).length > 0 && (
            <Notice tone="danger" title={`${preview.errors.length} baris belum bisa diimpor`} testId="roll-import-errors">
              <ul className="ml-4 list-disc">{preview.errors.slice(0, 30).map((x) => <li key={x}>{x}</li>)}</ul>
            </Notice>
          )}
          {(preview.warnings || []).length > 0 && (
            <Notice tone="warning" title="Perhatian" testId="roll-import-warnings">
              <ul className="ml-4 list-disc">{preview.warnings.slice(0, 20).map((x) => <li key={x}>{x}</li>)}</ul>
            </Notice>
          )}
          <TabelData baris={preview.groups || []} kunci={(g) => `${g.material_id}-${g.location_id}`} testId="roll-import-groups"
            kosong={<p className="py-4 text-center text-sm text-muted-foreground">Tidak ada baris yang lolos.</p>}
            kolom={[
              { kunci: 'kain', label: 'Kain', hp: 'judul', isi: (g) => <span className="font-medium">{g.code}</span> },
              { kunci: 'nama', label: 'Nama', hp: 'keterangan', isi: (g) => g.name },
              { kunci: 'lokasi', label: 'Lokasi', isi: (g) => g.location_code },
              { kunci: 'roll', label: 'Roll', rata: 'kanan', isi: (g) => fmt(g.rolls, 0) },
              { kunci: 'qty', label: 'Jumlah', rata: 'kanan', isi: (g) => `${fmt(g.qty)} ${g.uom}` },
              { kunci: 'rata', label: 'Rata-rata', rata: 'kanan', hp: false, isi: (g) => (g.average_rolls ? fmt(g.average_rolls, 0) : '—') },
              { kunci: 'nilai', label: 'Nilai', rata: 'kanan', hp: false, isi: (g) => `Rp ${fmt(g.value, 0)}` },
            ]} />
        </>
      )}
    </FormPopup>
  );
}
