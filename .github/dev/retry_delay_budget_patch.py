from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


ADAPTERS = [
    (
        "src/rate_monitor/collectors/kfcc/adapter.py",
        "KfccRequestFailure",
        "request_label",
        "request_label=request_label",
        '"KFCC retry source_id=%s phase=%s request=%s attempt=%d max_attempts=%d "\n'
        '                "error_class=%s http_status=%s retry_delay=%.1f",',
        'self.source_id,\n                phase,\n                request_label,',
    ),
    (
        "src/rate_monitor/collectors/nh_local/adapter.py",
        "NhRequestFailure",
        "screen",
        "screen=screen",
        '"NH retry source_id=%s phase=%s screen=%s attempt=%d max_attempts=%d "\n'
        '                "error_class=%s http_status=%s retry_delay=%.1f",',
        'self.source_id,\n                phase,\n                screen,',
    ),
]

for path, exc_name, label_param, label_kw, log_old, log_args in ADAPTERS:
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    old = "RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})\nMAX_TOTAL_RETRIES = 50\n"
    new = (
        "RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})\n"
        "MAX_TOTAL_RETRIES = 50\n"
        "# 07:30 normal 목표의 관측 최소 여유가 약 10분이었다. retry backoff가\n"
        "# 그 여유를 25분까지 잠식하지 않도록, 실제로 sleep하는 누적 추가 대기를\n"
        "# 10분으로 별도 제한한다. 요청 자체 timeout은 기존 per-request 제한을 따른다.\n"
        "MAX_TOTAL_RETRY_DELAY_SECONDS = 10 * 60.0\n"
    )
    if text.count(old) != 1:
        raise SystemExit(f"{path}: constants marker mismatch")
    text = text.replace(old, new, 1)

    old = "        self._retry_count = 0\n        self._retry_reasons: Counter[str] = Counter()\n"
    new = (
        "        self._retry_count = 0\n"
        "        self._retry_delay_seconds = 0.0\n"
        "        self._retry_reasons: Counter[str] = Counter()\n"
    )
    if text.count(old) != 1:
        raise SystemExit(f"{path}: init marker mismatch")
    text = text.replace(old, new, 1)

    old = "    def _reset_retry_state(self) -> None:\n        self._retry_count = 0\n        self._retry_reasons.clear()\n"
    new = (
        "    def _reset_retry_state(self) -> None:\n"
        "        self._retry_count = 0\n"
        "        self._retry_delay_seconds = 0.0\n"
        "        self._retry_reasons.clear()\n"
    )
    if text.count(old) != 1:
        raise SystemExit(f"{path}: reset marker mismatch")
    text = text.replace(old, new, 1)

    if path.endswith("kfcc/adapter.py"):
        sig_old = '''        max_attempts: int,\n        cause: Exception,\n    ) -> None:\n        if self._retry_count >= MAX_TOTAL_RETRIES:\n            raise KfccRequestFailure(\n                "RETRY_BUDGET_EXHAUSTED",\n                phase=phase,\n                request_label=request_label,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=cause,\n                retry_count=self._retry_count,\n                failure_reasons=self._failure_reasons_with(code),\n            ) from cause\n        self._retry_count += 1\n        self._retry_reasons[code] += 1\n'''
        sig_new = '''        max_attempts: int,\n        cause: Exception,\n        delay: float,\n    ) -> None:\n        if self._retry_count >= MAX_TOTAL_RETRIES:\n            raise KfccRequestFailure(\n                "RETRY_BUDGET_EXHAUSTED",\n                phase=phase,\n                request_label=request_label,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=cause,\n                retry_count=self._retry_count,\n                failure_reasons=self._failure_reasons_with(code),\n            ) from cause\n        if self._retry_delay_seconds + delay > MAX_TOTAL_RETRY_DELAY_SECONDS:\n            raise KfccRequestFailure(\n                "RETRY_DELAY_BUDGET_EXHAUSTED",\n                phase=phase,\n                request_label=request_label,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=cause,\n                retry_count=self._retry_count,\n                failure_reasons=self._failure_reasons_with(code),\n            ) from cause\n        self._retry_count += 1\n        self._retry_delay_seconds += delay\n        self._retry_reasons[code] += 1\n'''
    else:
        sig_old = '''        max_attempts: int,\n        cause: Exception,\n    ) -> None:\n        if self._retry_count >= MAX_TOTAL_RETRIES:\n            raise NhRequestFailure(\n                "RETRY_BUDGET_EXHAUSTED",\n                phase=phase,\n                screen=screen,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=cause,\n                retry_count=self._retry_count,\n                failure_reasons=self._failure_reasons_with(code),\n            ) from cause\n        self._retry_count += 1\n        self._retry_reasons[code] += 1\n'''
        sig_new = '''        max_attempts: int,\n        cause: Exception,\n        delay: float,\n    ) -> None:\n        if self._retry_count >= MAX_TOTAL_RETRIES:\n            raise NhRequestFailure(\n                "RETRY_BUDGET_EXHAUSTED",\n                phase=phase,\n                screen=screen,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=cause,\n                retry_count=self._retry_count,\n                failure_reasons=self._failure_reasons_with(code),\n            ) from cause\n        if self._retry_delay_seconds + delay > MAX_TOTAL_RETRY_DELAY_SECONDS:\n            raise NhRequestFailure(\n                "RETRY_DELAY_BUDGET_EXHAUSTED",\n                phase=phase,\n                screen=screen,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=cause,\n                retry_count=self._retry_count,\n                failure_reasons=self._failure_reasons_with(code),\n            ) from cause\n        self._retry_count += 1\n        self._retry_delay_seconds += delay\n        self._retry_reasons[code] += 1\n'''
    if text.count(sig_old) != 1:
        raise SystemExit(f"{path}: reserve retry marker mismatch")
    text = text.replace(sig_old, sig_new, 1)

    if path.endswith("kfcc/adapter.py"):
        call_old = '''            self._reserve_retry(\n                code=code,\n                phase=phase,\n                request_label=request_label,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=failure,\n            )\n            delay = REQUEST_INTERVAL_SECONDS + backoffs[attempt - 1]\n'''
        call_new = '''            delay = REQUEST_INTERVAL_SECONDS + backoffs[attempt - 1]\n            self._reserve_retry(\n                code=code,\n                phase=phase,\n                request_label=request_label,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=failure,\n                delay=delay,\n            )\n'''
    else:
        call_old = '''            self._reserve_retry(\n                code=code,\n                phase=phase,\n                screen=screen,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=failure,\n            )\n            delay = REQUEST_INTERVAL_SECONDS + backoffs[attempt - 1]\n'''
        call_new = '''            delay = REQUEST_INTERVAL_SECONDS + backoffs[attempt - 1]\n            self._reserve_retry(\n                code=code,\n                phase=phase,\n                screen=screen,\n                attempt=attempt,\n                max_attempts=max_attempts,\n                cause=failure,\n                delay=delay,\n            )\n'''
    if text.count(call_old) != 1:
        raise SystemExit(f"{path}: reserve call marker mismatch")
    text = text.replace(call_old, call_new, 1)

    log_new = log_old[:-2] + ' cumulative_retry_delay=%.1f",'
    if text.count(log_old) != 1:
        raise SystemExit(f"{path}: log marker mismatch")
    text = text.replace(log_old, log_new, 1)
    old_args = log_args + '''\n                attempt,\n                max_attempts,\n                code,\n                http_status if http_status is not None else "-",\n                delay,\n'''
    new_args = log_args + '''\n                attempt,\n                max_attempts,\n                code,\n                http_status if http_status is not None else "-",\n                delay,\n                self._retry_delay_seconds,\n'''
    if text.count(old_args) != 1:
        raise SystemExit(f"{path}: log args marker mismatch")
    text = text.replace(old_args, new_args, 1)

    p.write_text(text, encoding="utf-8")

