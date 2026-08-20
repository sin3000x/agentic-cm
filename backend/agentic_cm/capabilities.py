from __future__ import annotations

import argparse
import hashlib
import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


ASSET_KINDS = ("policy", "skill", "knowledge")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILTIN_ROOT = REPOSITORY_ROOT / "capabilities" / "builtin"
DEFAULT_LOCAL_ROOT = REPOSITORY_ROOT / ".agentic-cm" / "capabilities"


class CapabilityConfigurationError(ValueError):
    pass


class CapabilityConflictError(CapabilityConfigurationError):
    pass


@dataclass(frozen=True)
class AssetRef:
    kind: str
    id: str
    version: str
    digest: str
    source: str


@dataclass(frozen=True)
class CapabilityResolution:
    context: dict[str, str]
    policies: tuple[AssetRef, ...]
    skills: tuple[AssetRef, ...]
    knowledge: tuple[AssetRef, ...]
    compiled_policy: dict[str, Any]
    asset_payloads: dict[str, list[dict[str, Any]]]

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "context": deepcopy(self.context),
            "policies": [asdict(item) for item in self.policies],
            "skills": [asdict(item) for item in self.skills],
            "knowledge": [asdict(item) for item in self.knowledge],
            "compiled_policy": deepcopy(self.compiled_policy),
            "asset_payloads": deepcopy(self.asset_payloads),
        }


@dataclass(frozen=True)
class SkillPathDefinition:
    id: str
    title: str
    description: str
    skill_refs: tuple[AssetRef, ...]


@dataclass(frozen=True)
class _LoadedAsset:
    data: dict[str, Any]
    ref: AssetRef


