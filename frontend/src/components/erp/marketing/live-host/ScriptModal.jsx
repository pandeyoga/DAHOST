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

export default function ScriptModal({ script, accounts, authH, onClose, onSuccess }) {
  const isEdit = !!script;
  const [form, setForm] = useState({
    title: script?.title || '',
    category: script?.category || 'opening',
    account_id: script?.account_id || '',
    script_text: script?.script_text || '',
    language: script?.language || 'indonesia',
    products_applicable: script?.products_applicable || [],
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (!form.title || !form.script_text) {
      toast.error('Judul dan isi naskah wajib diisi');
      return;
    }

    setSaving(true);
    try {
      const url = isEdit
        ? `${API}/api/marketing/livehost/scripts/${script.id}`
        : `${API}/api/marketing/livehost/scripts`;
      const method = isEdit ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, account_id: form.account_id || null }),
      });

      if (res.ok) {
        toast.success(isEdit ? 'Naskah disimpan.' : 'Naskah dibuat.');
        onSuccess();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal menyimpan naskah');
      }
    } catch (e) {
      toast.error('Gagal menyimpan naskah');
    } finally {
      setSaving(false);
    }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul={isEdit ? 'Ubah naskah live' : 'Tambah naskah live'} onSimpan={handleSubmit} menyimpan={saving}
      testId="livehost-script">
          <div>
            <Label className="text-sm font-medium">Judul *</Label>
            <Input
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              className="mt-1 h-9"
              placeholder="cth: Naskah pembuka live fashion"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Kategori</Label>
              <Select value={form.category} onValueChange={(v) => setForm((f) => ({ ...f, category: v }))}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="opening">Pembuka</SelectItem>
                  <SelectItem value="demo">Demo produk</SelectItem>
                  <SelectItem value="promo">Promo</SelectItem>
                  <SelectItem value="closing">Penutup</SelectItem>
                  <SelectItem value="faq">Tanya jawab</SelectItem>
                  <SelectItem value="objection_handling">Menangani keberatan</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-sm font-medium">Bahasa</Label>
              <Select value={form.language} onValueChange={(v) => setForm((f) => ({ ...f, language: v }))}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="indonesia">Indonesia</SelectItem>
                  <SelectItem value="english">Inggris</SelectItem>
                  <SelectItem value="mandarin">Mandarin</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <Label className="text-sm font-medium">Akun toko (opsional)</Label>
            <Select
              value={form.account_id || 'global'}
              onValueChange={(v) => setForm((f) => ({ ...f, account_id: v === 'global' ? '' : v }))}
            >
              <SelectTrigger className="mt-1 h-9">
                <SelectValue placeholder="Semua akun toko" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="global">Semua akun toko</SelectItem>
                {accounts.map((acc) => (
                  <SelectItem key={acc.id} value={acc.id}>
                    {acc.account_name} ({acc.platform})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="text-sm font-medium">Isi naskah *</Label>
            <Textarea
              value={form.script_text}
              onChange={(e) => setForm((f) => ({ ...f, script_text: e.target.value }))}
              className="mt-1 text-sm"
              rows={6}
              placeholder="Tulis script lengkap di sini..."
            />
          </div>
    </FormPopup>
  );
}
