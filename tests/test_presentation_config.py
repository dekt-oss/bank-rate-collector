"""화면 계약 설정 (v4 §9.1).

이 파일은 코드가 아니라 YAML이라 오타가 조용히 지나간다. `savings_bank`를
`saving_bank`로 적으면 저축은행이 메인 표에서 통째로 사라지는데, 어디서도
에러가 안 난다 — 그냥 안 나온다.

그래서 값이 실재하는 열거형인지 여기서 잡는다.
"""

from pathlib import Path

import pytest
import yaml

from rate_monitor.domain.enums import Sector

CONFIG = Path(__file__).resolve().parents[1] / "config" / "presentation.yaml"


@pytest.fixture(scope="module")
def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_every_sector_name_actually_exists(config: dict) -> None:
    """오타가 여기서 걸린다. 안 걸리면 화면에서 업권이 사라진 뒤에 안다."""
    known = {s.value for s in Sector}
    for key in ("main_sectors", "reference_sectors"):
        unknown = set(config[key]) - known
        assert not unknown, f"{key}에 없는 업권: {unknown} (가능: {sorted(known)})"


def test_main_and_reference_do_not_overlap(config: dict) -> None:
    """한 업권이 메인이면서 참고일 수 없다. 겹치면 같은 값이 두 번 보인다."""
    assert not set(config["main_sectors"]) & set(config["reference_sectors"])


def test_the_main_sectors_are_the_ones_v4_names(config: dict) -> None:
    """v4 §1.1의 넷 + 시중은행 (§6.4 정정). 순서는 상관없다."""
    assert set(config["main_sectors"]) == {
        Sector.SAVINGS_BANK, Sector.KFCC, Sector.NH_LOCAL, Sector.CU, Sector.BANK
    }


def test_commercial_banks_are_in_the_main_table_by_explicit_decision(
    config: dict,
) -> None:
    """v4 §6.4 정정 (2026-08-06) — 사용자가 메인에 넣기로 정했다.

    한때 §17이 이것을 금지했다. 금지의 핵심은 "**자동** 혼합"이었고, 명시적
    결정은 자동이 아니다. 대신 조건이 붙는다 — 전국 공시 배지를 함께 보여야
    한다. 배지 쪽은 `test_site_ui_v4`가 지킨다.

    이 테스트가 실패하면 설정이 되돌아간 것이다. 되돌리려면 v4 §6.4의 정정
    절부터 고쳐야 한다.
    """
    assert Sector.BANK in config["main_sectors"]
    assert Sector.BANK not in config["reference_sectors"]


def test_every_sector_is_placed_somewhere(config: dict) -> None:
    """새 업권을 enum에 넣고 여기 안 적으면 화면에 영영 안 나온다.

    새 업권이 생기면 이 테스트가 실패해서, 메인인지 참고인지 정하게 만든다.
    """
    placed = set(config["main_sectors"]) | set(config["reference_sectors"])
    assert {s.value for s in Sector} == placed
