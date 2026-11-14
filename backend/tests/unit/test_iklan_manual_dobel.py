"""Input biaya iklan MANUAL dobel ditolak (temuan Marketing 14 Nov 2026) — routes.marketing_ads_routes.

Dulu yang ditolak hanya bentrok dengan jalur impor (M-09). Dua entri manual dengan toko + tanggal +
saluran iklan + nama kampanye sama lolos dan biayanya terjumlah dua kali di ROAS & anggaran.
"""
import pytest
from fastapi import HTTPException

from _mkt_uji import DB, Req, acc, patch_route, run  # noqa: E402

SHP = "SHP-01"


@pytest.fixture
def ma(monkeypatch):
    import routes.marketing_ads_routes as mod
    d = DB()
    d.marketing_platform_accounts.docs.append(acc(SHP, platform="shopee"))
    patch_route(monkeypatch, mod, d)
    mod._uji_db = d
    return mod


def _baru(ma, **kw):
    data = {"account_id": SHP, "date": "2026-11-10", "campaign_name": "Promo 11.11", "spend": 50_000,
            "ad_platform": "shopee_ads"}
    data.update(kw)
    return run(ma.create_ads_entry(ma.AdsEntryIn(**data), Req()))["data"]


def test_entri_manual_kembar_ditolak_tanpa_peduli_huruf_dan_spasi(ma):
    _baru(ma)
    with pytest.raises(HTTPException) as e:
        _baru(ma, campaign_name="  promo   11.11 ", spend=20_000)
    assert e.value.status_code == 409
    pesan = e.value.detail
    assert "Promo 11.11" in pesan and "10 Nov 2026" in pesan and "Ubah baris yang sudah ada" in pesan
    assert "dua kali" in pesan and "_" not in pesan
    assert len(ma._uji_db.marketing_ads_data.docs) == 1


def test_beda_tanggal_saluran_atau_kampanye_tetap_boleh(ma):
    _baru(ma)
    _baru(ma, date="2026-11-11")
    _baru(ma, ad_platform="meta_ads")
    _baru(ma, campaign_name="Promo 12.12")
    assert len(ma._uji_db.marketing_ads_data.docs) == 4


def test_ubah_baris_yang_sama_tidak_ditolak(ma):
    row = _baru(ma)
    out = run(ma.update_ads_entry(row["id"], ma.AdsEntryUpdate(date="2026-11-10", campaign_name="Promo 11.11",
                                                               ad_platform="shopee_ads", spend=75_000), Req()))
    assert out["data"]["spend"] == 75_000


def test_ubah_baris_menjadi_kembar_baris_lain_ditolak(ma):
    _baru(ma)
    lain = _baru(ma, campaign_name="Promo 12.12")
    with pytest.raises(HTTPException) as e:
        run(ma.update_ads_entry(lain["id"], ma.AdsEntryUpdate(campaign_name="PROMO 11.11"), Req()))
    assert e.value.status_code == 409 and "Promo 11.11" in e.value.detail


def test_kembar_lama_masih_bisa_diubah_angkanya(ma):
    """Data kembar yang sudah terlanjur ada tetap bisa dirapikan (angka diubah) tanpa ditolak."""
    _baru(ma)
    docs = ma._uji_db.marketing_ads_data.docs
    kembar = dict(docs[0], id="kembar-lama")
    docs.append(kembar)
    out = run(ma.update_ads_entry("kembar-lama", ma.AdsEntryUpdate(date="2026-11-10", campaign_name="Promo 11.11",
                                                                   spend=0), Req()))
    assert out["data"]["spend"] == 0


def test_baris_impor_tidak_dihitung_dobel_manual(ma):
    """Bentrok dengan impor tetap lewat aturan M-09 (pesan jalur lain), bukan aturan manual."""
    ma._uji_db.marketing_ads_data.docs.append({
        "id": "imp1", "account_id": SHP, "campaign_name": "Promo 11.11", "ad_platform": "shopee_ads",
        "_import_session_id": "s1", "_import_source_type": "ads", "date": "2026-11-10", "spend": 9_000})
    with pytest.raises(HTTPException) as e:
        _baru(ma)
    assert e.value.status_code == 409 and "jalur lain" in e.value.detail
