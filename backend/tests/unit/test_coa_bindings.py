"""Uji unit HERMETIK paket S2-H (2026-11-02) — wiring & penjaga Bagan Akun.

Permintaan owner: "untuk Chart of akun itu tolong tandai mana yang terhubung atau tidak karena takutnya
salah hapus". Uji ini membalik temuan audit w1 (T1–T18) menjadi asersi, memakai `_fake_mongo` supaya
jalur kode ASLI (core.coa_bindings, routes.rahaza_coa, routes.rahaza_journals, finance_sync, coa_auto)
ikut teruji:
  * registry keterikatan: semua sumber (profil, toko, rekening, Auto Akun, relasi, pemetaan GL, kas
    kecil, aset, anggaran, konstanta program, jurnal posted/draft, anak, penanda, seed);
  * penjaga aksi (hapus/nonaktif/grup/rinci/tipe/kode/induk) — PUT, DELETE, POST, impor Excel;
  * posting draft memvalidasi ulang akun; sinkron/Auto Akun tidak menonaktifkan/menimpa diam-diam;
  * saldo normal akun kontra; profil posting baru untuk kode akun yang dulu ditulis langsung;
  * uji grep: literal kode akun di modul posting harus tercatat di registry.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_coa_bindings.py -q
"""
import asyncio
import os
import re
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import coa_bindings as cb  # noqa: E402
from core import finance_sync as fs  # noqa: E402
import routes.rahaza_coa as coa  # noqa: E402
import routes.rahaza_journals as rj  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402
import routes.coa_auto as ca  # noqa: E402

USER = {"id": "u-fin", "name": "Finance Uji", "email": "fin@x", "role": "superadmin"}


def run(coro):
    return asyncio.run(coro)


async def _auth(*_a, **_k):
    return USER


async def _nolog(*_a, **_k):
    return None


def acc(code, name=None, type_="EXPENSE", group=False, parent=None, active=True, flags=None, **kw):
    return {"id": f"id-{code}", "code": code, "name": name or f"Akun {code}", "type": type_, "is_group": group,
            "parent_code": parent, "active": active, "flags": flags or {},
            "normal_balance": coa._normal_balance_for(type_, flags), **kw}


@pytest.fixture
def db(monkeypatch):
    d = fm.FakeDB()
    for mod in (coa, rj, pp):
        monkeypatch.setattr(mod, "get_db", lambda d=d: d)
        monkeypatch.setattr(mod, "log_activity", _nolog)
    monkeypatch.setattr(coa, "_require_fin", _auth)
    monkeypatch.setattr(coa, "require_auth", _auth)
    monkeypatch.setattr(rj, "_require_fin", _auth)
    monkeypatch.setattr(pp, "_require_fin", _auth)
    monkeypatch.setattr(pp, "require_auth", _auth)

    async def _open(*_a, **_k):
        return None
    monkeypatch.setattr(rj, "_check_period_open", _open)
    return d


def _base_coa(d):
    d.rahaza_coa_accounts.docs += [
        acc("1-0000", "ASET", "ASSET", group=True),
        acc("1-1200", "Bank", "ASSET", group=True, parent="1-0000", flags={"is_bank": True}),
        acc("1-1201", "Bank BCA", "ASSET", parent="1-1200", flags={"is_bank": True}),
        acc("1-1300", "Piutang Usaha", "ASSET", group=True, parent="1-0000", flags={"is_ar": True}),
        acc("1-1303", "Piutang Platform", "ASSET", parent="1-1300", flags={"is_ar": True}),
        acc("1-1303-SHP-01", "Piutang Channel — GHS", "ASSET", parent="1-1303",
            flags={"subledger": True, "subledger_entity_type": "channel", "subledger_entity_id": "s1",
                   "subledger_parent": "1-1303"}),
        acc("1-2000", "ASET TETAP", "ASSET", group=True, parent="1-0000"),
        acc("1-2501", "Akum. Penyusutan Inventaris", "ASSET", parent="1-2000", flags={"is_contra": True}),
        acc("4-1000", "Penjualan", "REVENUE", group=True),
        acc("4-1110", "Penjualan Shopee", "REVENUE", group=True, parent="4-1000"),
        acc("4-1111", "Penjualan – Shopee GHS", "REVENUE", parent="4-1110", flags={"is_sales": True, "channel": "shopee"}),
        acc("4-1300", "Diskon Penjualan", "REVENUE", parent="4-1000", flags={"is_contra": True}),
        acc("6-2000", "Beban Administrasi & Umum", "EXPENSE", group=True),
        acc("6-2900", "Beban Umum & Lain-lain", "EXPENSE", parent="6-2000"),
        acc("6-2955", "Beban Uji Bebas", "EXPENSE", parent="6-2000", created_by="u-fin"),
        acc("6-2956", "Beban Uji Draft", "EXPENSE", parent="6-2000", created_by="u-fin"),
    ]


# ══════════════════════════ 1. fungsi murni ═══════════════════════════════════
def _b(kind, active=True, detail=""):
    s = cb.KINDS[kind]
    return {"kind": kind, "level": s["level"], "group_label": s["label"], "label": f"uji {kind}",
            "source": "x", "active": active, "screen": None, "detail": detail}


