from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_config_does_not_store_real_api_keys() -> None:
    config_source = (PROJECT_ROOT / "backend" / "config.py").read_text(encoding="utf-8")
    deploy_source = (PROJECT_ROOT / "deploy_and_run.sh").read_text(encoding="utf-8")
    legacy_ark_alias = "VOLCENGINE" + "_ARK_API_KEY"

    assert "sk-" not in config_source
    assert "ark-" not in config_source
    assert "sk-" not in deploy_source
    assert "ark-" not in deploy_source
    assert 'DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")' in config_source
    assert 'ARK_API_KEY="${ARK_API_KEY:?请先在环境变量中设置 ARK_API_KEY}"' in deploy_source
    assert legacy_ark_alias not in deploy_source
    assert 'DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"' in deploy_source


def test_default_thumbnail_dir_lives_outside_project_cache() -> None:
    config_source = (PROJECT_ROOT / "backend" / "config.py").read_text(encoding="utf-8")
    pipeline_source = (PROJECT_ROOT / "run_index_pipeline.py").read_text(encoding="utf-8")
    ark_main_source = (PROJECT_ROOT / "backend" / "ark_main.py").read_text(encoding="utf-8")

    assert 'LIMB_THUMBNAIL_DIR = os.environ.get("LIMB_THUMBNAIL_DIR", os.path.expanduser("~/.cache/local-photo-model/thumbnails"))' in config_source
    assert '".cache/thumbnails"' not in pipeline_source
    assert '".cache/thumbnails"' not in ark_main_source


def test_volcengine_ark_api_key_alias_is_removed_from_runtime_code() -> None:
    legacy_ark_alias = "VOLCENGINE" + "_ARK_API_KEY"
    runtime_files = [
        PROJECT_ROOT / "backend" / "ark_index_engine.py",
        PROJECT_ROOT / "tests" / "test_ark_connectivity.py",
        PROJECT_ROOT / "start_workspace.sh",
        PROJECT_ROOT / "start_full_index.sh",
    ]

    for path in runtime_files:
        assert legacy_ark_alias not in path.read_text(encoding="utf-8")
