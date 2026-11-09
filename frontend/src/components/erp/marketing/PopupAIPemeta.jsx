/**
 * Popup "Bantu petakan kolom dengan AI" — SATU-SATUNYA pintu AI pemeta kolom (9 Nov 2026).
 *
 * Dipakai layar "Impor banyak berkas" dan wizard Impor Data satu berkas. Backend:
 * `POST /api/marketing/impor-paket/sesi/{id}/ai-pemeta` (usulan untuk kolom yang BELUM terpetakan,
 * tidak mengubah apa pun) lalu `…/terapkan-pemetaan` (hanya usulan yang dicentang staf; kolom uang
 * diuji rumus lagi; pemetaan diingat per toko + jenis).
 *
 * `onSelesai(hasil)` menerima jawaban terapkan-pemetaan (mapping, mapping_report, preview, summary,
 * duplicates, value_report) supaya layar pemanggil bisa memperbarui pratinjaunya tanpa memuat ulang.
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Checkbox } from '@/components/ui/checkbox';
import FormPopup from '@/components/ui/form-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { EmptyState } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const DASAR = '/api/marketing/impor-paket';

async function kirim(path, body) {
  const token = localStorage.getItem('erp_token');
  const headers = { Authorization: `Bearer ${token}` };
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${API}${DASAR}${path}`, { method: 'POST', headers, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    let pesan = 'Permintaan gagal. Coba lagi.';
    try { const d = await res.json(); if (typeof d.detail === 'string') pesan = d.detail; } catch { /* abaikan */ }
    throw new Error(pesan);
  }
  return res.json();
}

export default function PopupAIPemeta({ sesiId, onClose, onSelesai }) {
  const [data, setData] = useState(null);
  const [galat, setGalat] = useState('');
  const [pilih, setPilih] = useState({});
  const [menyimpan, setMenyimpan] = useState(false);
  useEffect(() => {
    kirim(`/sesi/${sesiId}/ai-pemeta`)
      .then((d) => { setData(d); setPilih(Object.fromEntries((d.usulan || []).filter((u) => u.diterima).map((u) => [u.kolom, u.field]))); })
      .catch((e) => setGalat(e.message));
  }, [sesiId]);
  const terapkan = async () => {
    setMenyimpan(true); setGalat('');
    try {
      const hasil = await kirim(`/sesi/${sesiId}/terapkan-pemetaan`, { pilihan: pilih, simpan_untuk_toko: true });
      toast.success('Pemetaan diterapkan dan diingat untuk toko ini.');
      onSelesai(hasil);
    } catch (e) { setGalat(e.message); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul="Bantu petakan kolom dengan AI"
      keterangan="Hanya nama kolom dan bentuk isinya yang dikirim ke AI — bukan data pembeli. Kolom uang wajib lolos uji rumus."
      onSimpan={terapkan} labelSimpan="Terapkan yang dipilih" menyimpan={menyimpan} galat={galat}
      bisaSimpan={Object.keys(pilih).length > 0} testId="popup-ai-pemeta">
      {!data && !galat && <p className="text-sm text-muted-foreground">AI sedang membaca kolom yang belum terpetakan…</p>}
      {data && (
        <>
          <p className="text-sm text-muted-foreground">{data.pesan}</p>
          <Table>
            <TableHeader><TableRow><TableHead className="w-10" /><TableHead>Kolom berkas</TableHead>
              <TableHead>Usulan</TableHead><TableHead>Keterangan</TableHead></TableRow></TableHeader>
            <TableBody>
              {(data.usulan || []).length === 0 && (
                <TableRow><TableCell colSpan={4} className="p-0"><EmptyState title="Tidak ada kolom yang perlu dipetakan" /></TableCell></TableRow>
              )}
              {(data.usulan || []).map((u) => (
                <TableRow key={u.kolom} data-testid="ai-usulan-baris">
                  <TableCell>
                    <Checkbox checked={!!pilih[u.kolom]} disabled={!u.diterima} aria-label={`Pakai usulan untuk ${u.kolom}`}
                      onCheckedChange={(v) => setPilih((p) => { const n = { ...p }; if (v) n[u.kolom] = u.field; else delete n[u.kolom]; return n; })} />
                  </TableCell>
                  <TableCell className="font-medium">{u.kolom}</TableCell>
                  <TableCell>{u.field_label || '—'}{u.field && <span className="text-muted-foreground"> · yakin {Math.round((u.keyakinan || 0) * 100)}%</span>}</TableCell>
                  <TableCell className={u.diterima ? 'text-muted-foreground' : 'text-[hsl(var(--warning-text))]'}>{u.catatan || u.alasan}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </FormPopup>
  );
}
