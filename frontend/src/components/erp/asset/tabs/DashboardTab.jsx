/**
 * DashboardTab — ringkasan Manajemen Aset.
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • 4 kartu angka StatTile netral dengan keterangan cara menghitung (dulu kartu gradasi berwarna + ikon);
 *    semua 0 → tampilan kosong (bukan deretan "Rp 0").
 *  • Diagram lingkaran "Distribusi per kategori" → tabel kategori · jumlah · porsi (angka terbaca, bisa diunduh).
 *  • Garansi/asuransi: satu Notice + satu tabel (dulu kotak kuning ber-emoji + 4 daftar terpotong 5 baris).
 *  • "Aset terbaru": tabel, klik baris membuka detail popup.
 * Data dari orkestrator (tanpa ambil data sendiri).
 */
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, Notice, StatusBadge as Lencana } from '../../moduleAtoms';
import { STATUS_CONFIG } from '../constants';
import { angka, fmtCurrency, fmtDate, fmtPersen } from '../utils';
import { KPICard, BarisKartu, Bagian } from '../components/KPICard';
import { StatusBadge } from '../components/StatusBadge';
import { AksiAset } from './AssetsTab';

const JENIS_HABIS = [
  { key: 'warranty_expiring',  jenis: 'Garansi',  keadaan: 'Habis ≤ 30 hari', tone: 'warning', tgl: 'warranty_expiry_date' },
  { key: 'warranty_expired',   jenis: 'Garansi',  keadaan: 'Sudah habis',     tone: 'danger',  tgl: 'warranty_expiry_date' },
  { key: 'insurance_expiring', jenis: 'Asuransi', keadaan: 'Habis ≤ 30 hari', tone: 'warning', tgl: 'insurance_expiry_date' },
  { key: 'insurance_expired',  jenis: 'Asuransi', keadaan: 'Sudah habis',     tone: 'danger',  tgl: 'insurance_expiry_date' },
];