def test_check_action_matrix_per_kind():
    a = {"code": "9-0001", "name": "x", "active": True, "is_group": False}
    g = {**a, "is_group": True}
    for kind, spec in cb.KINDS.items():
        assert "delete" in spec["blocks"], f"{kind}: setiap keterikatan wajib melarang hapus permanen"
        for action in cb.ACTIONS:
            target = g if action == "make_leaf" else a
            blocked = bool(cb.check_action(target, action, [_b(kind)]))
            assert blocked == (action in spec["blocks"]), (kind, action)
            blocked_inactive = bool(cb.check_action(target, action, [_b(kind, active=False)]))
            assert blocked_inactive == (action in (spec["blocks"] & cb._INACTIVE_KEEPS)), (kind, action)


def test_check_action_state_rules_and_free_account():
    free = {"code": "6-2955", "name": "x", "active": True, "is_group": False}
    assert all(not cb.check_action(free, a, []) for a in ("delete", "deactivate", "make_group", "change_type", "change_code"))
    assert cb.check_action({**free, "active": False}, "deactivate", []) == ["akun sudah nonaktif"]
    assert cb.check_action({**free, "is_group": True}, "make_group", []) == ["akun sudah berupa grup"]
    assert cb.check_action(free, "make_leaf", []) == ["akun sudah berupa akun rinci"]
    m = cb.action_matrix({**free, "active": False}, [_b("seed")])
    assert m["delete"]["allowed"] is False and m["reactivate"]["allowed"] is True
    with pytest.raises(ValueError):
        cb.check_action(free, "terbang", [])
    msg = cb.blocked_message({**free, "code": "6-2900"}, "deactivate", [{**_b("profil"), "screen": cb._SCR_PROFIL}])
    assert "6-2900" in msg and "Profil Posting" in msg and "dinonaktifkan" in msg


def test_summarize_levels_and_counts():
    assert cb.summarize([])["level"] == cb.BEBAS
    s = cb.summarize([_b("seed")])
    assert s["level"] == cb.SEED and s["count"] == 0
    s = cb.summarize([_b("seed"), _b("anak", detail="3"), _b("flag")])
    assert s["level"] == cb.STRUKTUR and s["count"] == 2 and s["children"] == 3
    s = cb.summarize([_b("jurnal", detail="5"), _b("jurnal_draft", detail="2"), _b("profil"), _b("seed")])
    assert s["level"] == cb.SISTEM and s["journal_lines"] == 5 and s["draft_entries"] == 2 and s["count"] == 3


def test_code_type_and_parent_rules():
    coa.check_code_type("6-2950", "EXPENSE")
    coa.check_code_type("1-1303-SHP-09", "ASSET")
    coa.check_code_type("7-2100", "OTHER_EXPENSE")
    for code, t in (("abc", "ASSET"), ("6-9999", "REVENUE"), ("1-1201-x", "ASSET"), ("8-1000", "EXPENSE"),
                    ("1-120", "ASSET"), ("6-2950", "BEBAN")):
        with pytest.raises(coa.CoaRuleError):
            coa.check_code_type(code, t)
    by = {a["code"]: a for a in [
        acc("1-1100", "Kas", "ASSET", group=True, parent="1-1000"), acc("1-1101", "Kas Kecil", "ASSET", parent="1-1100"),
        acc("1-1000", "Aset Lancar", "ASSET", group=True), acc("1-1201", "Bank", "ASSET", parent="1-1000"),
        acc("6-2000", "Beban", "EXPENSE", group=True), acc("7-0000", "Lain", "OTHER_INCOME", group=True),
        acc("1-9000", "Grup nonaktif", "ASSET", group=True, active=False)]}
    coa.check_parent("1-1102", "ASSET", "1-1100", by)
    coa.check_parent("7-2100", "OTHER_EXPENSE", "7-0000", by)        # pendapatan/beban lain boleh campur
    coa.check_parent("1-1201-XX", "ASSET", "1-1201", by, is_subledger=True)   # sub-ledger di bawah kontrol
    bad = [("1-1100", "ASSET", "1-1101", "siklus"), ("1-1100", "ASSET", "1-1100", "dirinya sendiri"),
           ("1-1102", "ASSET", "9-9999", "tidak ada"), ("6-2100", "EXPENSE", "1-1201", "rinci"),
           ("6-2100", "EXPENSE", "1-1100", "bertipe"), ("1-1102", "ASSET", "1-9000", "nonaktif")]
    for code, t, parent, word in bad:
        with pytest.raises(coa.CoaRuleError) as e:
            coa.check_parent(code, t, parent, by)
        assert word in str(e.value), (code, parent, str(e.value))


def test_merge_flags_keeps_system_flags_and_normal_balance_contra():
    old = {"is_sales": True, "channel": "shopee", "subledger_entity_type": "channel", "legacy_of": "1-1201",
           "is_inventory_rm": True}
    assert coa.merge_flags(old, {}) == old                                  # T8: '{}' tidak menghapus apa pun
    out = coa.merge_flags(old, {"is_sales": False, "subledger_entity_type": None, "legacy_of": "", "is_contra": True,
                                "channel": "TikTok", "bebas": 1})
    assert out == {"channel": "tiktok", "subledger_entity_type": "channel", "legacy_of": "1-1201",
                   "is_inventory_rm": True, "is_contra": True}
    assert coa._normal_balance_for("ASSET") == "DEBIT"
    assert coa._normal_balance_for("ASSET", {"is_contra": True}) == "CREDIT"
    assert coa._normal_balance_for("REVENUE", {"is_contra": True}) == "DEBIT"
    assert coa._normal_balance_for("EQUITY", {"is_contra": True}) == "DEBIT"


