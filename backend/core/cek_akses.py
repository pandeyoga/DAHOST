"""Pemeriksaan akses lintas lapisan (14 Nov 2026) — fungsi MURNI, tanpa DB.

Owner: "bisakah dibuatkan sehingga otomatis cek lapisan yang lain untuk semua akses role". Pola bug hari itu:
layar sebuah menu memanggil layanan yang tercatat di modul LAIN (Master Produk RnD › Buat varian → modul Produksi;
Dashboard Marketing → siklus Portal Manajemen; Kelola Akun › Saldo platform → Keuangan). Sejak itu layanan semacam
ini ikut terbuka otomatis (`data.module_catalog.modul_setara`, peta `peta_menu_layanan.json`); pemeriksa ini
menjelaskan ke owner apa yang ikut terbuka dan apa yang masih tertutup.

Untuk tiap menu yang TERLIHAT oleh centang peran (`module_catalog.menu_access`: ada centang Lihat di modul pemilik
menu), semua layanan yang dipanggil layarnya (peta) dinilai dengan fungsi inti gerbang `module_catalog.putuskan` —
aturan yang sama persis dengan `middleware.module_permission_gate.evaluate`, tanpa DB. Hasil:

  otomatis  : layanan modul lain yang lolos HANYA karena ikut terbuka otomatis dari centang layar ini.
  temuan    : layanan modul lain yang tetap ditolak gerbang, dengan `jenis`:
                kuat      — peran SUDAH punya centang aksi yang sama di modul pemilik menu, tetapi layanannya tetap
                            butuh modul lain (pola bug R&D/Marketing; seharusnya ~0 sejak ikut-otomatis);
                terpisah  — layanan sengaja punya kotak centang sendiri (`module_catalog.sebab_terpisah`);
                informasi — modul pemilik menu tidak punya aksi itu sama sekali (tombol milik modul lain).
              Penolakan di modul pemilik menu sendiri (owner sengaja tidak mencentang) bukan temuan.
"""
from __future__ import annotations

import json
import logging
import os

from data import module_catalog as mc

logger = logging.getLogger(__name__)

_LABEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                           "peta_menu_label.json")
_LABEL_CACHE: dict = {}


def label_menu() -> dict:
    """{menu_id: {"label", "portal": [...]}} dari `peta_menu_label.json` (hilang/rusak → kosong + log)."""
    if "v" not in _LABEL_CACHE:
        try:
            with open(_LABEL_PATH, encoding="utf-8") as fh:
                raw = json.load(fh)
            _LABEL_CACHE["v"] = raw if isinstance(raw, dict) else {}
        except Exception:  # noqa: BLE001 — label hanya untuk kalimat layar
            logger.exception("[cek-akses] %s tidak terbaca", _LABEL_PATH)
            _LABEL_CACHE["v"] = {}
    return _LABEL_CACHE["v"]


def _portal_label(pid: str) -> str:
    return mc.PORTAL_LABELS.get(pid, {"sysadmin": "Administrasi Sistem", "self": "Portal Saya",
                                      "collaboration": "Kolaborasi"}.get(pid, pid))


def _info_menu(menu: str, pemilik: list[dict]) -> dict:
    lab = label_menu().get(menu) or {}
    portals = list(lab.get("portal") or [])
    utama = pemilik[0]["portal"] if (pemilik[0]["portal"] in portals or not portals) else portals[0]
    return {"menu": menu, "label_menu": lab.get("label") or pemilik[0]["label"], "portal": utama,
            "label_portal": _portal_label(utama)}


def _info_modul(mod: dict, act: str) -> dict:
    return {"butuh_modul": mod["id"], "label_modul": mod["label"], "portal_modul": mod["portal"],
            "label_portal_modul": _portal_label(mod["portal"]), "butuh_aksi": act,
            "label_aksi": mc.ACTION_LABELS.get(act, act), "kunci": mc.perm_key(mod["id"], act)}


