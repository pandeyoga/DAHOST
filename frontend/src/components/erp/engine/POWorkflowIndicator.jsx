
import { Check } from 'lucide-react';

const STEPS = [
  { key: 'Draft', label: 'Draf', color: 'bg-muted-foreground/50' },
  { key: 'Distributed', label: 'Didistribusikan', color: 'bg-[hsl(var(--primary))]' },
  { key: 'In Production', label: 'Produksi', color: 'bg-[hsl(var(--warning))]' },
  { key: 'Completed', label: 'Selesai', color: 'bg-[hsl(var(--success))]' },
  { key: 'Closed', label: 'Ditutup', color: 'bg-foreground/80' },
];

export default function POWorkflowIndicator({ status, compact = false }) {
  const currentIdx = STEPS.findIndex(s => s.key === status);

  if (compact) {
    return (
      <div className="flex items-center gap-1">
        {STEPS.map((step, idx) => {
          const done = idx < currentIdx;
          const active = idx === currentIdx;
          return (
            <div key={step.key} className="flex items-center gap-1">
              <div className={`w-2 h-2 rounded-full ${
                done ? 'bg-[hsl(var(--success))]' : active ? step.color : 'bg-muted'
              }`} title={step.label} />
              {idx < STEPS.length - 1 && (
                <div className={`w-3 h-0.5 ${idx < currentIdx ? 'bg-[hsl(var(--success))]' : 'bg-muted'}`} />
              )}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="flex items-center justify-between relative">
        <div className="absolute top-4 left-0 right-0 h-0.5 bg-muted z-0" />
        <div
          className="absolute top-4 left-0 h-0.5 bg-[hsl(var(--success))] z-0 transition-all duration-500"
          style={{ width: `${currentIdx === 0 ? 0 : (currentIdx / (STEPS.length - 1)) * 100}%` }}
        />
        {STEPS.map((step, idx) => {
          const done = idx < currentIdx;
          const active = idx === currentIdx;
          return (
            <div key={step.key} className="flex flex-col items-center z-10">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all ${
                done
                  ? 'bg-[hsl(var(--success))] border-[hsl(var(--success)/0.35)] text-white'
                  : active
                  ? `${step.color} border-current text-white`
                  : 'bg-card border-border text-muted-foreground/70'
              }`}>
                {done ? <Check className="w-4 h-4" /> : <span className="text-xs font-bold">{idx + 1}</span>}
              </div>
              <span className={`mt-1.5 text-xs font-medium whitespace-nowrap ${
                active ? 'text-foreground' : done ? 'text-[hsl(var(--success))]' : 'text-muted-foreground/70'
              }`}>{step.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