def test_plan_account_update_rules():
    a = acc("6-2900", "Beban Umum", "EXPENSE", parent="6-2000")
    by = {"6-2000": acc("6-2000", "Beban", "EXPENSE", group=True), "6-2900": a, "1-1200": acc("1-1200", "Bank", "ASSET", group=True)}
    jur = [_b("jurnal", detail="1")]
    with pytest.raises(coa.CoaRuleError) as e:                           # No.48 — pesan lama tetap
        coa.plan_account_update(a, {"is_group": True}, jur, by)
    assert "1 baris jurnal" in str(e.value)
    prof = [{**_b("profil"), "label": "Beban operasional › Beban bawaan (Dr)", "screen": cb._SCR_PROFIL}]
    for body in ({"is_group": True}, {"active": False}):                   # T3, T2
        with pytest.raises(coa.CoaRuleError) as e:
            coa.plan_account_update(a, body, prof, by)
        assert "Profil Posting" in str(e.value)
    with pytest.raises(coa.CoaRuleError) as e:                           # T7 — tipe & kode tidak diabaikan diam-diam
        coa.plan_account_update(a, {"type": "OTHER_EXPENSE"}, jur, by)
    assert "baris jurnal" in str(e.value).lower() and "Tipe akun 6-2900" in str(e.value)
    with pytest.raises(coa.CoaRuleError):
        coa.plan_account_update(a, {"code": "6-2999"}, prof, by)
    with pytest.raises(coa.CoaRuleError):
        coa.plan_account_update(a, {"parent_code": "1-1200"}, [], by)
    up = coa.plan_account_update(a, {"code": "6-2900", "type": "EXPENSE", "name": "Beban Umum", "is_group": False,
                                     "parent_code": "6-2000", "active": True, "flags": {}}, prof, by)
    assert up == {}                                                      # form lengkap tanpa perubahan = no-op
    up = coa.plan_account_update(a, {"name": "Beban Lain-lain"}, prof, by)
    assert up == {"name": "Beban Lain-lain", "name_user_set": True}
    up = coa.plan_account_update(a, {"flags": {"is_contra": True}}, [], by)
    assert up["normal_balance"] == "CREDIT" and up["flags"] == {"is_contra": True}
    free = acc("6-2955", "Bebas", "EXPENSE", parent="6-2000")
    up = coa.plan_account_update(free, {"code": "6-2957", "type": "OTHER_EXPENSE"}, [], {**by, "6-2955": free})
    assert up["code"] == "6-2957" and up["type"] == "OTHER_EXPENSE" and "normal_balance" not in up   # tetap DEBIT
    with pytest.raises(coa.CoaRuleError):                                # awalan 6 bukan pendapatan
        coa.plan_account_update(free, {"type": "REVENUE"}, [], {**by, "6-2955": free})
    g = acc("1-1200", "Bank", "ASSET", group=True)
    with pytest.raises(coa.CoaRuleError) as e:                           # T14 — grup → rinci dengan anak
        coa.plan_account_update(g, {"is_group": False}, [_b("anak", detail="14")], by)
    assert "anak" in str(e.value)
    up = coa.plan_account_update(a, {"active": False}, jur, by)          # berjurnal tapi bukan target → boleh
    assert up["active"] is False and up["active_user_set"] is True


# ══════════════════════════ 2. registry konstanta ═════════════════════════════
def test_constant_sources_resolve_from_their_modules():
    for src in cb.CONSTANT_SOURCES:
        vals = cb._resolve_constant(src)
        assert vals, f"konstanta {src['module']}.{src['attr']}[{src.get('key')}] tidak terbaca/kosong"
        assert all(cb.CODE_RX.match(v) for v in vals), vals
    codes = {b["code"] for b in cb.constant_bindings()}
    for c in ("1-1610", "6-3400", "3-2000", "4-1400", "6-1110", "6-1112", "6-1113", "6-1130", "7-4000", "1-1305", "1-1404"):
        assert c in codes, c


def test_new_profile_roles_default_to_current_program_codes():
    """Butir 4: 11 akun yang dulu hanya terikat lewat kode program kini peran profil; bawaan == kode program."""
    defaults = {p["event_type"]: p["mapping"] for p in pp.DEFAULT_PROFILES}
    for b in cb.constant_bindings():
        if b.get("role") and b["kind"] in ("kode_posting", "kode_cadangan") and b["source"].startswith(("routes.", "core.")):
            et, role = b["role"]
            assert defaults.get(et, {}).get(role) == b["code"], (b["source"], et, role, b["code"])
    covered = {c for et in ("marketplace_settlement", "employee_travel", "year_end_close", "subledger_opening_balance")
               for c in defaults[et].values()}
    assert {"1-1305", "1-1610", "3-2000", "4-1400", "6-1110", "6-1112", "6-1113", "6-1130", "6-3400", "7-4000"} <= covered
    # 1-1303 = induk Auto Akun toko (layar Auto Akun) — sudah bisa diatur, bukan peran profil
    from routes.coa_auto import DEFAULT_ENTITY_TYPES
    assert DEFAULT_ENTITY_TYPES["channel"]["parent_code"] == "1-1303"


