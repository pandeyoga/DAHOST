/**
 * AIImageGeneratorModule — DIHAPUS 2026-11-02 (keputusan owner No.61a).
 *
 * Fitur Image Generator (OpenAI gpt-image-1 lewat Emergent) dan endpoint backend
 * `POST /api/marketing/ai-content/generate-image` sudah dihapus; tab-nya juga sudah
 * dicabut dari Hub Marketing AI. Berkas ini sengaja tinggal sebagai penanda kecil
 * karena `moduleRegistry.js` (milik paket lain) masih memuat impor lazy-nya —
 * setelah impor itu dibersihkan, berkas ini boleh dihapus.
 */
export default function AIImageGeneratorModule() {
  return (
    <div className="p-6 text-sm text-muted-foreground" data-testid="ai-image-generator-removed">
      Fitur Image Generator sudah dihapus.
    </div>
  );
}
