/**
 * Shared status badges for LiveHost Management module.
 */

import { Badge } from '@/components/ui/badge';
import { CheckCircle, XCircle, AlertCircle, Calendar as CalendarIcon } from 'lucide-react';

export const StatusBadge = ({ status }) => {
  const config = {
    active: { label: 'Active', color: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] ' },
    inactive: { label: 'Inactive', color: 'bg-muted text-foreground dark:text-foreground/70' },
    on_leave: { label: 'On Leave', color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))] ' },
  };
  const cfg = config[status] || config.inactive;
  return <Badge className={`text-xs ${cfg.color}`}>{cfg.label}</Badge>;
};

export const AttendanceBadge = ({ status }) => {
  const config = {
    scheduled: { label: 'Scheduled', color: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]', icon: CalendarIcon },
    on_time: { label: 'On Time', color: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))]', icon: CheckCircle },
    late: { label: 'Late', color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))]', icon: AlertCircle },
    no_show: { label: 'No Show', color: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--danger-text))]', icon: XCircle },
    completed: { label: 'Completed', color: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]', icon: CheckCircle },
  };
  const cfg = config[status] || config.scheduled;
  const Icon = cfg.icon;
  return (
    <Badge className={`text-xs ${cfg.color} flex items-center gap-1`}>
      <Icon size={10} />
      {cfg.label}
    </Badge>
  );
};

export const EmploymentTypeBadge = ({ type }) => {
  const config = {
    full_time: { label: 'Full Time', color: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]' },
    part_time: { label: 'Part Time', color: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]' },
    freelance: { label: 'Freelance', color: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]' },
    contract: { label: 'Contract', color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning-text))]' },
  };
  const cfg = config[type] || config.part_time;
  return <Badge className={`text-xs ${cfg.color}`}>{cfg.label}</Badge>;
};
