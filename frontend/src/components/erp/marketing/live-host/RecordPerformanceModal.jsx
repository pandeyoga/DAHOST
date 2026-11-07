import { useState } from 'react';
import { BarChart3, X, Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Label } from '@/components/ui/label';
import FormPopup from '@/components/ui/form-popup';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { API } from './utils';
import { CatalogItemSelect } from '../pickers/MarketingPickers';

export default function RecordPerformanceModal({ shift, authH, onClose, onSuccess }) {
  const [form, setForm] = useState({
    shift_id: shift.id,
    platform: shift.platform || null,
    viewers: 0,
    peak_viewers: 0,
    revenue: 0,
    orders: 0,
    items_promoted: [],
    script_adherence_score: null,
    challenges_faced: '',
    notes: '',
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();

    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/shifts/${shift.id}/performance`, {
        method: 'POST',
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });

      if (res.ok) {
        toast.success('Performa dicatat.');
        onSuccess();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal mencatat performa');
      }
    } catch (e) {
      toast.error('Gagal mencatat performa');
    } finally {
      setSaving(false);
    }
  };

  const addItem = (item) => {
    if (!item) return;
    const label = item.sku ? `${item.sku} · ${item.name}` : item.name;
    setForm((f) => (f.items_promoted.includes(label) ? f : { ...f, items_promoted: [...f.items_promoted, label] }));
  };

  const removeItem = (index) => {
    setForm((f) => ({ ...f, items_promoted: f.items_promoted.filter((_, i) => i !== index) }));
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul="Catat performa shift" onSimpan={handleSubmit} menyimpan={saving}
      testId="livehost-recordperformance">
          <div>
            <Label className="text-sm font-medium">Platform</Label>
            <div className="mt-1 h-9 flex items-center px-3 rounded-md border border-input bg-muted/30 text-sm" data-testid="select-platform">
              {shift.account_name ? `${shift.account_name} · ` : ''}{shift.platform || 'platform mengikuti toko'}
            </div>
            <p className="text-xs text-muted-foreground mt-1">Otomatis dari toko pada shift (bukan pilihan bebas).</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Penonton</Label>
              <Input
                type="number"
                min="0"
                value={form.viewers}
                onChange={(e) => setForm((f) => ({ ...f, viewers: Number(e.target.value) }))}
                className="mt-1 h-9"
                data-testid="input-viewers"
              />
            </div>
            <div>
              <Label className="text-sm font-medium">Penonton puncak</Label>
              <Input
                type="number"
                min="0"
                value={form.peak_viewers}
                onChange={(e) => setForm((f) => ({ ...f, peak_viewers: Number(e.target.value) }))}
                className="mt-1 h-9"
                data-testid="input-peak-viewers"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Omzet (Rp)</Label>
              <MoneyInput
                value={form.revenue}
                onChange={(e) => setForm((f) => ({ ...f, revenue: Number(e.target.value) }))}
                className="mt-1 h-9"
                data-testid="input-revenue"
              />
            </div>
            <div>
              <Label className="text-sm font-medium">Pesanan</Label>
              <Input
                type="number"
                min="0"
                value={form.orders}
                onChange={(e) => setForm((f) => ({ ...f, orders: Number(e.target.value) }))}
                className="mt-1 h-9"
                data-testid="input-orders"
              />
            </div>
          </div>

          <div>
            <Label className="text-sm font-medium">Produk yang dipromosikan</Label>
            <CatalogItemSelect accountId={shift.account_id} value="" label="" required={false}
              onChange={addItem} testId="input-item" className="mt-1" />
            {form.items_promoted.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {form.items_promoted.map((item, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">
                    {item}
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeItem(i)}
                      className="ml-1 h-5 w-5 hover:text-[hsl(var(--danger-text))]" title="Hapus" aria-label="Hapus">
                      <X size={10} />
                    </Button>
                  </Badge>
                ))}
              </div>
            )}
          </div>

          <div>
            <Label className="text-sm font-medium">Skor kepatuhan naskah (0–100)</Label>
            <Input
              type="number"
              min="0"
              max="100"
              value={form.script_adherence_score || ''}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  script_adherence_score: e.target.value ? Number(e.target.value) : null,
                }))
              }
              className="mt-1 h-9"
              placeholder="Opsional"
              data-testid="input-script-score"
            />
          </div>

          <div>
            <Label className="text-sm font-medium">Kendala yang dihadapi</Label>
            <Textarea
              value={form.challenges_faced}
              onChange={(e) => setForm((f) => ({ ...f, challenges_faced: e.target.value }))}
              className="mt-1 text-sm"
              rows={2}
              placeholder="Kendala yang dihadapi saat live..."
              data-testid="input-challenges"
            />
          </div>

          <div>
            <Label className="text-sm font-medium">Catatan</Label>
            <Textarea
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className="mt-1 text-sm"
              rows={2}
              placeholder="Catatan tambahan..."
              data-testid="input-performance-notes"
            />
          </div>
    </FormPopup>
  );
}
