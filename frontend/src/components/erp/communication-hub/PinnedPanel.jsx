/**
 * PinnedPanel — collapsible panel showing pinned messages in the active channel.
 */
import { Button } from '@/components/ui/button';
import { Pin, X } from 'lucide-react';

export default function PinnedPanel({ pinnedMessages, isAdmin, onUnpin, onClose }) {
  if (!pinnedMessages || pinnedMessages.length === 0) return null;

  return (
    <div
      className="border-b bg-[hsl(var(--warning)/0.1)]  px-4 py-2 space-y-1.5 max-h-40 overflow-y-auto"
      data-testid="pinned-messages-panel"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-[hsl(var(--warning-text))] flex items-center gap-1.5">
          <Pin size={12} /> {pinnedMessages.length} Pesan Di-Pin
        </span>
        <Button variant="ghost" size="sm" type="button" onClick={onClose} className="h-auto px-0 py-0 gap-0 justify-start whitespace-normal font-normal text-muted-foreground hover:text-foreground">
          <X size={14} />
        </Button>
      </div>
      {pinnedMessages.map((pm) => (
        <div key={pm.id} className="flex items-start gap-2 text-xs bg-card rounded-lg px-3 py-2 border">
          <Pin size={11} className="text-[hsl(var(--warning-text))] shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <span className="font-medium text-foreground">{pm.sender_name}</span>
            <span className="text-muted-foreground ml-2 truncate block">
              {pm.content || '📎 Lampiran'}
            </span>
          </div>
          {isAdmin && (
            <Button variant="ghost" size="sm" type="button" className="h-auto px-0 py-0 gap-0 justify-start whitespace-normal font-normal"
              onClick={() => onUnpin(pm.id)}
              className="text-muted-foreground hover:text-destructive shrink-0"
              title="Lepas sematan" aria-label="Lepas sematan"
            >
              <X size={12} />
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
