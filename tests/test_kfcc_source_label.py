"""KFCC 기술 경로명을 사용자 표시명과 분리한다."""

from pathlib import Path

from rate_monitor.collectors.kfcc.adapter import KfccAdapter

ROOT = Path(__file__).resolve().parents[1]
SITE = (ROOT / "web/templates/site.html").read_text(encoding="utf-8")


def test_kfcc_adapter_keeps_identity_but_uses_product_display_name() -> None:
    assert KfccAdapter.source_id == "kfcc"
    assert KfccAdapter.source_name == "새마을금고 예·적금 금리"
    assert KfccAdapter.base_reference == "kfcc.co.kr/map"


def test_kfcc_health_card_does_not_show_location_page_as_source_name() -> None:
    assert 'kfcc: "새마을금고 예·적금 금리"' in SITE
    assert "SOURCE_DISPLAY_NAME[s.source_id] || s.name || s.source_id" in SITE


def test_kfcc_footer_explains_the_official_location_and_rate_route() -> None:
    assert 'kfcc: ["새마을금고 공식 홈페이지 금고위치안내/금리조회", "지역은 점포 주소"]' in SITE
    assert 'kfcc: ["새마을금고 금고위치안내 · 금고별 금리"' not in SITE
