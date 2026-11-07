import { useState } from 'react';
import { User, Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import FormPopup from '@/components/ui/form-popup';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { API } from './utils';

export default function AddEditHostModal({ host, accounts, authH, onClose, onSuccess }) {
  const isEdit = !!host;
  const [form, setForm] = useState({
    name: host?.name || '',
    email: host?.email || '',
    password: '',
    phone: host?.phone || '',
    employment_type: host?.employment_type || 'part_time',
    hourly_rate: host?.hourly_rate || 0,
    shift_preferences: host?.shift_preferences || [],
    language_skills: host?.language_skills || [],
    product_expertise: host?.product_expertise || [],
    assigned_account_ids: host?.assigned_account_ids || [],
    status: host?.status || 'active',
    notes: host?.notes || '',
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (!form.name || !form.email) {
      toast.error('Nama dan email wajib diisi');
      return;
    }
    if (!isEdit && !form.password) {
      toast.error('Sandi wajib diisi untuk LiveHost baru');
      return;
    }

    setSaving(true);
    try {
      const payload = { ...form };
      if (isEdit && !form.password) {
        delete payload.password;
      }

      const url = isEdit ? `${API}/api/marketing/livehost/${host.id}` : `${API}/api/marketing/livehost`;
      const method = isEdit ? 'PATCH' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        toast.success(isEdit ? 'Host live disimpan.' : 'Host live ditambahkan.');
        onSuccess();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal menyimpan host live');
      }
    } catch (e) {
      toast.error('Gagal menyimpan host live');
    } finally {
      setSaving(false);
    }
  };

  const toggleArrayItem = (field, value) => {
    const current = form[field] || [];
    if (current.includes(value)) {
      setForm((f) => ({ ...f, [field]: current.filter((v) => v !== value) }));
    } else {
      setForm((f) => ({ ...f, [field]: [...current, value] }));
    }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul={host ? 'Ubah host live' : 'Tambah host live'} onSimpan={handleSubmit} menyimpan={saving}
      testId="livehost-addedithost">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Nama *</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="mt-1 h-9"
                placeholder="Nama host live"
                data-testid="input-name"
              />
            </div>
            <div>
              <Label className="text-sm font-medium">Email *</Label>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                className="mt-1 h-9"
                placeholder="email@example.com"
                data-testid="input-email"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Sandi {!isEdit && '*'}</Label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                className="mt-1 h-9"
                placeholder={isEdit ? 'Kosongkan jika tidak diubah' : 'Sandi login'}
                data-testid="input-password"
              />
            </div>
            <div>
              <Label className="text-sm font-medium">Telepon</Label>
              <Input
                value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                className="mt-1 h-9"
                placeholder="08xxx"
                data-testid="input-phone"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Jenis kerja</Label>
              <Select value={form.employment_type} onValueChange={(v) => setForm((f) => ({ ...f, employment_type: v }))}>
                <SelectTrigger className="mt-1 h-9" data-testid="select-employment">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="full_time">Penuh waktu</SelectItem>
                  <SelectItem value="part_time">Paruh waktu</SelectItem>
                  <SelectItem value="freelance">Freelance</SelectItem>
                  <SelectItem value="contract">Kontrak</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-sm font-medium">Tarif per jam (Rp)</Label>
              <MoneyInput
                value={form.hourly_rate}
                onChange={(e) => setForm((f) => ({ ...f, hourly_rate: Number(e.target.value) }))}
                className="mt-1 h-9"
                data-testid="input-hourly-rate"
              />
            </div>
          </div>

          <div>
            <Label className="mb-2 block text-sm font-medium">Preferensi shift</Label>
            <div className="flex flex-wrap gap-2">
              {['morning', 'afternoon', 'evening', 'night'].map((shift) => (
                <Button key={shift} type="button" size="sm" variant={(form.shift_preferences || []).includes(shift) ? 'default' : 'outline'} onClick={() => toggleArrayItem('shift_preferences', shift)}
                  data-testid={`shift-${shift}`}
                >
                  {({ morning: 'Pagi', afternoon: 'Siang', evening: 'Sore', night: 'Malam' })[shift] || shift}
                </Button>
              ))}
            </div>
          </div>

          <div>
            <Label className="mb-2 block text-sm font-medium">Bahasa yang dikuasai</Label>
            <div className="flex flex-wrap gap-2">
              {['indonesia', 'english', 'mandarin'].map((lang) => (
                <Button key={lang} type="button" size="sm" variant={(form.language_skills || []).includes(lang) ? 'default' : 'outline'} onClick={() => toggleArrayItem('language_skills', lang)}
                  data-testid={`lang-${lang}`}
                >
                  {({ indonesia: 'Indonesia', english: 'Inggris', mandarin: 'Mandarin' })[lang] || lang}
                </Button>
              ))}
            </div>
          </div>

          <div>
            <Label className="mb-2 block text-sm font-medium">Keahlian produk</Label>
            <div className="flex flex-wrap gap-2">
              {['fashion', 'electronics', 'food', 'beauty', 'health', 'home'].map((prod) => (
                <Button key={prod} type="button" size="sm" variant={(form.product_expertise || []).includes(prod) ? 'default' : 'outline'} onClick={() => toggleArrayItem('product_expertise', prod)}
                  data-testid={`product-${prod}`}
                >
                  {({ fashion: 'Fesyen', electronics: 'Elektronik', food: 'Makanan', beauty: 'Kecantikan', health: 'Kesehatan', home: 'Rumah tangga' })[prod] || prod}
                </Button>
              ))}
            </div>
          </div>

          <div>
            <Label className="mb-2 block text-sm font-medium">Akun toko yang ditugaskan</Label>
            <div className="max-h-32 overflow-y-auto border rounded-lg p-2 space-y-1">
              {accounts.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-2">Belum ada akun toko</p>
              ) : (
                accounts.map((acc) => (
                  <label key={acc.id} className="flex items-center gap-2 p-2 rounded hover:bg-muted/50 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={(form.assigned_account_ids || []).includes(acc.id)}
                      onChange={() => toggleArrayItem('assigned_account_ids', acc.id)}
                      className="rounded"
                      data-testid={`account-${acc.id}`}
                    />
                    <span className="text-xs flex-1">{acc.account_name}</span>
                    <Badge variant="outline" className="text-xs">
                      {acc.platform}
                    </Badge>
                  </label>
                ))
              )}
            </div>
          </div>

          {isEdit && (
            <div>
              <Label className="text-sm font-medium">Status</Label>
              <Select value={form.status} onValueChange={(v) => setForm((f) => ({ ...f, status: v }))}>
                <SelectTrigger className="mt-1 h-9" data-testid="select-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Aktif</SelectItem>
                  <SelectItem value="inactive">Nonaktif</SelectItem>
                  <SelectItem value="on_leave">Cuti</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <div>
            <Label className="text-sm font-medium">Catatan</Label>
            <Textarea
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className="mt-1 text-sm"
              rows={3}
              placeholder="Catatan tambahan..."
              data-testid="input-notes"
            />
          </div>
    </FormPopup>
  );
}
