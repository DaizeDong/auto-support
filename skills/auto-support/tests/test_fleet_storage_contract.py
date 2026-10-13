"""Generated discovery regressions: doctor and runtime share one companion selection."""
import runtime_data as runtime


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