def test_labels_cover_every_default_event_and_role():
    for p in pp.DEFAULT_PROFILES:
        assert p["event_type"] in pp.EVENT_LABELS, p["event_type"]
        for role in p["mapping"]:
            assert role in pp.ROLE_LABELS or (p["event_type"], role) in pp.ROLE_LABELS_BY_EVENT, (p["event_type"], role)
    assert pp.role_label("credit_other_deduction") == "Potongan penyesuaian manual payroll (Cr)"
    assert "BPJS Kesehatan" in pp.role_label("credit_bpjs_kes_payable")
    assert "kas kecil" in pp.role_label("debit_employee_advance", "petty_cash_expense").lower()
    assert pp.role_label("peran_baru_x") == "peran baru x"


_GUARD_FILES = sorted({src["module"].replace(".", "/") + ".py" for src in cb.CONSTANT_SOURCES
                       if src["module"] != "routes.employee_expense_gl_mapping"}
                      | {f for f, *_ in cb.INLINE_CODES})


@pytest.mark.parametrize("path", _GUARD_FILES)
def test_grep_guard_literal_account_codes_are_registered(path):
    """Literal kode akun ("x-xxxx") di modul posting WAJIB tercatat (konstanta yang dibaca registry atau
    INLINE_CODES). Menambah literal baru tanpa mendaftarkannya ⇒ gagal di sini."""
    mod = path[:-3].replace("/", ".")
    allowed = set()
    for src in cb.CONSTANT_SOURCES:
        if src["module"] == mod:
            allowed |= set(cb._resolve_constant(src))
    allowed |= {c for f, c, *_ in cb.INLINE_CODES if f == path}
    if mod == "core.finance_sync":
        allowed |= set(fs.CMT_AP_OLD_DEFAULTS)
    found = set()
    with open(os.path.join(BACKEND, path), encoding="utf-8") as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                continue
            found |= set(re.findall(r"[\"']([1-7]-\d{4})[\"']", line.split("  #")[0]))
    assert found <= allowed, f"{path}: kode akun belum tercatat di core/coa_bindings: {sorted(found - allowed)}"


# ══════════════════════════ 3. pengumpul keterikatan ══════════════════════════
def _wired_db():
    d = fm.FakeDB()
    _base_coa(d)
    d.rahaza_coa_accounts.docs += [acc("2-1100", "Hutang Usaha", "LIABILITY"),
                                   acc("2-1100-SUP-1", "Hutang Supplier — A", "LIABILITY", parent="2-1100"),
                                   acc("1-1219", "Bank BCA – Lainnya", "ASSET", parent="1-1200", flags={"is_bank": True}),
                                   acc("6-2400", "ATK", "EXPENSE", parent="6-2000"),
                                   acc("1-2500", "Inventaris", "ASSET", parent="1-2000"),
                                   acc("6-2730", "Penyusutan Kantor", "EXPENSE", parent="6-2000")]
    d.rahaza_posting_profiles.docs += [
        {"event_type": "expense", "active": True, "mapping": {"debit_expense_default": "6-2900", "credit_cash_default": "1-1201"}},
        {"event_type": "ar_invoice", "active": True, "mapping": {"debit_sales_discount": "4-1300", "debit_ar": "1-9999"}},
    ]
    d.marketing_platform_accounts.docs.append({"id": "s1", "account_code": "SHP-01", "account_name": "Shopee GHS",
                                               "coa_revenue_code": "4-1111", "ar_account_code": "1-1303-SHP-01",
                                               "coa_receivable_code": "1-1303-SHP-01", "coa_cash_code": "1-1201"})
    d.rahaza_cash_accounts.docs.append({"id": "k1", "code": "1-1219", "name": "BCA Lainnya", "gl_account_code": "1-1219"})
    d.rahaza_suppliers.docs.append({"id": "v1", "code": "SUP-1", "name": "Pemasok A", "ap_account_code": "2-1100-SUP-1"})
    d.employee_expense_gl_mappings.docs.append({"id": "m1", "category": "ATK / Perlengkapan", "gl_account_code": "6-2400", "is_active": True})
    d.rahaza_petty_cash_funds.docs.append({"id": "f1", "name": "Kas Kecil Gudang", "bank_account_code": "1-1201", "status": "active"})
    d.rahaza_fixed_assets.docs.append({"id": "a1", "asset_code": "AST-1", "name": "Laptop", "status": "active",
                                       "account_id_asset": "id-1-2500", "account_id_accum_depr": "1-2501",
                                       "account_id_depr_expense": "id-6-2730"})
    d.rahaza_budget_items.docs.append({"id": "b1", "account_id": "id-6-2900", "amount": 1})
    d.rahaza_journal_lines.docs.append({"account_code": "6-2900", "debit": 5000, "credit": 0})
    d.rahaza_journal_entries.docs.append({"id": "je-d", "status": "draft", "je_number": "JE-D",
                                          "lines": [{"account_code": "6-2956", "debit": 1, "credit": 0},
                                                    {"account_code": "1-1201", "debit": 0, "credit": 1}]})
    return d


