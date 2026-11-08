import { useState } from 'react';
import { Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import SmartNativeSelect from '@/components/ui/smart-native-select';
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
              <SmartNativeSelect className="mt-1" value={form.category} onChange={(e) => { const _v = e.target.value; setForm((f) => ({ ...f, category: _v })); }} searchable={false}>
                  <option value="opening">Pembuka</option>
                  <option value="demo">Demo produk</option>
                  <option value="promo">Promo</option>
                  <option value="closing">Penutup</option>
                  <option value="faq">Tanya jawab</option>
                  <option value="objection_handling">Menangani keberatan</option>
                </SmartNativeSelect>
            </div>
            <div>
              <Label className="text-sm font-medium">Bahasa</Label>
              <SmartNativeSelect className="mt-1" value={form.language} onChange={(e) => { const _v = e.target.value; setForm((f) => ({ ...f, language: _v })); }} searchable={false}>
                  <option value="indonesia">Indonesia</option>
                  <option value="english">Inggris</option>
                  <option value="mandarin">Mandarin</option>
                </SmartNativeSelect>
            </div>
          </div>

          <div>
            <Label className="text-sm font-medium">Akun toko (opsional)</Label>
            <SmartNativeSelect className="mt-1" value={form.account_id || 'global'} onChange={(e) => { const _v = e.target.value; setForm((f) => ({ ...f, account_id: _v === 'global' ? '' : _v })); }}>
                <option value="global">Semua akun toko</option>
                {accounts.map((acc) => (
                  <option key={acc.id} value={acc.id}>
                    {acc.account_name} · {({ shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', instagram: 'Instagram' })[acc.platform] || acc.platform}
                  </option>
                ))}
              </SmartNativeSelect>
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
