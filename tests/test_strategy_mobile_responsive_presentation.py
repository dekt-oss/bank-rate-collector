from rate_monitor.services.strategy_mobile_responsive_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_mobile_responsive,
)


def _strategy_html() -> str:
    return (
        "<html><head></head><body>"
        '<section id="market-scope"></section>'
        '<section id="planning-zone"></section>'
        '<details class="decision-model-evidence" open></details>'
        "</body></html>"
    )


def test_strategy_mobile_layer_is_strategy_only_and_idempotent() -> None:
    search = "<html><head></head><body><main>search</main></body></html>"
    assert inject_strategy_mobile_responsive(search) == search

    rendered = inject_strategy_mobile_responsive(_strategy_html())
    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert inject_strategy_mobile_responsive(rendered) == rendered


def test_strategy_mobile_layer_removes_known_fixed_width_regressions() -> None:
    rendered = inject_strategy_mobile_responsive(_strategy_html())

    assert '#trend-chart{display:block;width:100%!important' in rendered
    assert '.pref-intel-table{width:100%!important;min-width:0!important' in rendered
    assert '.funding-position-table{width:100%!important;min-width:0!important' in rendered
    assert '.workspace-decision .simform>*{min-width:0;max-width:100%}' in rendered
    assert '.workspace-decision .simrow{grid-template-columns:1fr}' in rendered


def test_model_evidence_defaults_to_collapsed() -> None:
    rendered = inject_strategy_mobile_responsive(_strategy_html())
    assert 'evidence.removeAttribute("open")' in rendered
