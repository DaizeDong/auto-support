"""Generated storage/discovery regressions with synthetic publication metadata."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import pytest
import runtime_data as runtime


@pytest.fixture
def contract_storage(tmp_path, monkeypatch):
    root = tmp_path / 'companion'
    root.mkdir()
    storage = runtime._storage_api()
    api = SimpleNamespace(
        prove_private_companion=lambda path, visibility_map=None: SimpleNamespace(
            root=str(root), repositories=('example/synthetic-private',), signature='synthetic'),
        read_private_companion_git=lambda proof, *args: SimpleNamespace(
            returncode=1 if args[0] == 'check-ignore' else 0, stdout='a'*40))
    monkeypatch.setattr(storage, 'load_boundary', lambda: api)
    monkeypatch.setattr(runtime, '_storage_api', lambda: storage)
    monkeypatch.setattr(runtime, '_guard_base', lambda: root)
    monkeypatch.setattr(runtime, '_private_repo', lambda path: root)
    return root, storage


def test_state_writer_uses_declared_default_and_sidecars(contract_storage):
    root, _ = contract_storage
    assert runtime.state_path() == root / 'escalation_state.json'
    assert list(root.iterdir()) == []


def test_undeclared_state_fails_without_creating_parents(contract_storage):
    root, _ = contract_storage
    with pytest.raises(runtime.DataBoundaryError, match='artifact'):
        runtime.state_path('new-kind/state.json')
    assert list(root.iterdir()) == []


def test_incident_path_has_one_core_owner(contract_storage):
    root, storage = contract_storage
    admission = storage.authorize_artifact_write(runtime.REPO_ROOT, root, 'metrics/example/incidents.jsonl')
    assert admission.artifact_id == 'incident-records'
    assert not admission.path.exists()


def test_doctor_and_runtime_share_data_override(tmp_path, monkeypatch):
    root = tmp_path / 'companion'
    (root / 'data').mkdir(parents=True)
    monkeypatch.setenv('AUTO_SUPPORT_DATA_DIR', str(root / 'data'))
    monkeypatch.setenv('AUTO_SUPPORT_CONFIG', str(tmp_path / 'other'))
    assert runtime._guard_base(companion=True) == root
    assert runtime._guard_base() == root / 'data'


def test_doctor_explicit_selection_wins_over_data_override(tmp_path, monkeypatch):
    root = tmp_path / 'selected'
    root.mkdir()
    monkeypatch.setenv('AUTO_SUPPORT_DATA_DIR', str(tmp_path / 'missing'))
    assert runtime._guard_base(companion=True, override=str(root)) == root
