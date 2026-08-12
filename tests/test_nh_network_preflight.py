from rate_monitor.nh_network_preflight import classify_target


def test_ready_when_any_resolved_endpoint_completes_tls() -> None:
    dns = {"ok": True, "ipv4": ["1.2.3.4"], "ipv6": []}
    endpoints = [
        {"ip": "1.2.3.4", "tcp_ok": True, "tls_ok": True},
    ]
    assert classify_target(dns, endpoints) == (True, "READY")


def test_dns_failure_is_not_admitted() -> None:
    assert classify_target({"ok": False}, []) == (False, "DNS_FAIL")


def test_tcp_refusal_is_retryable_network_classification() -> None:
    dns = {"ok": True, "ipv4": ["1.2.3.4"], "ipv6": []}
    endpoints = [
        {"ip": "1.2.3.4", "tcp_ok": False, "tls_ok": False},
    ]
    assert classify_target(dns, endpoints) == (False, "TCP_CONNECT_FAIL")


def test_tls_failure_is_distinguished_from_tcp_failure() -> None:
    dns = {"ok": True, "ipv4": ["1.2.3.4"], "ipv6": []}
    endpoints = [
        {"ip": "1.2.3.4", "tcp_ok": True, "tls_ok": False},
    ]
    assert classify_target(dns, endpoints) == (False, "TLS_FAIL")


def test_auxiliary_probe_failures_do_not_participate_in_admission() -> None:
    # classify_target intentionally receives only NH target evidence. A failed
    # ipify/control/IMDS lookup must not discard a runner whose NH TLS path works.
    dns = {"ok": True, "ipv4": ["1.2.3.4"], "ipv6": []}
    endpoints = [
        {"ip": "1.2.3.4", "tcp_ok": True, "tls_ok": True},
    ]
    assert classify_target(dns, endpoints)[0] is True
