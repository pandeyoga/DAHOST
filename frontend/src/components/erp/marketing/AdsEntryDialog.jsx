/**
 * AdsEntryDialog — form input/ubah BIAYA IKLAN per toko (F16).
 *
 * Kenapa layar ini baru ada sekarang: audit 2026-08-11 menemukan
 * `marketing_ads_routes.py` hanya punya endpoint GET, sehingga biaya iklan
 * **tidak pernah bisa dimasukkan lewat aplikasi**. Semua angka ROAS/CPA/CTR yang
 * dilihat manajemen berasal dari data demo yang tak bisa diperbarui.
 *
 * Dua aturan yang terlihat langsung di form ini:
 *   · TOKO wajib dipilih — belanja iklan tanpa toko tidak bisa dibandingkan
 *     dengan omzet toko mana pun.
 *   · CTR / CPC / CPA / ROAS / CVR TIDAK bisa diketik. Ditampilkan sebagai hasil
 *     hitungan hidup, dan yang tersimpan adalah hitungan SERVER — supaya tidak
 *     ada laporan yang mencampur angka ketikan dengan angka hitungan.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang + DatePicker (dulu Dialog + input tanggal bawaan).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { useToast } from '@/hooks/use-toast';
import axios from 'axios';
import { MarketingAccountSelect } from './pickers/MarketingPickers';
import { todayWIB } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;

const AD_PLATFORM_LABEL = {
  shopee_ads: 'Iklan Shopee', tiktok_ads: 'Iklan TikTok', meta_ads: 'Iklan Meta',
  google_ads: 'Iklan Google', affiliate: 'Afiliasi', lainnya: 'Lainnya',
};
const STATUS_LABEL = { active: 'Aktif', paused: 'Dijeda', ended: 'Selesai' };

const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;

const EMPTY = {
  account_id: '', date: '', campaign_name: '', campaign_id: '',
  ad_platform: 'shopee_ads', ad_type: '', spend: '', impressions: '',
  clicks: '', conversions: '', revenue: '', status: 'active', notes: '',
};

export default function AdsEntryDialog({ open, onClose, onSaved, token, entry }) {
  const { toast } = useToast();
  const authH = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  useEffect(() => {
    if (!open) return;
    setGalat('');
    if (entry) {
      setForm({
        ...EMPTY, ...entry,
        date: String(entry.date || '').slice(0, 10),
        spend: entry.spend ?? '', impressions: entry.impressions ?? '',
        clicks: entry.clicks ?? '', conversions: entry.conversions ?? '',
        revenue: entry.revenue ?? '',
      });
    } else {
      setForm({ ...EMPTY, date: todayWIB() });
    }
  }, [open, entry]);

  const set = (k) => (e) => setForm((f) => ({
    ...f, [k]: e?.target ? e.target.value : e,
  }));

  const n = (k) => Number(form[k] || 0);
  const derived = {
    ctr: n('impressions') ? (n('clicks') / n('impressions') * 100) : 0,
    cpc: n('clicks') ? (n('spend') / n('clicks')) : 0,
    cpa: n('conversions') ? (n('spend') / n('conversions')) : 0,
    roas: n('spend') ? (n('revenue') / n('spend')) : 0,
    cvr: n('clicks') ? (n('conversions') / n('clicks') * 100) : 0,
  };

  const submit = async () => {
    if (!form.account_id) { setGalat('Pilih toko dulu.'); return; }
    if (!form.date || !form.campaign_name) { setGalat('Tanggal dan nama kampanye wajib diisi.'); return; }
    setSaving(true);
    setGalat('');
    try {
      const payload = {
        ...form,
        spend: Number(form.spend || 0), impressions: Number(form.impressions || 0),
        clicks: Number(form.clicks || 0), conversions: Number(form.conversions || 0),
        revenue: Number(form.revenue || 0),
      };
      if (entry?.id) {
        delete payload.account_id;
        await axios.put(`${API}/api/marketing/ads/campaigns/${entry.id}`, payload, { headers: authH });
      } else {
        await axios.post(`${API}/api/marketing/ads/campaigns`, payload, { headers: authH });
      }
      toast({ title: entry?.id ? 'Data iklan disimpan' : 'Biaya iklan disimpan' });
      onSaved?.();
      onClose?.();
    } catch (e) {
      setGalat(e.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onClose?.()} ukuran="panjang" onSimpan={submit} menyimpan={saving} galat={galat}
      labelSimpan={entry?.id ? 'Simpan perubahan' : 'Simpan'} testId="ads-entry-form"
      judul={entry?.id ? 'Ubah biaya iklan' : 'Input biaya iklan'}
      keterangan="Toko wajib dipilih; CTR, CPC, CPA, ROAS, dan CVR dihitung otomatis.">
      <div className="grid gap-4 sm:grid-cols-2">
        {entry?.id ? (
          <Isian label="Toko / akun" petunjuk="Toko tidak bisa dipindah setelah tersimpan — buat baris baru bila salah toko.">
            <Input value={entry.account_name || '—'} disabled />
          </Isian>
        ) : (
          <MarketingAccountSelect token={token} value={form.account_id}
            onChange={(v) => setForm((f) => ({ ...f, account_id: v }))}
            testId="ads-account-select" />
        )}
        <Isian label="Tanggal" wajib>
          <DatePicker value={form.date} onChange={set('date')} bolehKosong={false} testId="ads-date" />
        </Isian>
        <Isian label="Nama kampanye" wajib htmlFor="ads-campaign">
          <Input id="ads-campaign" value={form.campaign_name} onChange={set('campaign_name')}
            placeholder="Flash sale gamis Agustus" data-testid="ads-campaign" />
        </Isian>
        <Isian label="Saluran iklan">
          <SmartNativeSelect className="w-full" value={form.ad_platform} onChange={set('ad_platform')} searchable={false}
            data-testid="ads-platform">
            {Object.entries(AD_PLATFORM_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {/* money=true → nominal Rupiah (MoneyInput, titik ribuan otomatis); sisanya hitungan. */}
        {[['spend', 'Biaya iklan (Rp)', true], ['revenue', 'Omzet dari iklan (Rp)', true],
          ['impressions', 'Tayangan'], ['clicks', 'Klik'], ['conversions', 'Konversi']].map(([k, l, money]) => (
            <Isian key={k} label={l}>
              {money ? (
                <MoneyInput value={form[k]} onChange={set(k)} className="tabular-nums" data-testid={`ads-${k}`} />
              ) : (
                <Input type="number" min="0" value={form[k]} onChange={set(k)} className="tabular-nums" data-testid={`ads-${k}`} />
              )}
            </Isian>
          ))}
        <Isian label="Status">
          <SmartNativeSelect className="w-full" value={form.status} onChange={set('status')} searchable={false} data-testid="ads-status">
            {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>

      <Isian label="Dihitung otomatis (tidak bisa diketik)">
        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5" data-testid="ads-derived">
          <div><dt className="text-xs text-muted-foreground">CTR</dt><dd className="font-medium tabular-nums">{derived.ctr.toFixed(2)}%</dd></div>
          <div><dt className="text-xs text-muted-foreground">CPC</dt><dd className="font-medium tabular-nums">{rp(derived.cpc.toFixed(0))}</dd></div>
          <div><dt className="text-xs text-muted-foreground">CPA</dt><dd className="font-medium tabular-nums">{rp(derived.cpa.toFixed(0))}</dd></div>
          <div><dt className="text-xs text-muted-foreground">ROAS</dt><dd className="font-medium tabular-nums">{derived.roas.toFixed(2)}×</dd></div>
          <div><dt className="text-xs text-muted-foreground">CVR</dt><dd className="font-medium tabular-nums">{derived.cvr.toFixed(2)}%</dd></div>
        </dl>
      </Isian>

      <Isian label="Catatan" htmlFor="ads-notes">
        <Textarea id="ads-notes" value={form.notes} onChange={set('notes')} rows={2}
          placeholder="Contoh: tes kreatif baru, target audiens…" data-testid="ads-notes" />
      </Isian>
    </FormPopup>
  );
}
