/**
 * Rincian omzet TOTAL per kanal — bagian form Input Sales (11 Nov 2026, keputusan owner).
 *
 * Rincian adalah BAGIAN dari omzet, bukan tambahan; yang tidak dirinci otomatis "Lainnya".
 * Hari yang punya pesanan impor: kanal dari pesanan tetap, isian di sini hanya membagi omzet
 * pesanan tanpa kanal (mis. Shopee yang ekspornya tidak membawa kanal). Aturan yang sama
 * dihitung ulang di server (`core.marketing_sales_shape.merge_traffic`).
 */
import { Button } from '@/components/ui/button';
import { MoneyInput } from '@/components/ui/money-input';
import { Isian } from '@/components/ui/form-popup';
import { formatRupiah } from '@/lib/format';
import { KANAL_PESANAN, KANAL_RINCIAN } from '@/lib/kanalPenjualan';
import { Notice } from '../moduleAtoms';

const fmt = formatRupiah;

export default function RincianKanal({
  nilai, rincian, batas, kanalPesanan, status, onUbah, liveTercatat = 0, onPakaiLive,
}) {
  const dariPesanan = kanalPesanan
    ? KANAL_PESANAN.filter(([k]) => k !== 'other' && Number(kanalPesanan[k] || 0) > 0)
    : [];
  return (
    <section className="space-y-3 border-t border-[var(--glass-border)] pt-4" data-testid="sd-kanal">
      <div>
        <p className="text-sm font-semibold">Rincian per kanal (opsional)</p>
        <p className="text-xs text-muted-foreground">
          {kanalPesanan
            ? `Hari ini sudah punya pesanan impor. Kanal dari pesanan tetap dipakai; isian di bawah hanya membagi omzet pesanan tanpa kanal (${fmt(batas)}).`
            : 'Bagian dari omzet di atas, bukan tambahan. Yang tidak dirinci otomatis masuk Lainnya.'}
        </p>
        {kanalPesanan && (
          <p className="mt-1 text-xs text-muted-foreground" data-testid="sd-kanal-pesanan">
            Dari pesanan: {dariPesanan.length
              ? dariPesanan.map(([k, label]) => `${label} ${fmt(kanalPesanan[k])}`).join(' · ')
              : 'belum ada kanal (semua Lainnya)'}
          </p>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {KANAL_RINCIAN.map(([k, label]) => (
          <Isian key={k} label={label} htmlFor={`sd-kanal-${k}`}>
            <MoneyInput id={`sd-kanal-${k}`} value={nilai[k]} onChange={(e) => onUbah(k, e.target.value)}
              data-testid={`sd-kanal-${k}`} />
          </Isian>
        ))}
        <Isian label="Lainnya (sisa)">
          <p className="flex h-9 items-center text-sm tabular-nums" data-testid="sd-kanal-sisa">{fmt(rincian.sisa)}</p>
        </Isian>
      </div>
      {liveTercatat > 0 && !Number(nilai.live) && (
        <p className="text-xs text-muted-foreground" data-testid="sd-kanal-live-hint">
          Omzet jenis Live yang sudah diisi untuk tanggal ini: {fmt(liveTercatat)}.{' '}
          <Button type="button" variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onPakaiLive}
            data-testid="sd-kanal-pakai-live">Pakai untuk kanal Live</Button>
        </p>
      )}
      {rincian.lebih && (
        <p className="text-xs text-destructive" data-testid="sd-kanal-lebih">
          Jumlah rincian {fmt(rincian.jumlah)} lebih besar dari {kanalPesanan ? 'omzet pesanan tanpa kanal' : 'omzet'} {fmt(batas)}.
        </p>
      )}
      {status?.dipakai === false && (
        <Notice tone="warning" testId="sd-kanal-tidak-dipakai" title="Rincian yang tersimpan sedang tidak dipakai">
          <p>{status.alasan}</p>
        </Notice>
      )}
    </section>
  );
}
