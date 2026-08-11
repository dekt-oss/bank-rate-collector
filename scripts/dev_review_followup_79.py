from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


path = Path("src/rate_monitor/collectors/nh_local/adapter.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "        retry_count: int,\n    ) -> None:\n"
    "        self.code = code\n"
    "        self.phase = phase\n"
    "        self.screen = screen\n"
    "        self.attempt = attempt\n"
    "        self.max_attempts = max_attempts\n"
    "        self.cause = cause\n"
    "        self.retry_count = retry_count\n"
    "        super().__init__(\n"
    "            f\"{code}: phase={phase} screen={screen} attempt={attempt}/{max_attempts} \"\n"
    "            f\"retries={retry_count} cause={type(cause).__name__}: {cause}\"\n"
    "        )",
    "        retry_count: int,\n"
    "        failure_reasons: dict[str, int] | None = None,\n"
    "    ) -> None:\n"
    "        self.code = code\n"
    "        self.phase = phase\n"
    "        self.screen = screen\n"
    "        self.attempt = attempt\n"
    "        self.max_attempts = max_attempts\n"
    "        self.cause = cause\n"
    "        self.retry_count = retry_count\n"
    "        self.failure_reasons = dict(failure_reasons or {})\n"
    "        reasons = \", \\.join(\n"
    "            f\"{reason} {count}\" for reason, count in sorted(self.failure_reasons.items())\n"
    "        ) or \"none\"\n"
    "        super().__init__(\n"
    "            f\"{code}: phase={phase} screen={screen} attempt={attempt}/{max_attempts} \"\n"
    "            f\"retries={retry_count} failures={reasons} \"\n"
    "            f\"cause={type(cause).__name__}: {cause}\"\n"
    "        )",
    "failure exception telemetry",
)

text = replace_once(
    text,
    "    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):\n"
    "        return \"NETWORK_TIMEOUT\"\n"
    "    if isinstance(exc, httpx.RemoteProtocolError):\n"
    "        return \"NETWORK_PROTOCOL\"",
    "    if isinstance(\n"
    "        exc,\n"
    "        (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout),\n"
    "    ):\n"
    "        return \"NETWORK_TIMEOUT\"\n"
    "    if isinstance(exc, (httpx.ReadError, httpx.WriteError)):\n"
    "        return \"NETWORK_IO\"\n"
    "    if isinstance(exc, httpx.RemoteProtocolError):\n"
    "        return \"NETWORK_PROTOCOL\"",
    "expanded failure taxonomy",
)
text = replace_once(
    text,
    '    return "NETWORK_PROTOCOL"\n\n\nclass NhLocalAdapter:',
    '    return "NETWORK_UNKNOWN"\n\n\nclass NhLocalAdapter:',
    "unknown taxonomy fallback",
)

text = replace_once(
    text,
    "    def _reserve_retry(\n",
    "    def _failure_reasons_with(self, code: str) -> dict[str, int]:\n"
    "        reasons = Counter(self._retry_reasons)\n"
    "        reasons[code] += 1\n"
    "        return dict(sorted(reasons.items()))\n\n"
    "    def _reserve_retry(\n",
    "failure reason helper",
)

text = replace_once(
    text,
    "                retry_count=self._retry_count,\n"
    "            ) from cause\n"
    "        self._retry_count += 1",
    "                retry_count=self._retry_count,\n"
    "                failure_reasons=self._failure_reasons_with(code),\n"
    "            ) from cause\n"
    "        self._retry_count += 1",
    "retry budget telemetry",
)

text = replace_once(
    text,
    "            except (\n"
    "                httpx.ConnectError,\n"
    "                httpx.ConnectTimeout,\n"
    "                httpx.ReadTimeout,\n"
    "                httpx.RemoteProtocolError,\n"
    "            ) as exc:",
    "            except (\n"
    "                httpx.ConnectError,\n"
    "                httpx.ConnectTimeout,\n"
    "                httpx.ReadTimeout,\n"
    "                httpx.WriteTimeout,\n"
    "                httpx.PoolTimeout,\n"
    "                httpx.ReadError,\n"
    "                httpx.WriteError,\n"
    "                httpx.RemoteProtocolError,\n"
    "            ) as exc:",
    "expanded retry exceptions",
)

text = replace_once(
    text,
    "                    retry_count=self._retry_count,\n"
    "                ) from failure\n\n"
    "            self._reserve_retry(",
    "                    retry_count=self._retry_count,\n"
    "                    failure_reasons=self._failure_reasons_with(code),\n"
    "                ) from failure\n\n"
    "            self._reserve_retry(",
    "terminal failure telemetry",
)
path.write_text(text, encoding="utf-8")


path = Path("tests/test_nh_local_retry.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    NhRequestFailure,\n)",
    "    NhRequestFailure,\n    _failure_code,\n)",
    "retry test import",
)
text = replace_once(
    text,
    "    assert adapter._retry_count == 3\n",
    "    assert adapter._retry_count == 3\n"
    "    assert caught.value.failure_reasons == {\"NETWORK_TIMEOUT\": 4}\n"
    "    assert \"failures=NETWORK_TIMEOUT 4\" in str(caught.value)\n",
    "failure telemetry assertion",
)
anchor = '\n\n@pytest.mark.parametrize("status", [403, 429])\n'
addition = '''\n\n@pytest.mark.parametrize(\n    ("error_type", "expected_code"),\n    [\n        (httpx.ReadError, "NETWORK_IO"),\n        (httpx.WriteError, "NETWORK_IO"),\n        (httpx.WriteTimeout, "NETWORK_TIMEOUT"),\n        (httpx.PoolTimeout, "NETWORK_TIMEOUT"),\n    ],\n)\ndef test_additional_transport_failures_retry_then_succeed(\n    error_type: type[httpx.RequestError], expected_code: str\n) -> None:\n    calls = 0\n    sleep = SleepRecorder()\n\n    def handler(request: httpx.Request) -> httpx.Response:\n        nonlocal calls\n        calls += 1\n        if calls == 1:\n            raise error_type("temporary transport failure", request=request)\n        return httpx.Response(200, content=b"detail", request=request)\n\n    adapter = NhLocalAdapter(sleep=sleep)\n    assert _run_get(adapter, handler, phase="detail") == b"detail"\n    assert calls == 2\n    assert sleep.delays == [4.0]\n    assert adapter._retry_reasons == {expected_code: 1}\n\n\ndef test_unknown_failure_taxonomy_does_not_mislabel_as_protocol() -> None:\n    assert _failure_code(RuntimeError("unexpected")) == "NETWORK_UNKNOWN"\n'''
text = replace_once(text, anchor, addition + anchor, "extra transport retry tests")
path.write_text(text, encoding="utf-8")


path = Path("tests/test_repeat_guard.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        assert "self.fetch_note = guard.summary()" in source, f"{name}이 요약을 안 남긴다"',
    '        assert "guard.summary()" in source, f"{name}이 되풀이 요약을 안 만든다"\n'
    '        assert "self.fetch_note" in source, f"{name}이 실행 메모를 안 남긴다"',
    "repeat guard semantic source contract",
)
path.write_text(text, encoding="utf-8")
