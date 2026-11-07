const statusColors = {
  // General
  active: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))]',
  inactive: 'bg-muted text-muted-foreground',
  // PO Status
  Draft: 'bg-muted text-foreground/90',
  Confirmed: 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]',
  Distributed: 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]',
  'In Production': 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))]',
  'Production Complete': 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))]',
  'Ready to Close': 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]',
  Completed: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))]',
  'Closed Short': 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))]',
  Closed: 'bg-muted text-muted-foreground',
  // Work Order Status
  Waiting: 'bg-muted text-muted-foreground',
  'In Progress': 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]',
  // Invoice Status
  Unpaid: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))]',
  Partial: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))]',
  Paid: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))]',
};

export default function StatusBadge({ status }) {
  const color = statusColors[status] || 'bg-muted text-foreground/90';
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {status}
    </span>
  );
}
