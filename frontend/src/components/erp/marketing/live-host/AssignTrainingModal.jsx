import { useState, useEffect } from 'react';
import { UserCheck, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import FormPopup from '@/components/ui/form-popup';
import { toast } from 'sonner';
import { API } from './utils';
import { EmploymentTypeBadge } from './Badges';

export default function AssignTrainingModal({ training, authH, onClose, onSuccess }) {
  const [hosts, setHosts] = useState([]);
  const [selectedHostIds, setSelectedHostIds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fetchHosts = async () => {
      try {
        const res = await fetch(`${API}/api/marketing/livehost?status=active`, { headers: authH });
        if (res.ok) {
          const data = await res.json();
          setHosts(data);
        }
      } catch (e) {
        toast.error('Gagal memuat host live');
      } finally {
        setLoading(false);
      }
    };
    fetchHosts();
  }, [authH]);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (selectedHostIds.length === 0) {
      toast.error('Pilih minimal 1 host live');
      return;
    }

    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/livehost/training/assign`, {
        method: 'POST',
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          training_id: training.id,
          host_ids: selectedHostIds,
        }),
      });

      if (res.ok) {
        onSuccess();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal menugaskan pelatihan');
      }
    } catch (e) {
      toast.error('Gagal menugaskan pelatihan');
    } finally {
      setSaving(false);
    }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul={`Tugaskan pelatihan: ${training.title}`} onSimpan={handleSubmit} menyimpan={saving}
      testId="livehost-assigntraining">
          <p className="text-sm text-muted-foreground">
            Pilih LiveHost yang akan di-assign training ini:
          </p>

          {loading ? (
            <div className="flex justify-center py-6">
              <Loader2 size={24} className="animate-spin" />
            </div>
          ) : (
            <div className="max-h-64 overflow-y-auto border rounded-lg p-2 space-y-1">
              {hosts.map((host) => (
                <label
                  key={host.id}
                  className="flex items-center gap-2 p-2 rounded hover:bg-muted/50 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedHostIds.includes(host.id)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedHostIds([...selectedHostIds, host.id]);
                      } else {
                        setSelectedHostIds(selectedHostIds.filter((id) => id !== host.id));
                      }
                    }}
                    className="rounded"
                  />
                  <span className="text-sm flex-1">{host.name}</span>
                  <EmploymentTypeBadge type={host.employment_type} />
                </label>
              ))}
            </div>
          )}
    </FormPopup>
  );
}
