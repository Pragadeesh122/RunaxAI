"""Guard against drift between the compose-mounted Grafana assets and the
copies packaged into the Helm chart.

Grafana dashboards and alert rules live canonically in
monitoring/grafana/provisioning/ (mounted by docker compose). Helm's
.Files.Get can only read files inside the chart root, so the chart carries
copies under helm/agenticrag/files/grafana/. If someone edits one side and
forgets the other, prod and local Grafana silently diverge — this test makes
that a CI failure instead.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_DASHBOARDS = REPO_ROOT / "monitoring/grafana/provisioning/dashboards"
COMPOSE_ALERTING = REPO_ROOT / "monitoring/grafana/provisioning/alerting"
CHART_DASHBOARDS = REPO_ROOT / "helm/agenticrag/files/grafana/dashboards"
CHART_ALERTING = REPO_ROOT / "helm/agenticrag/files/grafana/alerting"


def _json_names(directory: Path) -> set[str]:
    return {p.name for p in directory.glob("*.json")}


def test_dashboard_sets_match():
    assert _json_names(COMPOSE_DASHBOARDS) == _json_names(CHART_DASHBOARDS), (
        "Dashboard file sets differ between monitoring/grafana/provisioning/"
        "dashboards and helm/agenticrag/files/grafana/dashboards — copy the "
        "missing/renamed file to the other side."
    )


@pytest.mark.parametrize(
    "name", sorted(_json_names(COMPOSE_DASHBOARDS) | _json_names(CHART_DASHBOARDS))
)
def test_dashboard_contents_match(name: str):
    compose_file = COMPOSE_DASHBOARDS / name
    chart_file = CHART_DASHBOARDS / name
    assert compose_file.exists() and chart_file.exists()
    assert compose_file.read_bytes() == chart_file.read_bytes(), (
        f"{name} differs between the compose and Helm copies — sync them "
        f"(cp {compose_file.relative_to(REPO_ROOT)} "
        f"{chart_file.relative_to(REPO_ROOT)} or vice versa)."
    )


@pytest.mark.parametrize(
    "name", sorted(_json_names(COMPOSE_DASHBOARDS) | _json_names(CHART_DASHBOARDS))
)
def test_dashboard_is_valid_json(name: str):
    for base in (COMPOSE_DASHBOARDS, CHART_DASHBOARDS):
        path = base / name
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))


def test_alerting_rules_match():
    compose_files = {p.name for p in COMPOSE_ALERTING.glob("*.yml")}
    chart_files = {p.name for p in CHART_ALERTING.glob("*.yml")}
    assert compose_files == chart_files, (
        "Alerting rule file sets differ between monitoring/grafana/"
        "provisioning/alerting and helm/agenticrag/files/grafana/alerting."
    )
    for name in compose_files:
        assert (COMPOSE_ALERTING / name).read_bytes() == (
            CHART_ALERTING / name
        ).read_bytes(), f"{name} differs between the compose and Helm copies — sync them."
