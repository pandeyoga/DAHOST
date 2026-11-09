/**
 * CatalogTidyDialog — RAPIKAN ITEM TERSEMBUNYI (klarifikasi owner 9 Nov 2026 §D2).
 *
 * Item impor lama (12 Sep) tidak punya katalog, jadi tidak tampil di layar mana pun — padahal semuanya berharga dan
 * sebagian ber-URL. Popup ini PRATINJAU dulu (angka + contoh), lalu satu tombol menjalankan:
 *   kembar item tampil → harga, harga coret, URL disalin ke item tampil BILA kosong → item tampil ber-URL sah
 *   ditayangkan → kembaran DIARSIPKAN (tidak dihapus);
 *   tunggal → dipasangkan ke katalog toko yang sama (dibuatkan bila toko belum punya katalog).
 * Hasilnya tercatat di Riwayat aksi massal dan bisa dibatalkan. Hanya admin/owner/SPV/manager Marketing.
 */
import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import TabelData from '@/components/ui/tabel-data';
import FormPopup from '@/components/ui/form-popup';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { alatUrl, panggil } from './catalogToolsApi';

const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const SALIN = { harga_jual: 'harga jual', harga_coret: 'harga coret', platform_url: 'URL' };

export default function CatalogTidyDialog({ open, token, onClose, onDone }) {
  const [pv, setPv] = useState(null);
  const [memuat, setMemuat] = useState(false);
  const [sibuk, setSibuk] = useState(false);
  const [galat, setGalat] = useState('');

  useEffect(() => {
    if (!open) return;
    let batal = false;
    setPv(null); setGalat(''); setMemuat(true);
    panggil(token, alatUrl('/hidden/preview'), { method: 'GET' })
      .then((b) => { if (!batal) setPv(b); })
      .catch((e) => { if (!batal) setGalat(e.message); })
      .finally(() => { if (!batal) setMemuat(false); });
    return () => { batal = true; };
  }, [open, token]);

  const s = pv?.summary || {};
  const ada = (s.twins || 0) + (s.singles || 0) > 0;

  const jalankan = async () => {
    setSibuk(true); setGalat('');
    try {
      const b = await panggil(token, alatUrl('/hidden/apply'),
        { body: { expect_twins: s.twins || 0, expect_singles: s.singles || 0 } });
      onDone?.(b);
    } catch (e) { setGalat(e.message); } finally { setSibuk(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" onSimpan={jalankan} menyimpan={sibuk} galat={galat}
      bisaSimpan={!memuat && ada} labelSimpan={ada ? `Rapikan ${angka((s.twins || 0) + (s.singles || 0))} item` : 'Rapikan'}
      judul="Rapikan item tersembunyi" testId="catalog-tidy-dialog"
      keterangan="Item impor lama tanpa katalog tidak tampil di layar mana pun. Periksa angkanya dulu — semuanya bisa dibatalkan.">
      {memuat && <p className="text-sm text-muted-foreground">Menghitung…</p>}
      {pv && !ada && (
        <EmptyState icon={Sparkles} title="Tidak ada item tersembunyi" testId="catalog-tidy-empty"
          description="Semua item katalog sudah berada di katalog tokonya." />
      )}
      {pv && ada && (
        <>
          <Notice tone="info" icon={Sparkles} title={pv.message} testId="catalog-tidy-summary">
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              <li><b>{angka(s.twins)}</b> kembar item tampil: {angka(s.twins_copy_price)} harga jual, {angka(s.twins_copy_coret)} harga coret,
                {' '}{angka(s.twins_copy_url)} URL disalin (hanya ke item tampil yang masih kosong); {angka(s.twins_publish)} item tampil
                {' '}ditayangkan karena URL-nya sah; kembaran diarsipkan, tidak dihapus.</li>
              <li><b>{angka(s.singles)}</b> item tunggal dipasangkan ke katalog tokonya ({angka(s.singles_publish)} langsung tayang karena ber-URL
                {s.new_catalogs ? `, ${angka(s.new_catalogs)} katalog baru dibuat` : ''}).</li>
              {s.twins_conflict > 0 && <li>{angka(s.twins_conflict)} kembar berbeda harga/URL dengan item tampil — item tampil yang dipakai.</li>}
              {s.skipped > 0 && <li>{angka(s.skipped)} item dilewati (alasan di bawah).</li>}
            </ul>
          </Notice>
          <section className="space-y-2">
            <p className="text-sm font-medium">Contoh kembar</p>
            <TabelData baris={pv.twins_sample || []} kunci={(r) => `${r.toko}-${r.sku}`} testId="catalog-tidy-twins"
              kolom={[
                { kunci: 'sku', label: 'Produk', hp: 'judul', isi: (r) => (
                  <div className="min-w-0"><p className="truncate font-medium">{r.name}</p><p className="text-xs text-muted-foreground">{r.sku} · {r.toko}</p></div>) },
                { kunci: 'salin', label: 'Disalin', isi: (r) => (r.salin.length ? r.salin.map((k) => SALIN[k] || k).join(', ') : '—') },
                { kunci: 'tayang', label: 'Tayang', isi: (r) => (r.tayang ? <StatusBadge status="ya" label="Ya" tone="success" /> : '—') },
                { kunci: 'catatan', label: 'Catatan', isi: (r) => <span className="text-xs text-muted-foreground">{r.catatan || '—'}</span> },
              ]}
              kosong={<EmptyState title="Tidak ada kembar" description="Tidak ada item tersembunyi yang punya kembaran tampil." />} />
          </section>
          <section className="space-y-2">
            <p className="text-sm font-medium">Contoh tunggal</p>
            <TabelData baris={pv.singles_sample || []} kunci={(r) => `${r.toko}-${r.sku}`} testId="catalog-tidy-singles"
              kolom={[
                { kunci: 'sku', label: 'Produk', hp: 'judul', isi: (r) => (
                  <div className="min-w-0"><p className="truncate font-medium">{r.name}</p><p className="text-xs text-muted-foreground">{r.sku} · {r.toko}</p></div>) },
                { kunci: 'katalog', label: 'Masuk ke katalog', isi: (r) => (
                  <span>{r.katalog}{r.katalog_baru && <> <StatusBadge status="baru" label="Baru" tone="info" /></>}</span>) },
                { kunci: 'tayang', label: 'Tayang', isi: (r) => (r.tayang ? <StatusBadge status="ya" label="Ya" tone="success" /> : 'Draf') },
              ]}
              kosong={<EmptyState title="Tidak ada item tunggal" description="Semua item tersembunyi punya kembaran tampil." />} />
          </section>
          {(pv.skipped || []).length > 0 && (
            <section className="space-y-1" data-testid="catalog-tidy-skipped">
              <p className="text-sm font-medium">Dilewati</p>
              <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">
                {pv.skipped.map((r) => <li key={r.hidden_id}>{r.sku} · {r.account_label}: {r.why}</li>)}
              </ul>
            </section>
          )}
        </>
      )}
    </FormPopup>
  );
}
