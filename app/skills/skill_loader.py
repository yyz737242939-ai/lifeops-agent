from dataclasses import dataclass
from pathlib import Path


SKILLS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: Path


@dataclass(frozen=True)
class Skill:
    metadata: SkillMetadata
    instructions: str


def _read_frontmatter(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    with path.open(encoding="utf-8") as skill_file:
        if skill_file.readline().strip() != "---":
            raise ValueError(f"{path} must start with YAML frontmatter")

        for line in skill_file:
            stripped = line.strip()
            if stripped == "---":
                break
            if not stripped or stripped.startswith("#"):
                continue
            key, separator, value = stripped.partition(":")
            if not separator:
                raise ValueError(f"Invalid frontmatter line in {path}: {stripped}")
            metadata[key.strip()] = value.strip().strip('"').strip("'")
        else:
            raise ValueError(f"{path} has no closing frontmatter delimiter")

    unexpected = set(metadata) - {"name", "description"}
    if unexpected:
        raise ValueError(
            f"{path} has unsupported frontmatter fields: {sorted(unexpected)}"
        )
    for required in ("name", "description"):
        if not metadata.get(required):
            raise ValueError(f"{path} is missing required field: {required}")
    return metadata


def discover_skills(skills_dir: Path = SKILLS_DIR) -> dict[str, SkillMetadata]:
    skills: dict[str, SkillMetadata] = {}
    for skill_path in sorted(skills_dir.glob("*/SKILL.md")):
        frontmatter = _read_frontmatter(skill_path)
        name = frontmatter["name"]
        if name != skill_path.parent.name:
            raise ValueError(
                f"Skill name {name!r} must match folder {skill_path.parent.name!r}"
            )
        if name in skills:
            raise ValueError(f"Duplicate skill name: {name}")
        skills[name] = SkillMetadata(
            name=name,
            description=frontmatter["description"],
            path=skill_path,
        )
    return skills


def load_skill(metadata: SkillMetadata) -> Skill:
    content = metadata.path.read_text(encoding="utf-8")
    parts = content.split("---", maxsplit=2)
    if len(parts) != 3:
        raise ValueError(f"Invalid SKILL.md structure: {metadata.path}")
    instructions = parts[2].strip()
    if not instructions:
        raise ValueError(f"Skill body is empty: {metadata.path}")
    return Skill(metadata=metadata, instructions=instructions)