# Retry tests: budget stops before the next sleep and preserves no-retry contracts.
for path, adapter, failure, max_import, phase in [
    ("tests/test_kfcc_retry.py", "KfccAdapter", "KfccRequestFailure", "MAX_TOTAL_RETRIES", "rate"),
    ("tests/test_nh_local_retry.py", "NhLocalAdapter", "NhRequestFailure", "MAX_TOTAL_RETRIES", "detail"),
]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    old = f"    {max_import},\n"
    new = f"    MAX_TOTAL_RETRY_DELAY_SECONDS,\n    {max_import},\n"
    if text.count(old) != 1:
        raise SystemExit(f"{path}: import marker mismatch")
    text = text.replace(old, new, 1)

    marker = "\n\ndef test_unknown_failure_taxonomy_does_not_mislabel_as_protocol() -> None:\n"
    test = f'''\n\ndef test_retry_delay_budget_stops_before_next_sleep() -> None:\n    calls = 0\n    sleep = SleepRecorder()\n\n    def handler(request: httpx.Request) -> httpx.Response:\n        nonlocal calls\n        calls += 1\n        raise httpx.ConnectError("still down", request=request)\n\n    adapter = {adapter}(sleep=sleep)\n    adapter._retry_delay_seconds = MAX_TOTAL_RETRY_DELAY_SECONDS - 3.0\n\n    with pytest.raises({failure}) as caught:\n        _run_get(adapter, handler, phase="{phase}")\n\n    assert caught.value.code == "RETRY_DELAY_BUDGET_EXHAUSTED"\n    assert calls == 1\n    assert sleep.delays == []\n    assert adapter._retry_count == 0\n    assert adapter._retry_delay_seconds == MAX_TOTAL_RETRY_DELAY_SECONDS - 3.0\n\n'''
    if marker not in text:
        raise SystemExit(f"{path}: insertion marker mismatch")
    text = text.replace(marker, test + marker, 1)
    p.write_text(text, encoding="utf-8")

