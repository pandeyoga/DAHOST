/**
 * ImageLightbox — fullscreen image preview overlay with Download button.
 */
import { Button } from '@/components/ui/button';
import { Download, X } from 'lucide-react';

export default function ImageLightbox({ image, onClose }) {
  if (!image) return null;
  return (
    <div
      className="fixed inset-0 z-[9999] bg-foreground/70 flex items-center justify-center p-4"
      onClick={onClose}
      data-testid="image-lightbox"
    >
      <div className="relative max-w-[90vw] max-h-[90vh]" onClick={(e) => e.stopPropagation()}>
        <img
          src={image.url}
          alt={image.name}
          className="max-w-full max-h-[85vh] object-contain rounded-lg shadow-2xl"
        />
        <div className="absolute top-2 right-2 flex gap-2">
          <a
            href={image.url}
            download={image.name}
            target="_blank"
            rel="noreferrer"
            className="bg-foreground/40 hover:bg-foreground/60 text-foreground rounded-full p-1.5 transition-colors"
            onClick={(e) => e.stopPropagation()}
            title="Unduh" aria-label="Unduh"
          >
            <Download size={16} />
          </a>
          <Button variant="ghost" size="sm" type="button"
            className="h-auto px-0 py-0 gap-0 justify-start whitespace-normal font-normal bg-foreground/40 hover:bg-foreground/60 text-foreground rounded-full p-1.5 transition-colors"
            onClick={onClose}
            title="Tutup" aria-label="Tutup"
          >
            <X size={16} />
          </Button>
        </div>
        {image.name && (
          <p className="absolute bottom-2 left-0 right-0 text-center text-foreground/70 text-xs px-4 truncate">
            {image.name}
          </p>
        )}
      </div>
    </div>
  );
}
