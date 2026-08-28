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
SELECTOR_FIELDS = frozenset({"case_type", "path_definition"})
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
class SkillEntrypointResolution:
    entrypoint: AssetRef
    members: tuple[AssetRef, ...]


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
            "compiled_policy": deepcopy(self.compiled_policy),
            "asset_payloads": deepcopy(self.asset_payloads),
        }


@dataclass(frozen=True)
class PathDefinition:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class CaseTypePathCatalog:
    case_type: str
    title: str
    paths: tuple[PathDefinition, ...]
    source: str


@dataclass(frozen=True)
class _LoadedAsset:
    data: dict[str, Any]
    ref: AssetRef


class CapabilityRegistry:
    """Loads built-ins, then adds or intentionally replaces workspace-local assets."""

    def __init__(
        self,
        assets: dict[tuple[str, str], _LoadedAsset],
        case_types: dict[str, CaseTypePathCatalog] | None = None,
        skill_ownership: dict[str, str] | None = None,
    ) -> None:
        self._assets = assets
        self._case_types = case_types or {}
        self._skill_ownership = skill_ownership or {}
        self._validate_skill_bundles()
        self._validate_skill_ownership()

    def _validate_skill_bundles(self) -> None:
        for (kind, skill_id), asset in self._assets.items():
            if kind != "skill" or "members" not in asset.data:
                continue
            for member_id in asset.data["members"]:
                member = self._assets.get(("skill", member_id))
                if member is None:
                    raise CapabilityConfigurationError(
                        f"Skill bundle {skill_id!r} references unknown member {member_id!r}"
                    )
                if member.data.get("members"):
                    raise CapabilityConfigurationError(
                        f"Skill bundle {skill_id!r} member {member_id!r} must be an atomic Skill"
                    )
    def _validate_skill_ownership(self) -> None:
        for skill_id in self._skill_ownership:
            if ("skill", skill_id) not in self._assets:
                raise CapabilityConfigurationError(
                    f"Skill ownership references unknown Skill {skill_id!r}"
                )

    @classmethod
    def from_directories(
        cls,
        builtin_root: str | Path = DEFAULT_BUILTIN_ROOT,
        local_root: str | Path | None = DEFAULT_LOCAL_ROOT,
    ) -> "CapabilityRegistry":
        merged: dict[tuple[str, str], _LoadedAsset] = {}
        builtin_path = Path(builtin_root)
        local_path = Path(local_root) if local_root else None
        case_types = cls._load_case_type_catalogs(builtin_path, "builtin", required=True)
        if local_path:
            case_types.update(
                cls._load_case_type_catalogs(local_path, "local", required=False)
            )
        cls._load_layer(builtin_path, "builtin", merged, required=True)
        if local_path:
            cls._load_layer(local_path, "local", merged, required=False)
        skill_ownership = cls._load_skill_ownership(builtin_path, required=True)
        if local_path:
            skill_ownership.update(cls._load_skill_ownership(local_path, required=False))
        return cls(merged, case_types, skill_ownership)

    @staticmethod
    def _load_case_type_catalogs(
        root: Path,
        source: str,
        *,
        required: bool,
    ) -> dict[str, CaseTypePathCatalog]:
        if not root.exists():
            if required:
                raise CapabilityConfigurationError(f"Capability directory does not exist: {root}")
            return {}
        catalogs: dict[str, CaseTypePathCatalog] = {}
        case_types_root = root / "case-types"
        if not case_types_root.exists():
            return catalogs
        for catalog_dir in sorted(path for path in case_types_root.iterdir() if path.is_dir()):
            path = catalog_dir / "paths.json"
            if not path.is_file():
                raise CapabilityConfigurationError(f"Case Type catalog is missing paths.json: {catalog_dir}")
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise CapabilityConfigurationError(f"Cannot load Case Type catalog {path}: {exc}") from exc
            if (
                not isinstance(payload, dict)
                or set(payload) != {"schema_version", "case_type", "title", "paths"}
                or payload.get("schema_version") != 1
                or not isinstance(payload.get("case_type"), str)
                or not payload["case_type"].strip()
                or not isinstance(payload.get("title"), str)
                or not payload["title"].strip()
                or not isinstance(payload.get("paths"), list)
                or not payload["paths"]
            ):
                raise CapabilityConfigurationError(f"Invalid Case Type catalog contract: {path}")
            definitions: list[PathDefinition] = []
            for item in payload["paths"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"id", "title", "description"}
                    or any(
                        not isinstance(item.get(field), str) or not item[field].strip()
                        for field in ("id", "title", "description")
                    )
                ):
                    raise CapabilityConfigurationError(f"Invalid Case Type PathDefinition: {path}")
                definitions.append(PathDefinition(**{
                    field: item[field].strip()
                    for field in ("id", "title", "description")
                }))
            if len({item.id for item in definitions}) != len(definitions):
                raise CapabilityConfigurationError(f"Case Type Path ids must be unique: {path}")
            case_type = payload["case_type"].strip()
            if case_type in catalogs:
                raise CapabilityConfigurationError(
                    f"Duplicate Case Type catalog for {case_type!r}: {path}"
                )
            catalogs[case_type] = CaseTypePathCatalog(
                case_type=case_type,
                title=payload["title"].strip(),
                paths=tuple(definitions),
                source=source,
            )
        return catalogs

    @staticmethod
    def _validate_selector(selector: Any, label: str, path: Path) -> None:
        if (
            not isinstance(selector, dict)
            or not selector
            or any(not isinstance(values, list) or not values for values in selector.values())
        ):
            raise CapabilityConfigurationError(
                f"{label} selector must map fields to non-empty lists: {path}"
            )
        unsupported = set(selector) - SELECTOR_FIELDS
        if unsupported:
            raise CapabilityConfigurationError(
                f"Unsupported selector fields {sorted(unsupported)} for {label}: {path}"
            )
        if "path_definition" in selector and "case_type" not in selector:
            raise CapabilityConfigurationError(
                f"{label} selector selects path_definition without case_type: {path}"
            )

    @staticmethod
    def _load_skill_ownership(root: Path, *, required: bool) -> dict[str, str]:
        if not root.exists():
            if required:
                raise CapabilityConfigurationError(f"Capability directory does not exist: {root}")
            return {}
        path = root / "skill-ownership.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityConfigurationError(f"Cannot load Skill ownership {path}: {exc}") from exc
        if (
            not isinstance(data, dict)
            or set(data) != {"schema_version", "ownership"}
            or data.get("schema_version") != 1
            or not isinstance(data.get("ownership"), dict)
        ):
            raise CapabilityConfigurationError(f"Invalid Skill ownership contract: {path}")
        ownership: dict[str, str] = {}
        for skill_id, details in data["ownership"].items():
            if (
                not isinstance(skill_id, str)
                or not skill_id.strip()
                or not isinstance(details, dict)
                or set(details) != {"maintainer_role"}
                or not isinstance(details.get("maintainer_role"), str)
                or not details["maintainer_role"].strip()
            ):
                raise CapabilityConfigurationError(
                    f"Skill ownership {skill_id!r} requires one non-empty maintainer_role: {path}"
                )
            ownership[skill_id.strip()] = details["maintainer_role"].strip()
        return ownership

    @classmethod
    def _load_layer(
        cls,
        root: Path,
        source: str,
        target: dict[tuple[str, str], _LoadedAsset],
        *,
        required: bool,
    ) -> None:
        if not root.exists():
            if required:
                raise CapabilityConfigurationError(f"Capability directory does not exist: {root}")
            return
        for directory_name, kind in (("policies", "policy"), ("knowledge", "knowledge")):
            directory = root / directory_name
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*.json")):
                try:
                    raw = path.read_bytes()
                    data = json.loads(raw)
                except (OSError, json.JSONDecodeError) as exc:
                    raise CapabilityConfigurationError(f"Cannot load capability asset {path}: {exc}") from exc
                cls._validate_asset(data, path, kind)
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
            loaded = cls._load_skill(skill_path, source)
            target[("skill", loaded.ref.id)] = loaded

    @staticmethod
    def _load_skill(
        skill_path: Path,
        source: str,
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
        display_title = next(
            (
                line.removeprefix("# ").strip()
                for line in body.splitlines()
                if line.startswith("# ") and line.removeprefix("# ").strip()
            ),
            frontmatter["name"],
        )
        paths_file = skill_path / "paths.json"
        if paths_file.exists():
            raise CapabilityConfigurationError(
                f"Skill paths.json is no longer supported; define candidate Paths in Case Type catalogs: {paths_file}"
            )

        bundle_file = skill_path / "bundle.json"
        bundle_members: list[str] | None = None
        if bundle_file.is_file():
            try:
                bundle_payload = json.loads(bundle_file.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise CapabilityConfigurationError(f"Cannot load Skill bundle {bundle_file}: {exc}") from exc
            if (
                not isinstance(bundle_payload, dict)
                or set(bundle_payload) != {"schema_version", "members"}
                or bundle_payload.get("schema_version") != 1
                or not isinstance(bundle_payload.get("members"), list)
                or not bundle_payload["members"]
                or any(not isinstance(member, str) or not member.strip() for member in bundle_payload["members"])
            ):
                raise CapabilityConfigurationError(f"Invalid Skill bundle contract: {bundle_file}")
            bundle_members = [member.strip() for member in bundle_payload["members"]]
            if len(set(bundle_members)) != len(bundle_members):
                raise CapabilityConfigurationError(f"Skill bundle members must be unique: {bundle_file}")
            if frontmatter["name"] in bundle_members:
                raise CapabilityConfigurationError(f"Skill bundle cannot contain itself: {bundle_file}")

        path_options: list[dict[str, str]] = []
        options_file = skill_path / "path-options.json"
        if options_file.is_file():
            try:
                options_payload = json.loads(options_file.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise CapabilityConfigurationError(f"Cannot load Skill options {options_file}: {exc}") from exc
            if (
                not isinstance(options_payload, dict)
                or set(options_payload) != {"schema_version", "options"}
                or options_payload.get("schema_version") != 1
                or not isinstance(options_payload.get("options"), list)
                or not options_payload["options"]
            ):
                raise CapabilityConfigurationError(f"Invalid Skill path-options contract: {options_file}")
            for item in options_payload["options"]:
                if not isinstance(item, dict) or set(item) != {"id", "material_id", "title", "description"} or any(
                    not isinstance(item[field], str) or not item[field].strip()
                    for field in ("id", "material_id", "title", "description")
                ):
                    raise CapabilityConfigurationError(f"Invalid Skill path option: {options_file}")
                path_options.append({field: item[field].strip() for field in item})
            if len({item["id"] for item in path_options}) != len(path_options):
                raise CapabilityConfigurationError(f"Skill path option ids must be unique: {options_file}")

        tools: list[dict[str, Any]] = []
        tools_file = skill_path / "tools.json"
        if tools_file.is_file():
            try:
                tools_payload = json.loads(tools_file.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise CapabilityConfigurationError(f"Cannot load Skill tools {tools_file}: {exc}") from exc
            if (
                not isinstance(tools_payload, dict)
                or set(tools_payload) != {"schema_version", "tools"}
                or tools_payload.get("schema_version") != 1
                or not isinstance(tools_payload.get("tools"), list)
            ):
                raise CapabilityConfigurationError(f"Invalid Skill tools contract: {tools_file}")
            for item in tools_payload["tools"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"id", "description", "read_only", "input_key", "records"}
                    or not all(isinstance(item.get(field), str) and item[field].strip() for field in ("id", "description", "input_key"))
                    or item.get("read_only") is not True
                    or not isinstance(item.get("records"), dict)
                ):
                    raise CapabilityConfigurationError(f"Invalid read-only Skill tool: {tools_file}")
                tools.append(deepcopy(item))
            if len({item["id"] for item in tools}) != len(tools):
                raise CapabilityConfigurationError(f"Skill tool ids must be unique: {tools_file}")

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
            "id": frontmatter["name"],
            "version": digest_hex[:12],
            "title": display_title,
            "path_options": deepcopy(path_options),
            "tools": deepcopy(tools),
            "description": frontmatter["description"],
            "instructions_markdown": body.strip(),
            "files": inventory,
        }
        if bundle_members is not None:
            data["members"] = deepcopy(bundle_members)
        ref = AssetRef(
            kind="skill",
            id=frontmatter["name"],
            version=digest_hex[:12],
            digest=f"sha256:{digest_hex}",
            source=source,
        )
        return _LoadedAsset(data=data, ref=ref)

    @staticmethod
    def _validate_asset(data: Any, path: Path, kind: str) -> None:
        if not isinstance(data, dict):
            raise CapabilityConfigurationError(f"Capability asset must be an object: {path}")
        for field in ("schema_version", "id", "version", "title"):
            if field not in data:
                raise CapabilityConfigurationError(f"Missing {field!r} in {path}")
        if data["schema_version"] != 1:
            raise CapabilityConfigurationError(f"Unsupported schema_version in {path}")
        removed_fields = set(data) & {"kind", "status"}
        if removed_fields:
            raise CapabilityConfigurationError(
                f"Capability asset has removed fields {sorted(removed_fields)}: {path}"
            )
        selector = data.get("selector")
        CapabilityRegistry._validate_selector(selector, kind.title(), path)
        if kind == "policy" and not isinstance(data.get("requirements"), dict):
            raise CapabilityConfigurationError(f"Policy requirements must be an object: {path}")
        if kind == "policy":
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
                if not isinstance(node, dict) or any(
                    field not in node
                    for field in ("id", "role", "review_dimension")
                ):
                    raise CapabilityConfigurationError(f"Policy commitment has an invalid contract: {path}")
                if set(node) - {"id", "role", "review_dimension", "depends_on"}:
                    raise CapabilityConfigurationError(f"Policy commitment has unsupported fields: {path}")
                if any(
                    not isinstance(node.get(field), str) or not node[field].strip()
                    for field in ("id", "role", "review_dimension")
                ):
                    raise CapabilityConfigurationError(f"Policy commitment strings must be non-empty: {path}")
                if not isinstance(node.get("depends_on", []), list):
                    raise CapabilityConfigurationError(f"Policy commitment dependencies must be a list: {path}")
        if kind == "knowledge":
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
            for kind in ("policy", "knowledge")
        }
        selected["skill"] = []
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

    def resolve_refs(
        self,
        kind: str,
        refs: Iterable[Any],
    ) -> tuple[dict[str, Any], ...]:
        if kind not in ASSET_KINDS:
            raise CapabilityConfigurationError(f"Unsupported capability kind: {kind}")
        payloads: list[dict[str, Any]] = []
        for ref in refs:
            asset = self._assets.get((kind, ref.id))
            if asset is None:
                raise CapabilityConfigurationError(f"unknown {kind} reference: {ref.id}")
            if asset.ref.version != ref.version:
                raise CapabilityConfigurationError(
                    f"{kind} {ref.id} version mismatch: "
                    f"expected {ref.version}, actual {asset.ref.version}"
                )
            if asset.ref.digest != ref.digest:
                raise CapabilityConfigurationError(
                    f"{kind} {ref.id} digest mismatch: "
                    f"expected {ref.digest}, actual {asset.ref.digest}"
                )
            payloads.append(deepcopy(asset.data) | {"resolved_ref": asdict(asset.ref)})
        return tuple(payloads)

    def resolve_manifest_path(
        self,
        path: Any,
        case_type: str,
    ) -> CapabilityResolution:
        skill_refs = path.skill_refs()
        policies = self.resolve_refs("policy", path.policies)
        skills = self.resolve_refs("skill", skill_refs)
        knowledge = self.resolve_refs("knowledge", path.knowledge)
        loaded_policies = tuple(self._assets[("policy", ref.id)] for ref in path.policies)
        return CapabilityResolution(
            context={"case_type": case_type, "path_definition": path.definition},
            policies=tuple(asset.ref for asset in loaded_policies),
            skills=tuple(self._assets[("skill", ref.id)].ref for ref in skill_refs),
            knowledge=tuple(self._assets[("knowledge", ref.id)].ref for ref in path.knowledge),
            compiled_policy=self._compile_policies(loaded_policies),
            asset_payloads={
                "policies": list(policies),
                "skills": list(skills),
                "knowledge": list(knowledge),
            },
        )

    def resolve_path_candidates(self, context: dict[str, str]) -> tuple[PathDefinition, ...]:
        """Return the Path catalog owned by this Case type."""
        catalog = self._case_types.get(context.get("case_type", ""))
        return catalog.paths if catalog else ()

    def describe_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        frozen_payloads = snapshot.get("asset_payloads", {})
        return {
            "snapshot": deepcopy(snapshot),
            "assets": {
                group: deepcopy(frozen_payloads.get(group, []))
                for group in ("policies", "skills", "knowledge")
            },
        }

    @staticmethod
    def _asset_matches(asset: _LoadedAsset, context: dict[str, str]) -> bool:
        selector = asset.data.get("selector")
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

    def list_assets(self) -> dict[str, list[dict[str, Any]]]:
        """Return the effective organization library after local overrides are applied."""
        assets: dict[str, list[dict[str, Any]]] = {"policies": [], "skills": [], "knowledge": []}
        for (kind, _), asset in sorted(self._assets.items()):
            payload = deepcopy(asset.data) | {"resolved_ref": asdict(asset.ref)}
            if kind == "skill":
                payload["kind"] = "bundle" if asset.data.get("members") else "atomic"
                payload["maintainer_role"] = self._skill_ownership.get(asset.ref.id)
            assets[{"policy": "policies", "skill": "skills", "knowledge": "knowledge"}[kind]].append(payload)
        return assets

    def list_orchestrator_skills(self) -> tuple[dict[str, str], ...]:
        member_ids = {
            member_id
            for (kind, _), asset in self._assets.items()
            if kind == "skill"
            for member_id in asset.data.get("members", [])
        }
        return tuple(
            {
                "id": asset.ref.id,
                "title": asset.data["title"],
                "description": asset.data["description"],
                "kind": "bundle" if asset.data.get("members") else "atomic",
            }
            for (kind, skill_id), asset in sorted(self._assets.items())
            if kind == "skill" and skill_id not in member_ids
        )

    def resolve_skill_entrypoint(self, skill_id: str) -> SkillEntrypointResolution:
        asset = self._assets.get(("skill", skill_id))
        if asset is None:
            raise CapabilityConfigurationError(f"unknown Skill entrypoint: {skill_id}")
        allowed = {item["id"] for item in self.list_orchestrator_skills()}
        if skill_id not in allowed:
            raise CapabilityConfigurationError(f"Skill is not an Orchestrator entrypoint: {skill_id}")
        return SkillEntrypointResolution(
            entrypoint=asset.ref,
            members=tuple(
                self._assets[("skill", member_id)].ref
                for member_id in asset.data.get("members", [])
            ),
        )

    def list_case_types(self) -> list[dict[str, Any]]:
        """Return effective Case Type Path catalogs after local overrides."""
        return [
            {
                "case_type": catalog.case_type,
                "title": catalog.title,
                "paths": [asdict(path) for path in catalog.paths],
                "source": catalog.source,
            }
            for catalog in sorted(self._case_types.values(), key=lambda item: item.case_type)
        ]


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
        "case_type": "ORDER_DELIVERY_RISK",
        "path_definition": "MaterialSubstitution",
    }
    print(json.dumps(registry.resolve(context).to_snapshot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
