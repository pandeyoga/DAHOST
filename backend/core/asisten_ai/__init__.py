"""Asisten AI (Portal Manajemen) — Tahap A, 7 Nov 2026.

Paket ini memegang lapisan agen chat analis:

  alat_base  kerangka alat (Kontrak A): `@alat`, `AlatError`, `AlatContext`, registri & eksekusi
  alat/      modul alat; setiap modul di folder ini dimuat otomatis
  prompt     instruksi sistem yang STABIL (di-cache)
  mesin      loop agen: streaming, pemikiran ringkas, alat klien & server, cache, batas putaran
  simpan     percakapan (`ai_chat_sessions`, `ai_chat_messages`), hanya milik pengguna sendiri
  saran      tombol saran per peran
  fake       klien Anthropic tiruan untuk uji & lokal (`ASISTEN_AI_FAKE=1`, Kontrak C)

Impor ringan: modul ini sengaja tidak mengimpor submodul supaya `from core.asisten_ai.alat_base
import alat` dari modul alat tidak memicu impor melingkar.
"""