class CapabilityRegistry:
    """Loads built-ins, then adds or intentionally replaces workspace-local assets."""

    def __init__(self, assets: dict[tuple[str, str], _LoadedAsset]) -> None:
        self._assets = assets

    @classmethod
    def from_directories(
        cls,
        builtin_root: str | Path = DEFAULT_BUILTIN_ROOT,
        local_root: str | Path | None = DEFAULT_LOCAL_ROOT,
    ) -> "CapabilityRegistry":
        merged: dict[tuple[str, str], _LoadedAsset] = {}
        builtin_path = Path(builtin_root)
        local_path = Path(local_root) if local_root else None
        bindings = cls._load_skill_bindings(builtin_path, required=True)
        if local_path:
            bindings.update(cls._load_skill_bindings(local_path, required=False))
        cls._load_layer(builtin_path, "builtin", merged, bindings, required=True)
        if local_root:
            cls._load_layer(local_path, "local", merged, bindings, required=False)
        return cls(merged)

    @staticmethod
    def _load_skill_bindings(root: Path, *, required: bool) -> dict[str, dict[str, Any]]:
        if not root.exists():
            if required:
                raise CapabilityConfigurationError(f"Capability directory does not exist: {root}")
            return {}
        path = root / "skill-bindings.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityConfigurationError(f"Cannot load skill bindings {path}: {exc}") from exc
        if data.get("schema_version") != 1 or not isinstance(data.get("bindings"), dict):
            raise CapabilityConfigurationError(f"Invalid skill bindings contract: {path}")
        bindings: dict[str, dict[str, Any]] = {}
        for name, binding in data["bindings"].items():
            selector = binding.get("selector") if isinstance(binding, dict) else None
            if not isinstance(binding, dict) or set(binding) != {"selector"}:
                raise CapabilityConfigurationError(
                    f"Skill binding {name!r} may contain only selector: {path}"
                )
            if not isinstance(selector, dict) or any(not isinstance(values, list) or not values for values in selector.values()):
                raise CapabilityConfigurationError(f"Invalid selector for skill {name!r}: {path}")
            if "path_definition" in selector and "case_type" not in selector:
                raise CapabilityConfigurationError(
                    f"Skill {name!r} selects path_definition without case_type: {path}"
                )
            bindings[name] = {"selector": selector}
        return bindings

    @classmethod
    def _load_layer(
        cls,
        root: Path,
        source: str,
        target: dict[tuple[str, str], _LoadedAsset],
        skill_bindings: dict[str, dict[str, Any]],
        *,
        required: bool,
    ) -> None:
        if not root.exists():
            if required:
                raise CapabilityConfigurationError(f"Capability directory does not exist: {root}")
            return
        json_paths = [
            path
            for directory in (root / "policies", root / "knowledge")
            if directory.exists()
            for path in directory.rglob("*.json")
        ]
        for path in sorted(json_paths):
            try:
                raw = path.read_bytes()
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                raise CapabilityConfigurationError(f"Cannot load capability asset {path}: {exc}") from exc
            cls._validate_asset(data, path)
            kind = data["kind"]
            ref = AssetRef(
                kind=kind,
                id=data["id"],
                version=data["version"],
                digest=f"sha256:{hashlib.sha256(raw).hexdigest()}",
                source=source,
            )
            target[(kind, data["id"])] = _LoadedAsset(data=data, ref=ref)

        skills_root = root / "skills"
        if not skills_root.exists():
            return
        for skill_path in sorted(path for path in skills_root.iterdir() if path.is_dir()):
            loaded = cls._load_skill(skill_path, source, skill_bindings.get(skill_path.name))
            target[("skill", loaded.ref.id)] = loaded

    @staticmethod
    def _load_skill(
        skill_path: Path,
        source: str,
        binding: dict[str, Any] | None,
    ) -> _LoadedAsset:
        entrypoint = skill_path / "SKILL.md"
        if not entrypoint.is_file():
            raise CapabilityConfigurationError(f"Skill folder is missing SKILL.md: {skill_path}")
        text = entrypoint.read_text()
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise CapabilityConfigurationError(f"SKILL.md must start with YAML frontmatter: {entrypoint}")
        frontmatter_text, body = text[4:].split("\n---\n", 1)
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            raise CapabilityConfigurationError(f"Invalid SKILL.md frontmatter {entrypoint}: {exc}") from exc
        if (
            not isinstance(frontmatter, dict)
            or set(frontmatter) != {"name", "description"}
            or not all(isinstance(frontmatter.get(key), str) for key in ("name", "description"))
        ):
            raise CapabilityConfigurationError(f"SKILL.md requires string name and description: {entrypoint}")
        if frontmatter["name"] != skill_path.name:
            raise CapabilityConfigurationError(f"Skill name must match its folder: {entrypoint}")
        paths_file = skill_path / "paths.json"
        declared_paths: list[dict[str, str]] = []
        if paths_file.is_file():
            try:
                paths_payload = json.loads(paths_file.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise CapabilityConfigurationError(f"Cannot load Skill paths {paths_file}: {exc}") from exc
            if (
                not isinstance(paths_payload, dict)
                or set(paths_payload) != {"schema_version", "paths"}
                or paths_payload.get("schema_version") != 1
                or not isinstance(paths_payload.get("paths"), list)
                or not paths_payload["paths"]
            ):
                raise CapabilityConfigurationError(f"Invalid Skill paths contract: {paths_file}")
            for item in paths_payload["paths"]:
                if not isinstance(item, dict) or set(item) != {"id", "title", "description"} or not all(
                    isinstance(item[field], str) and item[field].strip()
                    for field in ("id", "title", "description")
                ):
                    raise CapabilityConfigurationError(f"Invalid Skill PathDefinition: {paths_file}")
                declared_paths.append({field: item[field].strip() for field in ("id", "title", "description")})
            if len({item["id"] for item in declared_paths}) != len(declared_paths):
                raise CapabilityConfigurationError(f"Skill PathDefinition ids must be unique: {paths_file}")
            selector = binding.get("selector", {}) if binding else {}
            if len(selector.get("case_type", [])) != 1 or "path_definition" in selector:
                raise CapabilityConfigurationError(
                    f"A Skill owning paths.json must bind exactly one case_type and not path_definition: {paths_file}"
                )

        digest = hashlib.sha256()
        inventory: list[dict[str, Any]] = []
        for path in sorted(path for path in skill_path.rglob("*") if path.is_file()):
            relative = path.relative_to(skill_path).as_posix()
            raw = path.read_bytes()
            file_digest = hashlib.sha256(raw).hexdigest()
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(raw)
            inventory.append({"path": relative, "digest": f"sha256:{file_digest}", "size": len(raw)})
        digest_hex = digest.hexdigest()
        data = {
            "schema_version": 1,
            "kind": "skill",
            "id": frontmatter["name"],
            "version": digest_hex[:12],
            "title": frontmatter["name"],
            "status": "published",
            "selector": deepcopy(binding.get("selector")) if binding else None,
            "paths": deepcopy(declared_paths),
            "description": frontmatter["description"],
            "purpose": frontmatter["description"],
            "entrypoint": "SKILL.md",
            "instructions_markdown": body.strip(),
            "files": inventory,
        }
        ref = AssetRef(
            kind="skill",
            id=frontmatter["name"],
            version=digest_hex[:12],
            digest=f"sha256:{digest_hex}",
            source=source,
        )
        return _LoadedAsset(data=data, ref=ref)

    @staticmethod
    def _validate_asset(data: Any, path: Path) -> None:
        if not isinstance(data, dict):
            raise CapabilityConfigurationError(f"Capability asset must be an object: {path}")
        for field in ("schema_version", "kind", "id", "version", "title", "status"):
            if field not in data:
                raise CapabilityConfigurationError(f"Missing {field!r} in {path}")
        if data["schema_version"] != 1:
            raise CapabilityConfigurationError(f"Unsupported schema_version in {path}")
        if data["kind"] not in ASSET_KINDS:
            raise CapabilityConfigurationError(f"Unsupported capability kind in {path}")
        if data["kind"] == "skill":
            raise CapabilityConfigurationError(f"Skill assets must use a SKILL.md folder, not JSON: {path}")
        if data["status"] != "published":
            raise CapabilityConfigurationError(f"Only published assets can be loaded: {path}")
        selector_name = {"policy": "match", "knowledge": "scope"}[data["kind"]]
        selector = data.get(selector_name, {})
        if not isinstance(selector, dict) or any(not isinstance(values, list) or not values for values in selector.values()):
            raise CapabilityConfigurationError(f"{selector_name} must map fields to non-empty lists: {path}")
        if "path_definition" in selector and "case_type" not in selector:
            raise CapabilityConfigurationError(
                f"{selector_name} selects path_definition without case_type in {path}"
            )
        if data["kind"] == "policy" and not isinstance(data.get("requirements"), dict):
            raise CapabilityConfigurationError(f"Policy requirements must be an object: {path}")
        if data["kind"] == "policy":
            requirements = data["requirements"]
            unsupported = set(requirements) - {"commitments"}
            if unsupported:
                raise CapabilityConfigurationError(
                    f"Unsupported initial Policy requirements {sorted(unsupported)} in {path}"
                )
            if "priority" in data:
                raise CapabilityConfigurationError(f"Policy priority is not part of the initial contract: {path}")
            if not isinstance(requirements.get("commitments", []), list):
                raise CapabilityConfigurationError(f"Policy commitments must be a list: {path}")
            for node in requirements.get("commitments", []):
                if not isinstance(node, dict) or any(field not in node for field in ("id", "role", "node_type", "reviews")):
                    raise CapabilityConfigurationError(f"Policy commitment has an invalid contract: {path}")
                if not isinstance(node["reviews"], list) or not isinstance(node.get("depends_on", []), list):
                    raise CapabilityConfigurationError(f"Policy commitment reviews/dependencies must be lists: {path}")
        if data["kind"] == "knowledge":
            if not isinstance(data.get("source"), dict) or not isinstance(data.get("content"), dict):
                raise CapabilityConfigurationError(f"Knowledge source/content must be objects: {path}")

    def resolve(self, context: dict[str, str]) -> CapabilityResolution:
        selected = {
            kind: sorted(
                (
                    asset
                    for (asset_kind, _), asset in self._assets.items()
                    if asset_kind == kind and self._asset_matches(asset, context)
                ),
                key=lambda asset: asset.ref.id,
            )
            for kind in ASSET_KINDS
        }
        return CapabilityResolution(
            context=deepcopy(context),
            policies=tuple(asset.ref for asset in selected["policy"]),
            skills=tuple(asset.ref for asset in selected["skill"]),
            knowledge=tuple(asset.ref for asset in selected["knowledge"]),
            compiled_policy=self._compile_policies(selected["policy"]),
            asset_payloads={
                group: [deepcopy(asset.data) | {"resolved_ref": asdict(asset.ref)} for asset in selected[kind]]
                for group, kind in (("policies", "policy"), ("skills", "skill"), ("knowledge", "knowledge"))
            },
        )

    def resolve_path_candidates(self, context: dict[str, str]) -> tuple[SkillPathDefinition, ...]:
        """Expand PathDefinitions owned by orchestration Skills matching this Case."""
        candidates: dict[str, SkillPathDefinition] = {}
        matched_skills = sorted(
            (
                asset
                for (kind, _), asset in self._assets.items()
                if kind == "skill" and self._asset_matches(asset, context)
            ),
            key=lambda asset: asset.ref.id,
        )
        for asset in matched_skills:
            for definition in asset.data.get("paths", []):
                current = candidates.get(definition["id"])
                if current and (current.title, current.description) != (
                    definition["title"], definition["description"]
                ):
                    raise CapabilityConflictError(
                        f"Matched orchestration Skills disagree on PathDefinition {definition['id']}"
                    )
                candidates[definition["id"]] = SkillPathDefinition(
                    id=definition["id"],
                    title=definition["title"],
                    description=definition["description"],
                    skill_refs=(current.skill_refs if current else ()) + (asset.ref,),
                )
        return tuple(candidates.values())

    def describe_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        frozen_payloads = snapshot.get("asset_payloads", {})
        for group, kind in (("policies", "policy"), ("skills", "skill"), ("knowledge", "knowledge")):
            groups[group] = []
            for ref in snapshot.get(group, []):
                frozen = next(
                    (
                        item for item in frozen_payloads.get(group, [])
                        if item.get("resolved_ref", {}).get("id") == ref["id"]
                        and item.get("resolved_ref", {}).get("digest") == ref["digest"]
                    ),
                    None,
                )
                if frozen:
                    groups[group].append(deepcopy(frozen))
                    continue
                asset = self._assets.get((kind, ref["id"]))
                if asset and asset.ref.digest == ref["digest"]:
                    groups[group].append(deepcopy(asset.data) | {"resolved_ref": deepcopy(ref)})
                else:
                    groups[group].append({"resolved_ref": deepcopy(ref), "available": False})
        return {
            "snapshot": deepcopy(snapshot),
            "assets": groups,
        }

    @staticmethod
    def _asset_matches(asset: _LoadedAsset, context: dict[str, str]) -> bool:
        selector_name = {"policy": "match", "skill": "selector", "knowledge": "scope"}[asset.ref.kind]
        selector = asset.data.get(selector_name)
        return isinstance(selector, dict) and bool(selector) and CapabilityRegistry._matches(selector, context)

    @staticmethod
    def _matches(selector: dict[str, list[str]], context: dict[str, str]) -> bool:
        return all(context.get(field) in allowed for field, allowed in selector.items())

    @staticmethod
    def _compile_policies(policies: Iterable[_LoadedAsset]) -> dict[str, Any]:
        commitments: dict[str, tuple[dict[str, Any], str]] = {}

        for asset in policies:
            requirements = asset.data["requirements"]
            for node in requirements.get("commitments", []):
                node_id = node["id"]
                current = commitments.get(node_id)
                if current and current[0] != node:
                    raise CapabilityConflictError(
                        f"Policies {current[1]} and {asset.ref.id} define incompatible commitment {node_id}"
                    )
                commitments[node_id] = (deepcopy(node), asset.ref.id)

        ordered_nodes = CapabilityRegistry._order_commitments([item[0] for item in commitments.values()])
        return {"commitments": ordered_nodes}

    @staticmethod
    def _order_commitments(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {node["id"]: node for node in nodes}
        unknown = {
            dependency
            for node in nodes
            for dependency in node.get("depends_on", [])
            if dependency not in by_id
        }
        if unknown:
            raise CapabilityConflictError(f"Commitment dependencies are missing: {sorted(unknown)}")

        ordered: list[dict[str, Any]] = []
        remaining = dict(by_id)
        while remaining:
            ready = sorted(
                node_id
                for node_id, node in remaining.items()
                if all(dependency in {item["id"] for item in ordered} for dependency in node.get("depends_on", []))
            )
            if not ready:
                raise CapabilityConflictError("Compiled Policy commitments contain a cycle")
            for node_id in ready:
                ordered.append(remaining.pop(node_id))
        return ordered

    def list_refs(self) -> list[dict[str, str]]:
        return [asdict(self._assets[key].ref) for key in sorted(self._assets)]


def default_registry() -> CapabilityRegistry:
    builtin_root = Path(os.getenv("AGENTIC_CM_BUILTIN_CAPABILITIES_DIR", DEFAULT_BUILTIN_ROOT))
    local_value = os.getenv("AGENTIC_CM_LOCAL_CAPABILITIES_DIR")
    local_root = Path(local_value) if local_value else DEFAULT_LOCAL_ROOT
    return CapabilityRegistry.from_directories(builtin_root, local_root)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Validate and inspect Agentic CM capability assets")
    parser.add_argument("command", choices=("validate", "resolve"))
    parser.add_argument("--local-dir", type=Path, default=DEFAULT_LOCAL_ROOT)
    args = parser.parse_args()
    registry = CapabilityRegistry.from_directories(DEFAULT_BUILTIN_ROOT, args.local_dir)
    if args.command == "validate":
        print(json.dumps({"status": "ok", "assets": registry.list_refs()}, ensure_ascii=False, indent=2))
        return
    context = {
        "organization": "demo-supply-chain",
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    }
    print(json.dumps(registry.resolve(context).to_snapshot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