def test_collect_bindings_all_sources():
    d = _wired_db()
    allb = run(cb.collect_bindings(d))
    kinds = {c: {b["kind"] for b in bl} for c, bl in allb.items()}
    assert {"profil", "kode_posting", "jurnal", "anggaran"} <= kinds["6-2900"]
    assert {"profil", "toko", "kas_kecil", "flag", "jurnal_draft"} <= kinds["1-1201"]
    assert {"toko", "subledger"} <= kinds["1-1303-SHP-01"]
    assert {"profil"} <= kinds["4-1300"] and "seed" in kinds["4-1300"]
    assert {"toko", "flag", "sinkron_toko"} <= kinds["4-1111"]
    assert {"rekening", "flag"} <= kinds["1-1219"]
    assert "entitas" in kinds["2-1100-SUP-1"]
    assert "pemetaan_gl" in kinds["6-2400"]
    assert {"aset_tetap"} <= kinds["1-2500"] and {"aset_tetap"} <= kinds["1-2501"] and {"aset_tetap"} <= kinds["6-2730"]
    assert {"auto_coa", "anak", "kode_sinkron"} <= kinds["1-1303"]
    assert "anak" in kinds["1-1200"] and "jurnal_draft" in kinds["6-2956"]
    assert "6-2955" not in allb                                      # bebas sepenuhnya
    assert "1-9999" in allb                                          # rujukan ke akun yang tidak ada ikut muncul
    one = run(cb.collect_bindings(d, ["6-2900"]))
    assert set(one) == {"6-2900"} and {b["kind"] for b in one["6-2900"]} == kinds["6-2900"]
    prof = next(b for b in allb["4-1300"] if b["kind"] == "profil")
    assert prof["label"] == "Faktur penjualan (AR) › Diskon penjualan (Dr)" and prof["screen"]["tab"] == "mapping" and prof["screen"]["view"] == "posting"  # 2026-11-04: Pengaturan Keuangan


def test_integrity_report_detects_dangling_inactive_group_and_fallbacks():
    d = _wired_db()
    d.rahaza_cash_accounts.docs.append({"id": "k2", "code": "1-1299", "name": "Bank Hilang", "gl_account_code": "1-1299"})
    for a in d.rahaza_coa_accounts.docs:
        if a["code"] == "6-2400":
            a["active"] = False
        if a["code"] == "4-1300":
            a["is_group"] = True
    rep = run(cb.integrity_report(d))
    dang = {r["code"] for r in rep["dangling_refs"]}
    assert {"1-9999", "1-1299"} <= dang and rep["ok"] is False
    assert "6-2400" in {r["code"] for r in rep["inactive_targets"]}
    assert "4-1300" in {r["code"] for r in rep["group_targets"]}
    fb = {x["role"] for x in rep["fallback_warnings"]}
    assert "petty_cash_replenish.debit_petty_cash" in fb             # peran kosong → cadangan 1-1101 akan terpakai
    # 2026-11-02 (butir 9): cadangan 6-2200 (Listrik & Air) dihapus — peran kosong kini DITOLAK, bukan cadangan
    assert "petty_cash_expense.debit_expense_default" not in fb
    assert not any(x["code"] == "6-2200" for x in rep["fallback_warnings"])


# ══════════════════════════ 4. rute: penjaga ══════════════════════════════════
def test_delete_only_free_accounts_t1_t11_t12(db):
    d = db
    for x in _wired_db()._cols.items():
        d._cols[x[0]] = x[1]
    out = run(coa.deactivate_account("id-6-2955", fm.FakeRequest()))
    assert out == {"ok": True, "deleted": True} and not any(a["code"] == "6-2955" for a in d.rahaza_coa_accounts.docs)
    for code, word in (("4-1300", "Profil Posting"), ("1-1300", "anak"), ("4-1111", "toko"), ("1-1219", "Rekening"),
                       ("1-1303-SHP-01", "sub-ledger"), ("1-1303", "Auto Akun"), ("6-2956", "draft")):
        with pytest.raises(HTTPException) as e:
            run(coa.deactivate_account(f"id-{code}", fm.FakeRequest()))
        assert e.value.status_code == 409 and word.lower() in e.value.detail.lower(), (code, e.value.detail)
        assert any(a["code"] == code for a in d.rahaza_coa_accounts.docs)
    with pytest.raises(HTTPException) as e:                              # akun bawaan tanpa rujukan → tawarkan nonaktif
        run(coa.deactivate_account("id-1-2000", fm.FakeRequest()))
    assert "bawaan" in e.value.detail and "DINONAKTIFKAN" not in e.value.detail   # 1-2000 punya anak → nonaktif pun ditolak
    d.rahaza_coa_accounts.docs.append(acc("6-2500", "Sewa Kantor", "EXPENSE", parent="6-2000"))
    with pytest.raises(HTTPException) as e:
        run(coa.deactivate_account("id-6-2500", fm.FakeRequest()))
    assert "masih bisa DINONAKTIFKAN" in e.value.detail


