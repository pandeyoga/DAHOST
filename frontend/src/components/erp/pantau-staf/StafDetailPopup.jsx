/**
 * Rincian satu staf (popup, Standar UI v2): kewajiban terbuka, riwayat kewajiban, dan aktivitas per hari
 * (menu yang dibuka, berapa kali simpan/setujui) — "akun ini melakukan apa" vs "seharusnya melakukan apa".
 */
import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import DetailPopup from '@/components/ui/detail-popup';
import PanelTabs from '@/components/ui/panel-tabs';
import TabelData from '@/components/ui/tabel-data';
import { formatDateID } from '@/lib/format';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { NilaiBadge, StatusKewajiban, labelDokumen, lamaTerlambat, namaPeran, persen, qs, useApi, waktu } from './pantauStafShared';

const jam = (v) => (v ? new Date(v).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' }) : '—');

export default function StafDetailPopup({ uid, nama, periode, ujiCoba, onClose, onNavigate }) {
  const [tab, setTab] = useState('terbuka');
  const { data, loading, error } = useApi(`/pantau-staf/staf/${uid}${qs({ dari: periode.from, sampai: periode.to })}`);
  const s = data?.skor || {};
  const buka = (k) => { if (k.link_module) { onClose(); onNavigate?.(k.link_module, k.link_params || undefined); } };

  const kolomKewajiban = [
    { kunci: 'langkah', label: 'Langkah', hp: 'judul', isi: (k) => (
      <div className="min-w-0"><p className="font-medium">{k.nama}</p><p className="text-xs text-muted-foreground">{k.alur_label}</p></div>) },
    { kunci: 'dok', label: 'Dokumen', isi: (k) => (
      <div className="min-w-0"><p>{labelDokumen(k)}</p>{k.keterangan && <p className="truncate text-xs text-muted-foreground">{k.keterangan}</p>}</div>) },
    { kunci: 'sejak', label: 'Sejak', isi: (k) => <span className="text-sm md:whitespace-nowrap">{waktu(k.mulai)}{k.tanpa_waktu ? '*' : ''}</span> },
    { kunci: 'batas', label: 'Batas', isi: (k) => <span className="text-sm md:whitespace-nowrap">{waktu(k.tenggat)}</span> },
    { kunci: 'status', label: 'Status', isi: (k) => <StatusKewajiban k={k} /> },
    { kunci: 'lama', label: 'Terlambat', rata: 'kanan', isi: (k) => <span className="text-sm">{lamaTerlambat(k)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (k) => k.link_module && (
      <Button size="sm" variant="outline" onClick={() => buka(k)}><ExternalLink />Buka</Button>) },
  ];
  const kolomRiwayat = [
    kolomKewajiban[0], kolomKewajiban[1],
    { kunci: 'batas', label: 'Batas', isi: (k) => <span className="text-sm md:whitespace-nowrap">{waktu(k.tenggat)}</span> },
    { kunci: 'selesai', label: 'Selesai', isi: (k) => <span className="text-sm md:whitespace-nowrap">{k.selesai_at ? waktu(k.selesai_at) : '—'}</span> },
    { kunci: 'oleh', label: 'Dikerjakan oleh', isi: (k) => <span className="text-sm">{k.pelaku_nama || (k.status === 'selesai' ? 'tidak tercatat' : '—')}</span> },
    { kunci: 'status', label: 'Hasil', isi: (k) => <StatusKewajiban k={k} /> },
  ];
  const kolomAktivitas = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'judul', isi: (h) => formatDateID(h.tanggal) },
    { kunci: 'jam', label: 'Jam aktif', isi: (h) => <span className="tabular-nums">{jam(h.pertama)}–{jam(h.terakhir)}</span> },
    { kunci: 'menu', label: 'Menu yang dipakai', isi: (h) => (
      <span className="text-sm">{(h.modul || []).slice(0, 4).map((m) => m.label).join(', ') || '—'}
        {(h.modul || []).length > 4 ? ` +${h.modul.length - 4}` : ''}</span>) },
    { kunci: 'simpan', label: 'Simpan', rata: 'kanan', isi: (h) => <span className="tabular-nums">{(h.modul || []).reduce((a, m) => a + m.simpan, 0)}</span> },
    { kunci: 'setujui', label: 'Setujui', rata: 'kanan', isi: (h) => <span className="tabular-nums">{(h.modul || []).reduce((a, m) => a + m.setujui, 0)}</span> },
  ];

  return (
    <DetailPopup open onClose={onClose} judul={data?.user?.nama || nama} testId="pantau-staf-rincian"
      keterangan={data?.user ? `${namaPeran(data.user.peran)} · login terakhir ${waktu(data.user.login_terakhir)}` : undefined}
      status={data && <NilaiBadge nilai={s.nilai} ujiCoba={ujiCoba} />}>
      {error && <Notice tone="danger">{error}</Notice>}
      {loading && !data ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p> : data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Kepatuhan" value={persen(s.kepatuhan)} sub={`${s.tepat ?? 0} dari ${s.dinilai ?? 0} tepat waktu`} />
            <StatTile label="Terlambat sekarang" value={s.terlambat ?? 0} accent={s.terlambat > 0 ? 'danger' : 'default'} />
            <StatTile label="Dikerjakan orang lain" value={s.oleh_orang_lain ?? 0}
              hint="Langkah miliknya yang diinput akun lain (tidak dinilai untuknya)" />
            <StatTile label="Membantu orang lain" value={data.membantu_orang_lain ?? 0}
              hint="Langkah milik orang lain yang ia kerjakan di periode ini" />
          </div>
          <PanelTabs value={tab} onChange={setTab} testId="pantau-staf-rincian-tab" tabs={[
            { key: 'terbuka', label: 'Kewajiban terbuka', count: data.terbuka.length },
            { key: 'riwayat', label: 'Riwayat', count: data.riwayat.length },
            { key: 'aktivitas', label: 'Aktivitas per hari', count: data.aktivitas.length },
          ]} />
          {tab === 'terbuka' && (
            <TabelData kolom={kolomKewajiban} baris={data.terbuka} testId="rincian-terbuka"
              kosong={<EmptyState title="Tidak ada kewajiban yang menunggu" />} />
          )}
          {tab === 'riwayat' && (
            <TabelData kolom={kolomRiwayat} baris={data.riwayat} testId="rincian-riwayat"
              kosong={<EmptyState title="Belum ada kewajiban yang jatuh tempo di periode ini" />} />
          )}
          {tab === 'aktivitas' && (
            <TabelData kolom={kolomAktivitas} baris={data.aktivitas} kunci={(h) => h.tanggal} testId="rincian-aktivitas"
              kosong={<EmptyState title="Belum membuka sistem di periode ini"
                description="Aktivitas dicatat sejak fitur ini dipasang." />} />
          )}
          {tab === 'terbuka' && data.terbuka.some((k) => k.tanpa_waktu) && (
            <p className="text-xs text-muted-foreground">* Dokumen tidak menyimpan waktu masuk tahap ini; dipakai waktu pertama kali terlihat oleh sistem.</p>
          )}
        </>
      )}
    </DetailPopup>
  );
}
