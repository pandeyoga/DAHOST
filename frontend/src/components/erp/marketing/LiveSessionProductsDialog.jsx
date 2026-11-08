/**
 * LiveSessionProductsDialog — isi/ubah rincian produk untuk SATU sesi live yang
 * sudah tersimpan (dipanggil dari tombol “Rincian” pada tabel Live Sessions).
 *
 * Terpisah dari dialog sesi supaya alur nyatanya terlayani: sesi biasanya dicatat
 * segera sesudah live (angka total dari dasbor platform), sedangkan rincian per
 * produk baru dimasukkan belakangan saat laporan produk keluar.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang (dulu Dialog buatan sendiri); "Samakan total sesi" di kaki
 * kiri; tombol Simpan kini ber-testid lp-form-simpan (dulu lp-save). Simpan tidak menutup popup (sama seperti dulu).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, Scale } from 'lucide-react';
import { Button } from '@/components/ui/button';
import FormPopup from '@/components/ui/form-popup';
import { formatDateID } from '@/lib/format';
import { useToast } from '@/hooks/use-toast';
import axios from 'axios';
import LiveSessionProductsEditor from './LiveSessionProductsEditor';

const API = process.env.REACT_APP_BACKEND_URL;
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
// Waktu dari server tanpa zona = UTC → tambah 'Z' supaya dibaca benar dalam WIB.
const tgl = (v) => (v ? formatDateID(/T\d\d:\d\d(:\d\d(\.\d+)?)?$/.test(String(v)) ? `${v}Z` : v) : '—');

export default function LiveSessionProductsDialog({
  open, onClose, onSaved, token, session,
}) {
  const { toast } = useToast();
  const authH = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const [lines, setLines] = useState([]);
  const [recon, setRecon] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sessionRevenue, setSessionRevenue] = useState(0);

  const load = useCallback(async () => {
    if (!session?.id) return;
    setLoading(true);
    try {
      const r = await axios.get(
        `${API}/api/marketing/live/sessions/${session.id}/products`, { headers: authH });
      const d = r.data?.data || {};
      setLines(d.products || []);
      setRecon(d.reconciliation || null);
      setSessionRevenue(d.reconciliation?.session_revenue ?? session.revenue ?? 0);
    } catch (e) {
      toast({
        title: 'Gagal memuat rincian produk',
        description: e.response?.data?.detail || e.message, variant: 'destructive',
      });
    } finally { setLoading(false); }
  }, [session, authH, toast]);

  useEffect(() => { if (open) load(); }, [open, load]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        products: (lines || [])
          .filter((l) => l.catalog_item_id)
          .map((l) => ({
            catalog_item_id: l.catalog_item_id,
            units_sold: Number(l.units_sold || 0),
            revenue: Number(l.revenue || 0),
            orders: Number(l.orders || 0),
            notes: l.notes || '',
          })),
      };
      const r = await axios.put(
        `${API}/api/marketing/live/sessions/${session.id}/products`, payload,
        { headers: authH });
      setRecon(r.data?.data?.reconciliation || null);
      setLines(r.data?.data?.products || []);
      toast({ title: 'Rincian produk disimpan' });
      onSaved?.();
    } catch (e) {
      toast({
        title: 'Gagal menyimpan rincian',
        description: e.response?.data?.detail || e.message, variant: 'destructive',
      });
    } finally { setSaving(false); }
  };

  const syncTotals = async () => {
    setSaving(true);
    try {
      const r = await axios.post(
        `${API}/api/marketing/live/sessions/${session.id}/products/sync-session-totals`,
        {}, { headers: authH });
      const d = r.data?.data || {};
      setSessionRevenue(d.after?.revenue ?? sessionRevenue);
      setRecon(d.reconciliation || null);
      toast({
        title: 'Total sesi disamakan dengan rincian',
        description: `${rp(d.before?.revenue)} → ${rp(d.after?.revenue)}`,
      });
      onSaved?.();
    } catch (e) {
      toast({
        title: 'Gagal menyamakan total sesi',
        description: e.response?.data?.detail || e.message, variant: 'destructive',
      });
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="lp-form"
      judul={`Rincian produk — ${session?.title || 'sesi live'}`}
      keterangan={`${session?.account_name || '—'} · ${tgl(session?.session_date)} · omzet sesi ${rp(sessionRevenue)}`}
      onSimpan={save} labelSimpan="Simpan rincian" menyimpan={saving}
      aksiKiri={
        <Button type="button" variant="outline" onClick={syncTotals} disabled={saving || !lines.length}
          data-testid="lp-sync-totals" title="Tulis total rincian ke omzet/pesanan sesi">
          <Scale /> Samakan total sesi
        </Button>
      }>
      {loading ? (
        <div className="flex h-40 items-center justify-center text-muted-foreground">
          <Loader2 className="animate-spin" />
        </div>
      ) : (
        <LiveSessionProductsEditor
          token={token} accountId={session?.account_id} lines={lines}
          onChange={setLines} sessionRevenue={sessionRevenue} disabled={saving}
        />
      )}

      {recon?.message && (
        <p className="text-sm text-muted-foreground" data-testid="lp-server-message">
          {recon.message}
        </p>
      )}
    </FormPopup>
  );
}