def test_put_guards_t2_t3_t7_t9_t14_and_reactivate(db):
    d = db
    for k, v in _wired_db()._cols.items():
        d._cols[k] = v
    for body, word in (({"active": False}, "Profil Posting"), ({"is_group": True}, "baris jurnal"),
                       ({"type": "OTHER_EXPENSE", "code": "9-9999"}, "kode")):
        with pytest.raises(HTTPException) as e:
            run(coa.update_account("id-6-2900", fm.FakeRequest(body)))
        assert e.value.status_code == 400 and word.lower() in e.value.detail.lower(), e.value.detail
    with pytest.raises(HTTPException) as e:                              # T9 siklus
        run(coa.update_account("id-1-1200", fm.FakeRequest({"parent_code": "1-1201"})))
    assert "siklus" in e.value.detail
    with pytest.raises(HTTPException):                                   # T14 grup → rinci dengan anak
        run(coa.update_account("id-1-1200", fm.FakeRequest({"is_group": False})))
    out = run(coa.update_account("id-6-2955", fm.FakeRequest({"active": False})))
    assert out["active"] is False and out["active_user_set"] is True
    out = run(coa.update_account("id-6-2955", fm.FakeRequest({"active": True})))
    assert out["active"] is True and out.get("deactivated_reason") is None
    out = run(coa.update_account("id-6-2900", fm.FakeRequest({"name": "Beban Umum", "is_group": False})))
    assert "is_group_user_set" not in out                                # simpan form tanpa ubah grup tidak menandai


def test_create_account_validation_t10(db):
    db.rahaza_coa_accounts.docs += [acc("1-2000", "ASET TETAP", "ASSET", group=True),
                                    acc("1-1201", "Bank", "ASSET"), acc("6-2000", "Beban", "EXPENSE", group=True)]
    for body in ({"code": "abc", "name": "x", "type": "ASSET"},
                 {"code": "6-9999", "name": "x", "type": "REVENUE", "parent_code": "6-2000"},
                 {"code": "1-1201-X", "name": "x", "type": "EXPENSE", "parent_code": "1-1201"}):
        with pytest.raises(HTTPException) as e:
            run(coa.create_account(fm.FakeRequest(body)))
        assert e.value.status_code == 400
    out = run(coa.create_account(fm.FakeRequest({"code": "1-2502", "name": "Akum. Penyusutan Baru", "type": "ASSET",
                                                 "parent_code": "1-2000", "flags": {"is_contra": True, "subledger": True}})))
    assert out["normal_balance"] == "CREDIT" and out["flags"] == {"is_contra": True}
    with pytest.raises(HTTPException) as e:
        run(coa.create_account(fm.FakeRequest({"code": "1-2502", "name": "dup", "type": "ASSET"})))
    assert e.value.status_code == 409


def test_post_draft_revalidates_accounts_t5(db):
    db.rahaza_coa_accounts.docs += [acc("6-2956", "Draft", "EXPENSE"), acc("1-1201", "Bank", "ASSET")]
    db.rahaza_journal_entries.docs.append({"id": "je1", "je_number": "JE-1", "status": "draft", "date": "2026-11-02",
                                           "lines": [{"account_code": "6-2956", "account_name": "lama", "debit": 3000, "credit": 0},
                                                     {"account_code": "1-1201", "debit": 0, "credit": 3000}]})
    db.rahaza_coa_accounts.docs[0]["active"] = False
    with pytest.raises(HTTPException) as e:
        run(rj.post_journal("je1", fm.FakeRequest()))
    assert e.value.status_code == 400 and "6-2956" in e.value.detail and "JE-1" in e.value.detail
    assert db.rahaza_journal_lines.docs == [] and db.rahaza_journal_entries.docs[0]["status"] == "draft"
    db.rahaza_coa_accounts.docs[0]["active"] = True
    assert run(rj.post_journal("je1", fm.FakeRequest()))["ok"] is True
    assert {ln["account_name"] for ln in db.rahaza_journal_lines.docs} == {"Draft", "Bank"}   # nama disegarkan


def test_coa_import_uses_same_guards_and_merges_flags_t8(db):
    d = db
    for k, v in _wired_db()._cols.items():
        d._cols[k] = v
    rows = [{"code": "6-2900", "name": "Beban Umum", "type": "REVENUE", "parent_code": "6-2000", "is_group": True,
             "normal_balance": "CREDIT", "active": True, "flags": {}},
            {"code": "4-1111", "name": "Penjualan – Shopee GHS", "type": "REVENUE", "parent_code": "4-1110",
             "is_group": False, "normal_balance": "CREDIT", "active": True, "flags": {}},
            {"code": "6-2960", "name": "Beban Baru", "type": "EXPENSE", "parent_code": "6-2000"},
            {"code": "6-2961", "name": "Anak dari baris baru", "type": "EXPENSE", "parent_code": "6-2960"},
            {"code": "1-2502", "name": "Akum baru", "type": "ASSET", "parent_code": "1-2000", "normal_balance": "CREDIT"},
            {"code": "1-1201", "name": "Bank BCA", "type": "ASSET", "active": False}]
    out = run(coa.prepare_coa_import(d, rows))
    errs = {r["code"]: e for r, (_, e) in zip(rows, out)}
    assert errs["6-2900"] and errs["1-1201"] and "Profil Posting" in errs["1-1201"][0]
    assert not errs["4-1111"] and out[1][0] == {"code": "4-1111"}       # tanpa perubahan; penanda tidak dihapus
    assert errs["6-2961"] and "rinci" in errs["6-2961"][0]              # induk baris baru = akun rinci → ditolak
    assert not errs["6-2960"] and out[2][0]["normal_balance"] == "DEBIT"
    assert not errs["1-2502"] and out[4][0]["flags"] == {"is_contra": True} and out[4][0]["normal_balance"] == "CREDIT"


