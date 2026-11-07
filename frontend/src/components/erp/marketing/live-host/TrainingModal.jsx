import { useState } from 'react';
import { Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import FormPopup from '@/components/ui/form-popup';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { API } from './utils';

export default function TrainingModal({ training, authH, onClose, onSuccess }) {
  const isEdit = !!training;
  const [form, setForm] = useState({
    title: training?.title || '',
    category: training?.category || 'product_knowledge',
    description: training?.description || '',
    content_type: training?.content_type || 'video',
    duration_minutes: training?.duration_minutes || 0,
    is_required: training?.is_required ?? true,
    expiry_months: training?.expiry_months || null,
    passing_score: training?.passing_score || null,
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (!form.title || !form.description) {
      toast.error('Judul dan deskripsi wajib diisi');
      return;
    }

    setSaving(true);
    try {
      const url = isEdit
        ? `${API}/api/marketing/livehost/training/${training.id}`
        : `${API}/api/marketing/livehost/training`;
      const method = isEdit ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });

      if (res.ok) {
        toast.success(isEdit ? 'Pelatihan disimpan.' : 'Pelatihan dibuat.');
        onSuccess();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal menyimpan pelatihan');
      }
    } catch (e) {
      toast.error('Gagal menyimpan pelatihan');
    } finally {
      setSaving(false);
    }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul={isEdit ? 'Ubah pelatihan' : 'Tambah pelatihan'} onSimpan={handleSubmit} menyimpan={saving}
      testId="livehost-training">
          <div>
            <Label className="text-sm font-medium">Judul *</Label>
            <Input
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              className="mt-1 h-9"
              placeholder="e.g., Pengetahuan produk 101"
            />
          </div>

          <div>
            <Label className="text-sm font-medium">Kategori</Label>
            <Select value={form.category} onValueChange={(v) => setForm((f) => ({ ...f, category: v }))}>
              <SelectTrigger className="mt-1 h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="product_knowledge">Pengetahuan produk</SelectItem>
                <SelectItem value="platform_rules">Aturan platform</SelectItem>
                <SelectItem value="engagement">Teknik interaksi</SelectItem>
                <SelectItem value="sales_techniques">Teknik penjualan</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="text-sm font-medium">Deskripsi *</Label>
            <Textarea
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="mt-1 text-sm"
              rows={3}
              placeholder="Deskripsi training..."
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Jenis materi</Label>
              <Select value={form.content_type} onValueChange={(v) => setForm((f) => ({ ...f, content_type: v }))}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="video">Video</SelectItem>
                  <SelectItem value="pdf">PDF</SelectItem>
                  <SelectItem value="quiz">Kuis</SelectItem>
                  <SelectItem value="external_link">Tautan luar</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-sm font-medium">Durasi (menit)</Label>
              <Input
                type="number"
                min="0"
                value={form.duration_minutes}
                onChange={(e) => setForm((f) => ({ ...f, duration_minutes: Number(e.target.value) }))}
                className="mt-1 h-9"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Nilai lulus (%) — opsional</Label>
              <Input
                type="number"
                min="0"
                max="100"
                value={form.passing_score || ''}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    passing_score: e.target.value ? Number(e.target.value) : null,
                  }))
                }
                className="mt-1 h-9"
                placeholder="Khusus kuis"
              />
            </div>
            <div>
              <Label className="text-sm font-medium">Masa berlaku (bulan) — opsional</Label>
              <Input
                type="number"
                min="0"
                value={form.expiry_months || ''}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    expiry_months: e.target.value ? Number(e.target.value) : null,
                  }))
                }
                className="mt-1 h-9"
                placeholder="Sertifikasi ulang"
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={form.is_required}
              onChange={(e) => setForm((f) => ({ ...f, is_required: e.target.checked }))}
              className="rounded"
            />
            <Label className="text-xs font-medium cursor-pointer">Pelatihan wajib</Label>
          </div>
    </FormPopup>
  );
}