def periksa(permissions, portals=(), role_name: str = "", hidden_modules=()) -> dict:
    """Pemeriksaan satu kumpulan centang (form Atur peran atau centang tersimpan). Lihat docstring modul."""
    raw = [k for k in (permissions or ()) if k]
    perms = set(mc.expand_permissions(raw))
    hasil = {"otomatis": [], "temuan": [], "jumlah": {"kuat": 0, "informasi": 0, "terpisah": 0, "otomatis": 0}}
    if "*" in perms or str(role_name or "").lower() in ("superadmin", "admin", "owner"):
        return hasil
    allowed = None
    portals = [str(p) for p in (portals or ()) if p]
    if portals:
        from routes.shared import effective_portals
        allowed = set(effective_portals(role_name, portals, []))
    hidden, _ = mc.menu_access(raw)
    tersembunyi = set(hidden) | {str(m) for m in (hidden_modules or ())}
    for menu in sorted(mc.MENU_PEMILIK):
        pemilik = mc.MENU_PEMILIK[menu]
        if menu in tersembunyi or not any(mc.perm_key(o["id"], "view") in perms for o in pemilik):
            continue
        layanan = mc.layanan_menu(menu)
        if not layanan:
            continue
        pemilik_id = {o["id"] for o in pemilik}
        info = None
        for method, path in layanan:
            mod, act = mc.resolve(method, path)
            if not mod or mod["id"] in pemilik_id or mc.is_self_service(method, path):
                continue
            keputusan = mc.putuskan(method, path, perms, allowed)
            info = info or _info_menu(menu, pemilik)
            if keputusan is None:
                if mc.putuskan(method, path, perms, allowed, otomatis=False) is not None:
                    lewat = [alt for alt in mc.modul_setara(method, path)
                             if alt["id"] in pemilik_id and mc.perm_key(alt["id"], act) in perms]
                    hasil["otomatis"].append({**info, "metode": method, "layanan": path, **_info_modul(mod, act),
                                              "lewat_modul": [a["id"] for a in lewat],
                                              "label_lewat": [a["label"] for a in lewat]})
                continue
            punya_aksi = [o for o in pemilik if act in o["actions"]]
            sebab = next((s for s in (mc.sebab_terpisah(method, path, o["id"]) for o in pemilik) if s), None)
            if sebab:
                jenis = "terpisah"
            elif any(mc.perm_key(o["id"], act) in perms for o in punya_aksi):
                jenis = "kuat"
            elif punya_aksi:
                continue          # owner sengaja tidak mencentang aksi ini di modul pemilik menu
            else:
                jenis = "informasi"
            _, _, alasan = keputusan
            setara = [{"modul": a["id"], "label_modul": a["label"], "kunci": mc.perm_key(a["id"], act)}
                      for a in mc.modul_setara(method, path)]
            hasil["temuan"].append({**info, "metode": method, "layanan": path, **_info_modul(mod, act),
                                    "alasan": "portal" if alasan == "portal" else "centang", "jenis": jenis,
                                    "sebab": sebab or "", "setara_mungkin": setara})
    for t in hasil["temuan"]:
        hasil["jumlah"][t["jenis"]] += 1
    hasil["jumlah"]["otomatis"] = len(hasil["otomatis"])
    urut = {"kuat": 0, "informasi": 1, "terpisah": 2}
    hasil["temuan"].sort(key=lambda t: (urut[t["jenis"]], t["label_menu"], t["label_modul"], t["butuh_aksi"],
                                        t["layanan"], t["metode"]))
    hasil["otomatis"].sort(key=lambda t: (t["label_menu"], t["label_modul"], t["butuh_aksi"], t["layanan"]))
    return hasil


def ringkasan(peran: list[dict]) -> list[dict]:
    """[{role_id, name, kuat, informasi, terpisah, otomatis}] untuk daftar peran (`permission_keys`, `portals`)."""
    out = []
    for r in peran or ():
        j = periksa(r.get("permission_keys") or [], r.get("portals") or [], r.get("name") or "",
                    r.get("hidden_modules") or [])["jumlah"]
        out.append({"role_id": r.get("id"), "name": r.get("name"), **j})
    return out