def test_profile_save_reports_all_bad_roles_with_labels(db):
    db.rahaza_coa_accounts.docs += [acc("6-2900", "Beban", "EXPENSE"), acc("6-2000", "Grup", "EXPENSE", group=True),
                                    acc("1-1201", "Bank", "ASSET", active=False)]
    db.rahaza_posting_profiles.docs.append({"event_type": "expense", "mapping": {}})
    with pytest.raises(HTTPException) as e:
        run(pp.update_profile("expense", fm.FakeRequest({"mapping": {"debit_expense_default": "6-2000",
                                                                     "credit_cash_default": "1-1201",
                                                                     "debit_expense": "4-1300"}})))
    msg = e.value.detail
    assert "[debit_expense_default]" in msg and "grup" in msg and "[credit_cash_default]" in msg and "nonaktif" in msg
    assert "4-1300 tidak ada di Bagan Akun" in msg and "Beban bawaan (Dr)" in msg
    meta = run(pp.profiles_meta(fm.FakeRequest()))
    # 2026-11-02 (butir 7): pencairan marketplace kini membaca peran profil
    assert meta["consumers"]["marketplace_settlement.debit_platform_fee"][0]["reads_profile"] is True
    assert meta["consumers"]["payroll_finalize.credit_other_deduction"][0]["reads_profile"] is True


def test_role_code_helper_reads_profile_with_default(db):
    db.rahaza_posting_profiles.docs.append({"event_type": "year_end_close", "active": True,
                                            "mapping": {"credit_retained_earnings": "3-2100"}})
    assert run(pp.role_code(db, "year_end_close", "credit_retained_earnings", "3-2000")) == "3-2100"
    assert run(pp.role_code(db, "year_end_close", "x", "3-2000")) == "3-2000"


# ══════════════════════════ 5. sinkron & Auto Akun ════════════════════════════
def test_sync_stores_skips_user_created_revenue_account_t13():
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [
        acc("4-1110", "Penjualan Online Shop – Shopee", "REVENUE", group=True),
        acc("4-1111", "Penjualan – Shopee GHS", "REVENUE", parent="4-1110", created_by="system"),
        acc("4-1112", "Penjualan – Shopee Daluna", "REVENUE", parent="4-1110", created_by="system", created_by_name="auto-seed"),
        acc("4-1119", "Penjualan – Shopee Toko Offline", "REVENUE", parent="4-1110", created_by="u-fin", created_by_name="Fin"),
        acc("4-1118", "Penjualan – Shopee Dihidupkan", "REVENUE", parent="4-1110", created_by="system", active_user_set=True),
    ]
    d.marketing_platform_accounts.docs.append({"id": "s1", "account_code": "SHP-01", "account_name": "Shopee GHS",
                                               "platform": "shopee", "coa_revenue_code": "4-1111",
                                               "ar_account_code": "1-1303-SHP-01"})
    rep = {}
    run(fs._sync_stores(d, rep))
    st = {a["code"]: a.get("active") for a in d.rahaza_coa_accounts.docs}
    assert rep["stores"]["revenue_deactivated"] == ["4-1112"] and st["4-1112"] is False
    assert st["4-1119"] is True and st["4-1118"] is True
    assert {x["code"] for x in rep["stores"]["revenue_deactivation_skipped"]} == {"4-1118", "4-1119"}
    plan = run(fs.store_revenue_deactivation_plan(d))                 # dipakai juga oleh Setup Akuntansi
    assert plan["deactivate"] == [] and {x["code"] for x in plan["skipped"]} == {"4-1118", "4-1119"}


def test_sync_store_error_does_not_abort_whole_sync():
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [acc("4-1110", "Shopee", "REVENUE", group=True)] + [
        acc(f"4-111{n}", f"Penjualan – Shopee T{n}", "REVENUE", parent="4-1110") for n in range(1, 10)]
    d.marketing_platform_accounts.docs += [
        {"id": "s1", "account_code": "SHP-01", "account_name": "Toko Baru", "platform": "shopee"},
        {"id": "s2", "account_code": "SHP-02", "account_name": "Shopee T2", "platform": "shopee", "coa_revenue_code": "4-1112"}]
    rep = {}
    run(fs._sync_stores(d, rep))
    assert rep["stores"]["revenue_errors"][0]["store"] == "SHP-01"
    assert ("SHP-02", "4-1112", "1-1303") in rep["stores"]["mapped"]


def test_auto_coa_keeps_user_renamed_subledger_t15_and_refuses_inactive_parent():
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [acc("2-1110", "Hutang Vendor CMT", "LIABILITY"),
                                   acc("2-1110-DA-01", "Hutang CMT — nama diubah finance", "LIABILITY", parent="2-1110",
                                       name_user_set=True,
                                       flags={"subledger_entity_type": "cmt_vendor", "subledger_entity_id": "v1"}),
                                   acc("1-1303", "Piutang Platform", "ASSET", active=False)]
    r = run(ca.ensure_subledger_account(d, "cmt_vendor", "v1", "Hutang CMT — pak aan"))
    assert r["ok"] and r["account"]["name"] == "Hutang CMT — nama diubah finance"
    assert d.rahaza_coa_accounts.docs[1]["name"] == "Hutang CMT — nama diubah finance"
    r = run(ca.ensure_subledger_account(d, "channel", "s9", "Piutang Channel — Uji", code_hint="UJI"))
    assert r["ok"] is False and "nonaktif" in r["error"]


