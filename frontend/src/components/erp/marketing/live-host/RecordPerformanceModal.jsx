import { useState } from 'react';
import { BarChart3, X, Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
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
    e.preventDefault();

    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/shifts/${shift.id}/performance`, {
        method: 'POST',
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });

      if (res.ok) {
        toast.success('Performance berhasil dicatat');
        onSuccess();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal mencatat performance');
      }
    } catch (e) {
      toast.error('Gagal mencatat performance');
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
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BarChart3 size={18} className="text-primary" />
            Record Shift Performance
          </DialogTitle>
          <p className="text-sm text-muted-foreground">
            {shift.host_name} - {shift.date} ({shift.shift_start_time}-{shift.shift_end_time})
          </p>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label className="text-xs font-semibold">Platform</Label>
            <div className="mt-1 h-9 flex items-center px-3 rounded-md border border-input bg-muted/30 text-sm" data-testid="select-platform">
              {shift.account_name ? `${shift.account_name} · ` : ''}{shift.platform || 'platform mengikuti toko'}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">Otomatis dari toko pada shift (bukan pilihan bebas).</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs font-semibold">Viewers</Label>
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
              <Label className="text-xs font-semibold">Peak Viewers</Label>
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
              <Label className="text-xs font-semibold">Revenue (Rp)</Label>
              <Input
                type="number"
                min="0"
                step="1000"
                value={form.revenue}
                onChange={(e) => setForm((f) => ({ ...f, revenue: Number(e.target.value) }))}
                className="mt-1 h-9"
                data-testid="input-revenue"
              />
            </div>
            <div>
              <Label className="text-xs font-semibold">Orders</Label>
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
            <Label className="text-xs font-semibold">Items Promoted</Label>
            <CatalogItemSelect accountId={shift.account_id} value="" label="" required={false}
              onChange={addItem} testId="input-item" className="mt-1" />
            {form.items_promoted.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {form.items_promoted.map((item, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">
                    {item}
                    <button
                      type="button"
                      onClick={() => removeItem(i)}
                      className="ml-1 hover:text-red-600"
                    >
                      <X size={10} />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
          </div>

          <div>
            <Label className="text-xs font-semibold">Script Adherence Score (0-100)</Label>
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
              placeholder="Optional"
              data-testid="input-script-score"
            />
          </div>

          <div>
            <Label className="text-xs font-semibold">Challenges Faced</Label>
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
            <Label className="text-xs font-semibold">Notes</Label>
            <Textarea
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className="mt-1 text-sm"
              rows={2}
              placeholder="Catatan tambahan..."
              data-testid="input-performance-notes"
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
              Batal
            </Button>
            <Button type="submit" disabled={saving} data-testid="submit-performance">
              {saving ? (
                <>
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                  Menyimpan...
                </>
              ) : (
                <>
                  <Save size={14} className="mr-1.5" />
                  Simpan
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
