import { useState, useEffect } from 'react';
import { Clock, Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { getPlatformConfig } from '../AccountBadge';
import { API } from './utils';
import { todayWIB } from '@/lib/waktu';

export default function AddShiftModal({ hosts, accounts, authH, onClose, onSuccess }) {
  const [form, setForm] = useState({
    host_id: '',
    account_id: '',
    date: todayWIB(),
    shift_type: 'morning',
    shift_start_time: '09:00',
    shift_end_time: '13:00',
    notes: '',
  });
  const [saving, setSaving] = useState(false);

  const selectedHost = hosts.find((h) => h.id === form.host_id);
  const hostAssignedIds = (selectedHost?.assigned_accounts || []).map((a) => a.id);
  const availableAccounts =
    hostAssignedIds.length > 0 ? accounts.filter((a) => hostAssignedIds.includes(a.id)) : accounts;

  useEffect(() => {
    if (
      form.account_id &&
      availableAccounts.length > 0 &&
      !availableAccounts.find((a) => a.id === form.account_id)
    ) {
      setForm((f) => ({ ...f, account_id: '' }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.host_id]);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (!form.host_id || !form.account_id || !form.date) {
      toast.error('Host live, akun toko, dan tanggal wajib diisi');
      return;
    }

    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/shifts`, {
        method: 'POST',
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });

      if (res.ok) {
        toast.success('Shift dibuat.');
        onSuccess();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal membuat shift');
      }
    } catch (e) {
      toast.error('Gagal membuat shift');
    } finally {
      setSaving(false);
    }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul="Tambah jadwal shift" onSimpan={handleSubmit} menyimpan={saving}
      testId="livehost-addshift">
          <div>
            <Label className="text-sm font-medium">Host live *</Label>
            <SmartNativeSelect className="mt-1" value={form.host_id} onChange={(e) => { const _v = e.target.value; setForm((f) => ({ ...f, host_id: _v })); }} data-testid="select-host">
                <option value="">Pilih host live</option>
                {hosts.map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.name}
                  </option>
                ))}
              </SmartNativeSelect>
          </div>

          <div>
            <Label className="text-sm font-medium">Akun toko *</Label>
            <SmartNativeSelect className="mt-1" value={form.account_id} onChange={(e) => { const _v = e.target.value; setForm((f) => ({ ...f, account_id: _v })); }} data-testid="select-account">
                <option value="">Pilih akun toko</option>
                {availableAccounts.map((a) => {
                  const cfg = getPlatformConfig(a.platform);
                  return (
                    <option key={a.id} value={a.id}>
                      {a.account_name} · {a.platform === 'tiktok' ? 'TikTok' : cfg.label}
                    </option>
                  );
                })}
              </SmartNativeSelect>
            {form.host_id && hostAssignedIds.length === 0 && (
              <p className="text-xs text-[hsl(var(--warning-text))] mt-1">
                Host belum di-assign ke akun manapun. Edit host untuk menambah assignment.
              </p>
            )}
            {form.account_id &&
              availableAccounts.find((a) => a.id === form.account_id) &&
              (() => {
                const acc = availableAccounts.find((a) => a.id === form.account_id);
                const cfg = getPlatformConfig(acc.platform);
                return (
                  <div
                    className={`mt-1.5 flex items-center gap-1.5 px-2 py-1 rounded border text-xs font-medium ${cfg.bg} ${cfg.border} ${cfg.text}`}
                  >
                    {cfg.icon} Shift untuk: {acc.account_name}
                  </div>
                );
              })()}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Tanggal *</Label>
              <div className="mt-1"><DatePicker value={form.date || ''} onChange={(v) => setForm((f) => ({ ...f, date: v }))} testId="input-date" /></div>
            </div>
            <div>
              <Label className="text-sm font-medium">Jenis shift</Label>
              <SmartNativeSelect className="mt-1" value={form.shift_type} onChange={(e) => { const _v = e.target.value; setForm((f) => ({ ...f, shift_type: _v })); }} data-testid="select-shift-type" searchable={false}>
                  <option value="morning">Pagi</option>
                  <option value="afternoon">Siang</option>
                  <option value="evening">Sore</option>
                  <option value="night">Malam</option>
                  <option value="custom">Atur sendiri</option>
                </SmartNativeSelect>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-sm font-medium">Jam mulai</Label>
              <Input
                type="time"
                value={form.shift_start_time}
                onChange={(e) => setForm((f) => ({ ...f, shift_start_time: e.target.value }))}
                className="mt-1 h-9"
                data-testid="input-start-time"
              />
            </div>
            <div>
              <Label className="text-sm font-medium">Jam selesai</Label>
              <Input
                type="time"
                value={form.shift_end_time}
                onChange={(e) => setForm((f) => ({ ...f, shift_end_time: e.target.value }))}
                className="mt-1 h-9"
                data-testid="input-end-time"
              />
            </div>
          </div>

          <div>
            <Label className="text-sm font-medium">Catatan</Label>
            <Textarea
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className="mt-1 text-sm"
              rows={2}
              placeholder="Catatan shift..."
              data-testid="input-shift-notes"
            />
          </div>
    </FormPopup>
  );
}