export function DashboardTab({
  dashData, expiringAlerts, memuat, onAssetClick, onMuatUlang,
  onTambahAset, onScan, onImpor, onBuatPR, onDepresiasiMassal,
}) {
  const s = dashData?.summary || null;
  const totalAset = s?.total_assets || 0;
  const recent = dashData?.recent_assets || [];
  const byCat = (dashData?.by_category || []).map((c) => ({ id: c.category || '—', nama: c.category || 'Tanpa kategori', jumlah: c.count || 0 }));
  const totalKategori = byCat.reduce((n, c) => n + c.jumlah, 0);
  const adaAngka = s && (totalAset > 0 || (s.total_purchase_cost || 0) > 0 || (s.depreciation_this_month || 0) > 0);

  // Garansi & asuransi (≤ 30 hari & sudah habis) → satu tabel.
  const habis = JENIS_HABIS.flatMap((j) => (expiringAlerts?.[j.key] || []).map((a) => ({
    ...a, _kunci: `${j.key}-${a.id}`, _jenis: j.jenis, _keadaan: j.keadaan, _tone: j.tone, _tgl: a[j.tgl],
  })));
  const segeraGaransi = s?.warranty_expiring_soon || 0;
  const segeraAsuransi = s?.insurance_expiring_soon || 0;

  const muatUlang = (
    <Button variant="outline" size="icon" onClick={onMuatUlang} disabled={memuat} title="Muat ulang" aria-label="Muat ulang">
      <RefreshCw className={memuat ? 'animate-spin' : ''} />
    </Button>
  );
  const aksi = (
    <AksiAset onTambahAset={onTambahAset} onScan={onScan} onImpor={onImpor} onBuatPR={onBuatPR}
      onDepresiasiMassal={onDepresiasiMassal} />
  );

  return (
    <PageLayout testId="asset-dashboard" title="Dashboard" subtitle="Ringkasan nilai, kategori, dan garansi aset."
      actions={aksi} tools={muatUlang}
      summary={adaAngka ? (
        <BarisKartu testId="asset-dashboard-kpi">
          <KPICard label="Aset terdaftar" value={totalAset.toLocaleString('id-ID')} testId="asset-kpi-total"
            sub={`${s.active || 0} aktif · ${s.in_maintenance || 0} pemeliharaan`}
            hint="Semua aset kecuali yang sudah dilepas." />
          <KPICard label="Harga perolehan" value={fmtCurrency(s.total_purchase_cost)} testId="asset-kpi-cost"
            sub={`${s.linked_to_finance || 0} aset tertaut ke Keuangan`}
            hint="Jumlah harga beli aset yang belum dilepas. Aset yang tertaut memakai angka registri Keuangan › Aset Tetap." />
          <KPICard label="Nilai buku" value={fmtCurrency(s.total_nbv)} testId="asset-kpi-nbv"
            sub="Harga perolehan − akumulasi penyusutan"
            hint="Harga perolehan dikurangi akumulasi penyusutan, aset yang belum dilepas." />
          <KPICard label="Penyusutan bulan ini" value={fmtCurrency(s.depreciation_this_month)} testId="asset-kpi-depr"
            sub={s.not_linked_to_finance ? `${s.not_linked_to_finance} aset belum tertaut, tidak dihitung` : 'Yang sudah diposting di Keuangan'}
            hint="Penyusutan bulan berjalan yang sudah diposting di Keuangan › Aset Tetap, hanya aset yang tertaut." />
        </BarisKartu>
      ) : null}>
      {!dashData ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat ringkasan aset…</p>
      ) : dashData.gagal ? (
        <Notice tone="danger" title="Ringkasan aset gagal dimuat">Coba muat ulang beberapa saat lagi.</Notice>
      ) : totalAset === 0 && recent.length === 0 ? (
        <EmptyState title="Belum ada aset terdaftar" testId="asset-dashboard-empty"
          description="Daftarkan aset pertama, atau impor daftar aset dari berkas CSV/Excel. Ringkasan nilai dan kategori tampil di sini." />
      ) : (
        <>
          {(segeraGaransi > 0 || segeraAsuransi > 0) && (
            <Notice tone="warning" title="Garansi atau asuransi segera habis" testId="expiring-alerts-banner">
              {[segeraGaransi > 0 && `garansi ${segeraGaransi} aset`, segeraAsuransi > 0 && `asuransi ${segeraAsuransi} aset`]
                .filter(Boolean).join(' dan ')} habis dalam 30 hari ke depan.
            </Notice>
          )}

          {habis.length > 0 && (
            <Bagian judul={`Garansi & asuransi perlu perhatian (${habis.length})`} testId="expiring-alerts-card"
              keterangan="Yang habis dalam 30 hari dan yang sudah habis. Klik baris untuk membuka asetnya."
              alat={<TombolUnduh namaBerkas="aset-garansi-asuransi" namaLembar="Garansi asuransi" baris={habis}
                testId="asset-expiring-unduh" kolom={[
                  { label: 'Aset', nilai: (a) => a.name },
                  { label: 'No. aset', nilai: (a) => a.asset_number },
                  { label: 'Jenis', nilai: (a) => a._jenis },
                  { label: 'Keadaan', nilai: (a) => a._keadaan },
                  { label: 'Berakhir', nilai: (a) => fmtDate(a._tgl) },
                ]} />}>
              <TabelData baris={habis} kunci={(a) => a._kunci} onKlikBaris={onAssetClick} testId="asset-expiring-table"
                kolom={[
                  { kunci: 'nama', label: 'Aset', hp: 'judul', isi: (a) => <span className="font-medium">{a.name}</span> },
                  { kunci: 'no', label: 'No. aset', hp: 'keterangan', isi: (a) => <span className="tabular-nums">{a.asset_number}</span> },
                  { kunci: 'jenis', label: 'Jenis', isi: (a) => a._jenis },
                  { kunci: 'keadaan', label: 'Keadaan', isi: (a) => <Lencana status={a._tone} label={a._keadaan} tone={a._tone} /> },
                  { kunci: 'tgl', label: 'Berakhir', isi: (a) => fmtDate(a._tgl) },
                ]} />
            </Bagian>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Bagian judul="Aset per kategori" testId="asset-by-category"
              keterangan="Aset yang belum dilepas, dikelompokkan menurut kategori."
              alat={<TombolUnduh namaBerkas="aset-per-kategori" namaLembar="Per kategori" baris={byCat} testId="asset-by-category-unduh"
                kolom={[
                  { label: 'Kategori', nilai: (c) => c.nama },
                  { label: 'Jumlah aset', nilai: (c) => c.jumlah },
                  { label: 'Porsi (%)', nilai: (c) => (totalKategori ? Math.round((c.jumlah / totalKategori) * 1000) / 10 : 0) },
                ]} />}>
              <TabelData baris={byCat} kunci={(c) => c.id} testId="asset-by-category-table"
                kosong={<p className="py-6 text-center text-sm text-muted-foreground">Belum ada aset aktif.</p>}
                kolom={[
                  { kunci: 'nama', label: 'Kategori', hp: 'judul' },
                  { kunci: 'jumlah', label: 'Jumlah aset', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.jumlah.toLocaleString('id-ID')}</span> },
                  { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (c) => <span className="tabular-nums">{totalKategori ? fmtPersen((c.jumlah / totalKategori) * 100) : '—'}</span> },
                ]} />
            </Bagian>

            <Bagian judul="Aset terbaru" testId="asset-recent"
              keterangan="Lima aset yang terakhir didaftarkan. Klik baris untuk detail."
              alat={<TombolUnduh namaBerkas="aset-terbaru" namaLembar="Aset terbaru" baris={recent} testId="asset-recent-unduh"
                kolom={[
                  { label: 'No. aset', nilai: (a) => a.asset_number },
                  { label: 'Nama', nilai: (a) => a.name },
                  { label: 'Kategori', nilai: (a) => a.category_name || '' },
                  { label: 'Harga beli', nilai: (a) => angka(a.purchase_cost) },
                  { label: 'Status', nilai: (a) => STATUS_CONFIG[a.status]?.label || a.status },
                ]} />}>
              <TabelData baris={recent} onKlikBaris={onAssetClick} testId="asset-recent-table"
                kosong={<p className="py-6 text-center text-sm text-muted-foreground">Belum ada aset terdaftar.</p>}
                kolom={[
                  { kunci: 'nama', label: 'Aset', hp: 'judul', isi: (a) => <span className="font-medium">{a.name}</span> },
                  { kunci: 'ket', label: 'Kategori · no. aset', hp: 'keterangan', isi: (a) => (
                    <span className="text-muted-foreground">{[a.category_name, a.asset_number].filter(Boolean).join(' · ') || '—'}</span>) },
                  { kunci: 'harga', label: 'Harga beli', rata: 'kanan', isi: (a) => <span className="tabular-nums">{fmtCurrency(a.purchase_cost)}</span> },
                  { kunci: 'status', label: 'Status', isi: (a) => <StatusBadge status={a.status} configMap={STATUS_CONFIG} /> },
                ]} />
            </Bagian>
          </div>
        </>
      )}
    </PageLayout>
  );
}