# Small contract note; this PR intentionally does not refactor the duplicated retry engines.
doc = Path("docs/specs/20260811-retry-delay-budget.md")
doc.write_text(
    '''# NH/KFCC Retry Delay Budget — 2026-08-11\n\n## Decision\n\nNH와 KFCC의 기존 `MAX_TOTAL_RETRIES=50`은 유지하되, 실제 retry sleep에 쓰는\n누적 추가 대기를 source run당 **600초(10분)** 로 별도 제한한다.\n\n## Evidence\n\n2026-08-11 리뷰에서 이전 scheduled run의 queue delay와 runtime을 현재 00:17/04:17\n스케줄에 대입했을 때 07:30 normal 목표의 관측 최소 여유는 약 10분이었다. 기존\n50회 횟수 예산만으로는 KFCC retry backoff가 약 25분까지 늘 수 있다.\n\n600초는 08:00 hard deadline을 보장한다는 뜻이 아니다. GitHub queue와 원천 응답시간은\n통제할 수 없다. 이 상한은 **collector가 스스로 추가하는 retry sleep**이 관측된 normal\nmargin보다 커지는 것을 막는다. per-request connect/read timeout은 기존 값을 유지한다.\n\n## Preserved contracts\n\n- GET only\n- 기존 retryable transport exception과 500/502/503/504만 재시도\n- 400/403/429/block marker는 즉시 중단, 우회 없음\n- 정상 1초 pacing 유지\n- retry count 50 상한 유지\n- NH/KFCC retry 구현 공통화는 이번 PR 범위 밖\n\n## Failure taxonomy\n\n누적 다음 sleep이 600초를 넘기면 `RETRY_DELAY_BUDGET_EXHAUSTED`로 종료한다.\n해당 sleep은 실행하지 않으며 retry count도 증가시키지 않는다.\n''',
    encoding="utf-8",
)
