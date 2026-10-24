"""Load models.yaml + rules.yaml with fail-fast validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import load_yaml


@dataclass
class RoleConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str
    max_tokens: int = 1024
    timeout: int = 120
    image_detail: str = "low"
    training_data_risk: bool = False


@dataclass
class AppConfig:
    root: Path  # directory holding models.yaml + rules.yaml
    roles: dict[str, RoleConfig] = field(default_factory=dict)
    rules: dict = field(default_factory=dict)

    @property
    def rules_path(self) -> Path:
        return self.root / "rules.yaml"

    @property
    def models_path(self) -> Path:
        return self.root / "models.yaml"


DEFAULT_IMAGE_MODELS_HINT = (
    "frame_triage/escalation roles must point at models with image input support"
)


def load_config(config_dir: str | Path) -> AppConfig:
    root = Path(config_dir)
    models_p = root / "models.yaml"
    rules_p = root / "rules.yaml"
    if not rules_p.exists():
        raise FileNotFoundError(f"missing rules.yaml: {rules_p}")
    rules = load_yaml(rules_p) or {}
    roles: dict[str, RoleConfig] = {}
    if models_p.exists():
        models = load_yaml(models_p) or {}
        for name, r in (models.get("roles") or {}).items():
            roles[name] = RoleConfig(
                name=name,
                base_url=r.get("base_url", ""),
                model=r.get("model", ""),
                api_key_env=r.get("api_key_env", ""),
                max_tokens=int(r.get("max_tokens", 1024)),
                timeout=int(r.get("timeout", 120)),
                image_detail=str(r.get("image_detail", "low")),
                training_data_risk=bool(r.get("training_data_risk", False)),
            )
    cfg = AppConfig(root=root, roles=roles, rules=rules)
    return cfg


def require_vision_role(cfg: AppConfig, role: str) -> RoleConfig:
    if role not in cfg.roles:
        raise RuntimeError(
            f"model role '{role}' is not configured in {cfg.models_path}. {DEFAULT_IMAGE_MODELS_HINT}."
        )
    rc = cfg.roles[role]
    if not rc.model or not rc.base_url:
        raise RuntimeError(
            f"model role '{role}' is missing base_url/model in {cfg.models_path}."
        )
    return rc
