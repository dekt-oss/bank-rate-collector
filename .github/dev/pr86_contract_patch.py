from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: marker mismatch: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/rate_monitor/collectors/nh_local/resumable.py",
    '''        guard = self._guard_factory()
        self._replay_guard(guard, artifacts)
        if guard.tripped:
''',
    '''        guard = self._guard_factory()
        try:
            self._replay_guard(guard, artifacts)
        except CheckpointIncompatibleError as exc:
            self._seal_contract_failure(service, manifest, exc)
            raise
        if guard.tripped:
''',
)

replace_once(
    "src/rate_monitor/collectors/nh_local/resumable.py",
    '''        except SourceBlockedError as exc:
            if buffer:
                manifest = service.flush(
                    manifest,
                    buffer,
                    guard_state=self._checkpoint_state(),
                )
            service.mark_terminal(
                manifest,
                status="blocked",
                reason_code="SOURCE_BLOCKED",
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
            raise
        except SchemaChangedError as exc:
''',
    '''        except SourceBlockedError as exc:
            if buffer:
                manifest = service.flush(
                    manifest,
                    buffer,
                    guard_state=self._checkpoint_state(),
                )
            service.mark_terminal(
                manifest,
                status="blocked",
                reason_code="SOURCE_BLOCKED",
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
            raise
        except CheckpointIncompatibleError as exc:
            self._seal_contract_failure(service, manifest, exc)
            raise
        except SchemaChangedError as exc:
''',
)

replace_once(
    "src/rate_monitor/collectors/nh_local/resumable.py",
    '''    def _build_plan(
        self,
        outlets,
        products: tuple[ProductType, ...],
''',
    '''    def _seal_contract_failure(
        self,
        service: ResumableAcquisitionService,
        manifest: AcquisitionManifest,
        exc: CheckpointIncompatibleError,
    ) -> None:
        """Seal same-session contract drift so workflow recovery cannot loop it."""
        try:
            service.mark_terminal(
                manifest,
                status="contract_failed",
                reason_code="ACQUISITION_CONTRACT_CHANGED",
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
        except CheckpointIncompatibleError:
            # Identity-level incompatibility can mean this manifest is not the active
            # session. In that case the common recovery decision itself fails closed.
            return

    def _build_plan(
        self,
        outlets,
        products: tuple[ProductType, ...],
''',
)

replace_once(
    "tests/test_nh_local_resumable.py",
    '''    monkeypatch.setattr(resumed, "_get", must_not_fetch_directory)
    with pytest.raises(CheckpointIncompatibleError, match="work_plan_hash"):
        _run(resumed, request)


def test_blocked_source_is_terminal_and_not_recoverable''',
    '''    monkeypatch.setattr(resumed, "_get", must_not_fetch_directory)
    with pytest.raises(CheckpointIncompatibleError, match="work_plan_hash"):
        _run(resumed, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "ACQUISITION_CONTRACT_CHANGED"


def test_blocked_source_is_terminal_and_not_recoverable''',
)