def test_auto_coa_settings_parent_must_be_active_same_family():
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [acc("2-1100", "Hutang Usaha", "LIABILITY"), acc("6-2900", "Beban", "EXPENSE"),
                                   acc("2-1199", "Hutang Lama", "LIABILITY", active=False)]
    with pytest.raises(HTTPException) as e:
        run(ca._guard_parent(d, "supplier", d.rahaza_coa_accounts.docs[1]))
    assert "LIABILITY" in e.value.detail
    with pytest.raises(HTTPException):
        run(ca._guard_parent(d, "supplier", d.rahaza_coa_accounts.docs[2]))
    run(ca._guard_parent(d, "supplier", acc("2-1105", "Hutang Lain", "LIABILITY")))


def test_backfill_restores_missing_store_subledger_but_not_plain_bank():
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [acc("1-1303", "Piutang Platform", "ASSET"), acc("1-1200", "Bank", "ASSET", group=True)]
    d.marketing_platform_accounts.docs.append({"id": "s1", "account_code": "SHP-01", "account_name": "Shopee GHS",
                                               "ar_account_code": "1-1303-SHP-01"})
    d.rahaza_cash_accounts.docs.append({"id": "k1", "code": "1-1211", "name": "BCA Dekka", "gl_account_code": "1-1211"})
    rep = {}
    run(fs._backfill_subledgers(d, rep, None))
    rest = {x["entity_type"]: x for x in rep["subledgers_restored"]}
    assert rest["channel"]["now"] == "1-1303-SHP-01" and any(a["code"] == "1-1303-SHP-01" for a in d.rahaza_coa_accounts.docs)
    assert rest["bank"]["now"] is None and d.rahaza_cash_accounts.docs[0]["gl_account_code"] == "1-1211"


# ══════════════════════════ 6. seed, daftar, pohon ════════════════════════════
def test_seed_fixes_contra_normal_balance_idempotent_t18(db):
    db.rahaza_coa_accounts.docs += [
        {"id": "x1", "code": "1-2501", "type": "ASSET", "normal_balance": "DEBIT", "flags": {"is_contra": True, "is_accum_dep": True}},
        {"id": "x2", "code": "4-1200", "type": "REVENUE", "normal_balance": "CREDIT", "flags": {"is_contra": True}},
        {"id": "x3", "code": "3-4000", "type": "EQUITY", "normal_balance": "CREDIT", "flags": {"is_contra": True}},
        {"id": "x4", "code": "4-1400", "type": "REVENUE", "normal_balance": "DEBIT", "flags": {"is_contra": True}},
    ]
    rep = run(coa.seed_coa_accounts(db))
    by = {a["code"]: a for a in db.rahaza_coa_accounts.docs}
    assert {c: by[c]["normal_balance"] for c in ("1-2501", "4-1200", "3-4000", "4-1400")} == \
        {"1-2501": "CREDIT", "4-1200": "DEBIT", "3-4000": "DEBIT", "4-1400": "DEBIT"}
    assert set(rep["normal_balance_fixed"]) == {"1-2501", "4-1200", "3-4000"}
    for c in ("1-1302", "1-2201", "1-2301", "1-2401", "4-1300"):          # akun kontra yang baru disemai
        assert by[c]["normal_balance"] == ("CREDIT" if c.startswith("1-") else "DEBIT"), c
    assert set(rep["recreated"]) and "1-2501" not in rep["recreated"]  # DB tidak kosong → dilaporkan
    assert run(coa.seed_coa_accounts(db))["normal_balance_fixed"] == [] and run(coa.seed_coa_accounts(db))["recreated"] == []


def test_list_with_usage_and_tree_breaks_cycles(db):
    d = db
    for k, v in _wired_db()._cols.items():
        d._cols[k] = v
    rows = run(coa.list_accounts(fm.FakeRequest(), active_only=False, with_usage=True))
    by = {r["code"]: r["usage"] for r in rows}
    assert by["6-2955"]["level"] == "BEBAS" and by["6-2955"]["can_delete"] is True
    assert by["6-2900"]["level"] == "SISTEM" and by["6-2900"]["can_delete"] is False
    assert by["6-2900"]["can_deactivate"] is False and by["6-2900"]["journal_lines"] == 1
    assert by["1-1200"]["can_make_leaf"] is False
    act = run(coa.list_accounts(fm.FakeRequest(), active_only=True, with_usage=True))
    assert {r["code"]: r["usage"]["level"] for r in act} == {c: u["level"] for c, u in by.items()}
    u = run(coa.account_usage("6-2900", fm.FakeRequest()))
    assert u["summary"]["level"] == "SISTEM" and u["actions"]["delete"]["allowed"] is False
    assert {g["kind"] for g in u["groups"]} >= {"profil", "jurnal", "kode_posting", "anggaran"}
    # data lama bersiklus (T9): semua akun tetap tampil di pohon
    rows = [acc("1-1100", "Kas", "ASSET", group=True, parent="1-1101"), acc("1-1101", "Kas Kecil", "ASSET", parent="1-1100"),
            acc("1-1000", "Aset Lancar", "ASSET", group=True)]
    tree = coa.build_tree(rows)
    seen = []

    def walk(ns):
        for n in ns:
            seen.append(n["code"])
            walk(n["children"])
    walk(tree)
    assert sorted(seen) == ["1-1000", "1-1100", "1-1101"]
