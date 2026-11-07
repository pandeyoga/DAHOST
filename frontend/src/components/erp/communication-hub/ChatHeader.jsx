/**
 * ChatHeader — active channel/DM header with sidebar-toggle + pinned badge + WS status.
 */
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Hash, MessageSquare, ChevronDown, ChevronRight, WifiOff, Pin,
} from 'lucide-react';

export default function ChatHeader({
  activeView,
  isEmbedded,
  sidebarCollapsed,
  onToggleSidebar,
  pinnedCount,
  showPinned,
  onTogglePinned,
  wsConnected,
}) {
  if (!activeView) return null;

  return (
    <div className="px-4 py-3 border-b bg-[hsl(var(--card))] flex items-center gap-3 shrink-0">
      {!isEmbedded && (
        <Button variant="ghost" size="sm" type="button"
          className="h-auto px-0 py-0 gap-0 justify-start whitespace-normal font-normal text-muted-foreground hover:text-foreground"
          onClick={onToggleSidebar}
          aria-label="Toggle sidebar"
        >
          {sidebarCollapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
        </Button>
      )}
      {activeView.type === 'channel' ? (
        <Hash size={16} className="text-muted-foreground" />
      ) : (
        <MessageSquare size={16} className="text-muted-foreground" />
      )}
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-sm">{activeView.name}</p>
        {activeView.description && (
          <p className="text-xs text-muted-foreground truncate">{activeView.description}</p>
        )}
      </div>
      {activeView.type === 'channel' && pinnedCount > 0 && (
        <Button variant="ghost" size="sm" type="button"
          className={`h-auto px-0 py-0 gap-0 justify-start whitespace-normal font-normal flex items-center gap-1.5 text-xs px-2 py-1 rounded-full border transition-colors ${
            showPinned
              ? 'bg-[hsl(var(--warning)/0.1)]  border-[hsl(var(--warning)/0.4)] text-[hsl(var(--warning-text))]'
              : 'border-border text-muted-foreground hover:border-primary/50 hover:text-foreground'
          }`}
          onClick={onTogglePinned}
          data-testid="pinned-messages-btn"
          title="Pesan disematkan"
        >
          <Pin size={12} />
          <span>{pinnedCount} pin</span>
        </Button>
      )}
      {!wsConnected && (
        <Badge variant="destructive" className="text-xs flex items-center gap-1">
          <WifiOff size={10} /> Terputus
        </Badge>
      )}
    </div>
  );
}
