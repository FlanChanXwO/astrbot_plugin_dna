"""客户端更新 Source smoke 脚本私有 helper 测试。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts.smoke_client_update_sources import _run_smoke
from src.modules.client_updates import (
    CLIENT_UPDATE_REGISTRY,
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateFailureKind,
    ClientUpdateTransportError,
)


@dataclass
class FakeTransport:
    """记录 smoke 调用，确保不传 baseline 触发补丁清单读取。"""

    results: dict[str, ClientSourceObservation | ClientUpdateTransportError]
    calls: list[tuple[str, ClientSourceVersion | None]] = field(default_factory=list)

    async def get_observation(
        self,
        source_id: str,
        *,
        baseline: ClientSourceVersion | None = None,
    ) -> ClientSourceObservation:
        self.calls.append((source_id, baseline))
        result = self.results[source_id]
        if isinstance(result, ClientUpdateTransportError):
            raise result
        return result


def _observation(source_id: str, revision_id: str) -> ClientSourceObservation:
    current = ClientSourceVersion(
        source_id=source_id,
        version_text="1.2.3.4",
        revision_id=revision_id,
    )
    return ClientSourceObservation(
        current=current,
        observed_versions=(current,),
        history_complete=True,
        added_size_bytes=None,
    )


@pytest.mark.asyncio
async def test_source_smoke_reads_every_registry_source_without_baseline_or_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    results = {
        source.source_id: _observation(source.source_id, str(index))
        for index, source in enumerate(CLIENT_UPDATE_REGISTRY.sources, start=1)
    }
    transport = FakeTransport(results)

    passed = await _run_smoke(transport)

    output = capsys.readouterr().out.splitlines()
    assert passed
    assert transport.calls == [
        (source.source_id, None) for source in CLIENT_UPDATE_REGISTRY.sources
    ]
    assert output == [
        f"OK source={source.source_id} provider={source.provider_kind.value} "
        f"revision={index} version=1.2.3.4"
        for index, source in enumerate(CLIENT_UPDATE_REGISTRY.sources, start=1)
    ]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_source_smoke_classifies_failure_and_formats_only_safe_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = CLIENT_UPDATE_REGISTRY.sources[0]
    transport = FakeTransport(
        {
            candidate.source_id: (
                ClientUpdateTransportError(
                    ClientUpdateFailureKind.NETWORK,
                    resource="VersionList",
                    detail=(
                        "https://secret.example/VersionList.json body=secret-token"
                    ),
                )
                if candidate.source_id == source.source_id
                else _observation(candidate.source_id, "100")
            )
            for candidate in CLIENT_UPDATE_REGISTRY.sources
        }
    )

    passed = await _run_smoke(transport)
    rendered = capsys.readouterr().out.splitlines()[0]

    assert not passed
    assert rendered == (
        "FAIL source=cn-official-pc-manifest provider=manifest_cdn "
        "kind=network resource=VersionList status=none"
    )
    assert "secret.example" not in rendered
    assert "secret-token" not in rendered
