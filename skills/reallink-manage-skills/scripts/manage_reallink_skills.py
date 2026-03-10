#!/usr/bin/env python3
"""Shared skill operations for search, create, install, and upload workflows."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

REPO_URL_DEFAULT = "https://github.com/real-link-tech/reallink-skills.git"
REPO_PATH_ENV = "REALLINK_SKILLS_REPO"
SEARCH_THRESHOLD_DEFAULT = 0.15
INSTALL_THRESHOLD_DEFAULT = 0.45
INSTALL_GAP_DEFAULT = 0.08
SIMILARITY_THRESHOLD_DEFAULT = 0.62

ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "build",
    "by",
    "check",
    "claude",
    "code",
    "create",
    "creating",
    "creator",
    "current",
    "directory",
    "download",
    "existing",
    "find",
    "for",
    "from",
    "generate",
    "generated",
    "git",
    "help",
    "if",
    "in",
    "install",
    "into",
    "is",
    "it",
    "local",
    "match",
    "matching",
    "new",
    "of",
    "on",
    "or",
    "project",
    "repo",
    "repository",
    "request",
    "search",
    "shared",
    "similar",
    "skill",
    "skills",
    "system",
    "task",
    "that",
    "the",
    "then",
    "this",
    "to",
    "under",
    "upload",
    "use",
    "user",
    "whether",
    "when",
    "with",
}

CHINESE_STOPWORDS = {
    "一个",
    "一下",
    "上传",
    "下载",
    "仓库",
    "共享",
    "创建",
    "当前",
    "已有",
    "本地",
    "检查",
    "查询",
    "检索",
    "生成",
    "目录",
    "相似",
    "确认",
    "用户",
    "相关",
    "直接",
    "结束",
    "需求",
    "请求",
    "项目",
}

IGNORED_COPY_PATTERNS = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "Thumbs.db",
)


class SkillError(RuntimeError):
    """Raised when the script cannot continue safely."""


@dataclass
class SkillProfile:
    folder_name: str
    name: str
    description: str
    path: Path
    body: str
    headings: str
    top_level_entries: set[str]


@dataclass
class SearchResult:
    skill: SkillProfile
    score: float
    matched_terms: list[str]


@dataclass
class MatchResult:
    skill: SkillProfile
    scope: str
    score: float
    exact_folder_name: bool
    exact_frontmatter_name: bool
    matched_terms: list[str]


@dataclass
class SubmissionDecision:
    blocked: bool
    reason: str | None
    action: str | None
    target_path: Path | None


@dataclass
class CreateOutcome:
    blocked: bool
    reason: str | None
    recommendation: str | None
    scope: str | None
    match: MatchResult | None
    target_path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shared reallink skill operations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    command_specs = [
        ("search", ["find"]),
        ("auto-install", []),
        ("install", ["download"]),
        ("upload-check", ["check-upload"]),
        ("upload", []),
        ("create-check", ["check-create"]),
        ("create", []),
    ]
    for command_name, aliases in command_specs:
        subparser = subparsers.add_parser(command_name, aliases=aliases)
        subparser.add_argument("--repo-path", help="Use an existing local reallink-skills checkout.")
        subparser.add_argument(
            "--repo-url",
            default=REPO_URL_DEFAULT,
            help="Repository URL used when a cached clone is needed.",
        )
        subparser.add_argument(
            "--cache-dir",
            help="Cache directory used when the repository must be cloned.",
        )
        subparser.add_argument("--json", action="store_true", help="Emit JSON.")

    search_parser = subparsers.choices["search"]
    search_parser.add_argument("--query", required=True, help="Original user request.")
    search_parser.add_argument("--limit", type=int, default=5, help="Maximum matches to print.")
    search_parser.add_argument(
        "--min-score",
        type=float,
        default=SEARCH_THRESHOLD_DEFAULT,
        help="Discard results below this score.",
    )

    install_parser = subparsers.choices["install"]
    install_parser.add_argument("--skill", required=True, help="Exact skill folder name to install.")
    install_parser.add_argument(
        "--project-root",
        default=os.getcwd(),
        help="Project root that should receive .claude/skills.",
    )
    install_parser.add_argument("--force", action="store_true", help="Replace an existing target.")

    auto_install_parser = subparsers.choices["auto-install"]
    auto_install_parser.add_argument("--query", required=True, help="Original user request.")
    auto_install_parser.add_argument(
        "--project-root",
        default=os.getcwd(),
        help="Project root that should receive .claude/skills.",
    )
    auto_install_parser.add_argument("--force", action="store_true", help="Replace an existing target.")
    auto_install_parser.add_argument("--limit", type=int, default=5, help="Maximum matches to inspect.")
    auto_install_parser.add_argument(
        "--min-score",
        type=float,
        default=INSTALL_THRESHOLD_DEFAULT,
        help="Minimum score required to install the best match.",
    )
    auto_install_parser.add_argument(
        "--min-gap",
        type=float,
        default=INSTALL_GAP_DEFAULT,
        help="Minimum lead over the second-best match before auto-install.",
    )

    for command_name in ("upload-check", "upload"):
        subparser = subparsers.choices[command_name]
        subparser.add_argument("--skill", required=True, help="Source skill folder name.")
        subparser.add_argument(
            "--project-root",
            default=os.getcwd(),
            help="Project root that contains .claude/skills.",
        )
        subparser.add_argument(
            "--source-dir",
            help="Explicit .claude/skills directory. Overrides --project-root.",
        )
        subparser.add_argument(
            "--similar-threshold",
            type=float,
            default=SIMILARITY_THRESHOLD_DEFAULT,
            help="Block upload when an existing skill meets or exceeds this similarity.",
        )
        subparser.add_argument("--limit", type=int, default=5, help="Maximum matches to show.")

    upload_parser = subparsers.choices["upload"]
    upload_parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Copy the skill into the repository without creating a git commit.",
    )
    upload_parser.add_argument(
        "--no-push",
        action="store_true",
        help="Create the commit locally without pushing it.",
    )

    for command_name in ("create-check", "create"):
        subparser = subparsers.choices[command_name]
        subparser.add_argument("--skill-name", required=True, help="Planned skill folder name.")
        subparser.add_argument("--request", required=True, help="Original user request.")
        subparser.add_argument(
            "--project-root",
            default=os.getcwd(),
            help="Project root that contains or should contain .claude/skills.",
        )
        subparser.add_argument(
            "--local-skills-dir",
            help="Explicit .claude/skills directory. Overrides --project-root.",
        )
        subparser.add_argument(
            "--similar-threshold",
            type=float,
            default=SIMILARITY_THRESHOLD_DEFAULT,
            help="Block creation when a similar skill meets or exceeds this score.",
        )
        subparser.add_argument("--limit", type=int, default=5, help="Maximum matches to show.")

    create_parser = subparsers.choices["create"]
    create_parser.add_argument(
        "--resources",
        default="",
        help="Comma-separated resource directories for init_skill.py.",
    )
    create_parser.add_argument(
        "--examples",
        action="store_true",
        help="Create example files inside the selected resource directories.",
    )
    create_parser.add_argument("--display-name", help="Override agents/openai.yaml display_name.")
    create_parser.add_argument("--short-description", help="Override agents/openai.yaml short_description.")
    create_parser.add_argument("--default-prompt", help="Override agents/openai.yaml default_prompt.")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command in {"search", "find"}:
            return handle_search(args)
        if args.command in {"install", "download"}:
            return handle_install(args)
        if args.command == "auto-install":
            return handle_auto_install(args)
        if args.command in {"upload-check", "check-upload"}:
            return handle_upload_check(args)
        if args.command == "upload":
            return handle_upload(args)
        if args.command in {"create-check", "check-create"}:
            return handle_create_check(args)
        if args.command == "create":
            return handle_create(args)
        parser.error(f"Unsupported command: {args.command}")
        return 2
    except SkillError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


def resolve_repo(args: argparse.Namespace) -> Path:
    if getattr(args, "repo_path", None):
        return validate_repo_path(Path(args.repo_path))

    env_repo_path = os.environ.get(REPO_PATH_ENV)
    if env_repo_path:
        return validate_repo_path(Path(env_repo_path))

    local_repo = find_colocated_repo()
    if local_repo is not None:
        return local_repo

    cache_repo = default_cache_repo(args.cache_dir)
    return ensure_cached_repo(cache_repo, args.repo_url)


def validate_repo_path(repo_path: Path) -> Path:
    candidate = repo_path.expanduser().resolve()
    if not candidate.exists():
        raise SkillError(f"Repository path does not exist: {candidate}")
    if not candidate.is_dir():
        raise SkillError(f"Repository path is not a directory: {candidate}")
    if not (candidate / "skills").is_dir():
        raise SkillError(f"Repository path has no skills/ directory: {candidate}")
    return candidate


def find_colocated_repo() -> Path | None:
    script_path = Path(__file__).resolve()
    for candidate in [script_path.parent] + list(script_path.parents):
        if (candidate / ".git").exists() and (candidate / "skills").is_dir():
            return candidate
    return None


def default_cache_repo(cache_dir: str | None) -> Path:
    if cache_dir:
        return Path(cache_dir).expanduser().resolve() / "reallink-skills"

    if os.name == "nt":
        base_dir = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base_dir = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))

    return base_dir / "reallink-manage-skills" / "reallink-skills"


def ensure_cached_repo(cache_repo: Path, repo_url: str) -> Path:
    cache_repo.parent.mkdir(parents=True, exist_ok=True)

    if cache_repo.exists():
        if not (cache_repo / ".git").exists():
            raise SkillError(
                f"Cache path already exists but is not a Git repository: {cache_repo}"
            )
        if not (cache_repo / "skills").is_dir():
            raise SkillError(f"Cache repository has no skills/ directory: {cache_repo}")
        try:
            run_git(["-C", str(cache_repo), "pull", "--ff-only"])
        except SkillError as exc:
            print(
                f"[WARN] Failed to update cached repository; using existing cache. {exc}",
                file=sys.stderr,
            )
        return cache_repo

    run_git(["clone", "--depth", "1", repo_url, str(cache_repo)])
    return cache_repo


def run_git(arguments: list[str]) -> str:
    git = shutil.which("git")
    if not git:
        raise SkillError("git is required but was not found in PATH.")

    completed = subprocess.run(
        [git] + arguments,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise SkillError(message)
    return completed.stdout.strip()


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise SkillError(f"Unable to decode {path} as UTF-8.")


def parse_skill_markdown(content: str, fallback_name: str) -> tuple[str, str, str]:
    normalized = content.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return fallback_name, "", normalized

    closing_marker = normalized.find("\n---\n", 4)
    if closing_marker == -1:
        return fallback_name, "", normalized

    frontmatter = normalized[4:closing_marker]
    body = normalized[closing_marker + 5 :]
    name = fallback_name
    description = ""

    lines = frontmatter.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        name_match = re.match(r"^name:\s*(.*)$", line)
        if name_match:
            raw_value = name_match.group(1).strip()
            if raw_value:
                name = strip_quotes(raw_value)
            index += 1
            continue

        description_match = re.match(r"^description:\s*(.*)$", line)
        if description_match:
            raw_value = description_match.group(1).rstrip()
            if raw_value.strip() in {"|", "|-", ">", ">-"}:
                index += 1
                block_lines: list[str] = []
                while index < len(lines):
                    current = lines[index]
                    if current.startswith("  "):
                        block_lines.append(current[2:])
                        index += 1
                        continue
                    if current.startswith("\t"):
                        block_lines.append(current.lstrip("\t"))
                        index += 1
                        continue
                    if current == "":
                        block_lines.append("")
                        index += 1
                        continue
                    break
                description = "\n".join(block_lines).strip()
                continue

            description = strip_quotes(raw_value.strip())

        index += 1

    return name, description, body


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def extract_headings(body: str) -> str:
    headings = re.findall(r"^#{1,6}\s+(.*)$", body, re.MULTILINE)
    return " ".join(headings)


def load_skill_profile(skill_dir: Path) -> SkillProfile:
    skill_md = skill_dir / "SKILL.md"
    content = read_text(skill_md)
    name, description, body = parse_skill_markdown(content, skill_dir.name)
    top_level_entries = {
        child.name
        for child in skill_dir.iterdir()
        if child.name not in {".git", ".gitignore"}
    }
    return SkillProfile(
        folder_name=skill_dir.name,
        name=name or skill_dir.name,
        description=description,
        path=skill_dir,
        body=body,
        headings=extract_headings(body),
        top_level_entries=top_level_entries,
    )


def load_repo_skills(repo_path: Path) -> list[SkillProfile]:
    skills_dir = repo_path / "skills"
    skill_dirs = sorted(child for child in skills_dir.iterdir() if child.is_dir())
    if not skill_dirs:
        raise SkillError(f"No skills were found under {skills_dir}")
    profiles: list[SkillProfile] = []
    for skill_dir in skill_dirs:
        if (skill_dir / "SKILL.md").exists():
            profiles.append(load_skill_profile(skill_dir))
    return profiles


def load_local_skill(skill_name: str, project_root: str, source_dir: str | None) -> SkillProfile:
    if source_dir:
        skills_root = Path(source_dir).expanduser().resolve()
    else:
        skills_root = Path(project_root).expanduser().resolve() / ".claude" / "skills"

    if not skills_root.exists():
        raise SkillError(f"Source skills directory does not exist: {skills_root}")
    if not skills_root.is_dir():
        raise SkillError(f"Source skills path is not a directory: {skills_root}")

    skill_path = skills_root / skill_name
    if not skill_path.exists():
        raise SkillError(f"Skill directory does not exist: {skill_path}")
    if not skill_path.is_dir():
        raise SkillError(f"Skill path is not a directory: {skill_path}")
    return load_skill_profile(skill_path)


def resolve_local_skills_dir(local_skills_dir: str | None, project_root: str) -> Path:
    if local_skills_dir:
        return Path(local_skills_dir).expanduser().resolve()
    return Path(project_root).expanduser().resolve() / ".claude" / "skills"


def normalize_skill_name(raw_name: str) -> str:
    normalized = raw_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    if not normalized:
        raise SkillError("Skill name must include at least one letter or digit.")
    return normalized


def tokenize(text: str) -> set[str]:
    lower_text = text.lower()
    tokens: set[str] = set()

    for match in re.finditer(r"[a-z0-9][a-z0-9+._/-]*", lower_text):
        token = match.group(0).strip("._/-")
        if len(token) < 2 and not token.isdigit():
            continue
        if token in ENGLISH_STOPWORDS:
            continue
        tokens.add(token)

    for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if sequence not in CHINESE_STOPWORDS:
            tokens.add(sequence)
        if len(sequence) > 2:
            for index in range(len(sequence) - 1):
                piece = sequence[index : index + 2]
                if piece not in CHINESE_STOPWORDS:
                    tokens.add(piece)

    return tokens


def total_weight(tokens: set[str]) -> float:
    return sum(token_weight(token) for token in tokens)


def token_weight(token: str) -> float:
    if re.search(r"[\u4e00-\u9fff]", token):
        return min(6.0, 1.0 + len(token) * 0.9)
    return min(6.0, max(1.0, len(token) * 0.5))


def compress_terms(terms: set[str]) -> list[str]:
    ordered = sorted(terms, key=lambda term: (-token_weight(term), -len(term), term))
    selected: list[str] = []
    for term in ordered:
        if any(term != existing and term in existing for existing in selected):
            continue
        selected.append(term)
    return selected


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def normalize_identifier(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def shorten_line(text: str, width: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= width:
        return compact
    return compact[: width - 3].rstrip() + "..."


def score_query_against_skill(query: str, skill: SkillProfile) -> tuple[float, list[str]]:
    query_tokens = tokenize(query)
    if not query_tokens:
        query_tokens = {normalize_text(query)}

    name_tokens = tokenize(skill.name)
    summary_text = f"{skill.name} {skill.description}"
    summary_tokens = tokenize(summary_text)
    document_tokens = tokenize(f"{summary_text} {skill.headings}")

    overlap = query_tokens & document_tokens
    query_weight = total_weight(query_tokens)
    overlap_weight = total_weight(overlap)
    coverage = overlap_weight / query_weight if query_weight else 0.0
    name_bonus = total_weight(overlap & name_tokens) / query_weight if query_weight else 0.0
    summary_bonus = total_weight(overlap & summary_tokens) / query_weight if query_weight else 0.0
    sequence_ratio = SequenceMatcher(
        None,
        normalize_text(query),
        normalize_text(f"{summary_text} {skill.headings}"),
    ).ratio()

    score = (
        0.55 * coverage
        + 0.15 * summary_bonus
        + 0.10 * name_bonus
        + 0.20 * sequence_ratio
    )
    return min(score, 1.0), compress_terms(overlap)[:8]


def search_repo(repo_path: Path, query: str, limit: int, min_score: float) -> list[SearchResult]:
    query = query.strip()
    if not query:
        raise SkillError("Query cannot be empty.")

    results: list[SearchResult] = []
    for skill in load_repo_skills(repo_path):
        score, matched_terms = score_query_against_skill(query, skill)
        if score >= min_score:
            results.append(SearchResult(skill=skill, score=score, matched_terms=matched_terms))

    results.sort(key=lambda item: (-item.score, item.skill.folder_name))
    return results[: max(limit, 1)]


def install_skill(repo_path: Path, skill_name: str, project_root: Path, force: bool) -> Path:
    source = repo_path / "skills" / skill_name
    if not source.is_dir():
        raise SkillError(f"Skill '{skill_name}' was not found under {repo_path / 'skills'}")

    destination_root = project_root.expanduser().resolve()
    if not destination_root.exists():
        raise SkillError(f"Project root does not exist: {destination_root}")
    if not destination_root.is_dir():
        raise SkillError(f"Project root is not a directory: {destination_root}")

    target = destination_root / ".claude" / "skills" / skill_name
    if target.exists():
        if not force:
            raise SkillError(f"Target already exists: {target}. Use --force to replace it.")
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=IGNORED_COPY_PATTERNS)
    return target


def handle_search(args: argparse.Namespace) -> int:
    repo_path = resolve_repo(args)
    results = search_repo(repo_path, args.query, args.limit, args.min_score)
    payload = {
        "repo_path": str(repo_path),
        "query": args.query,
        "results": [search_result_to_dict(result) for result in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Repository: {repo_path}")
        print(f"Query: {args.query}")
        if not results:
            print("No matching skills found.")
        else:
            print("Matches:")
            for index, result in enumerate(results, start=1):
                print(f"{index}. {result.skill.folder_name} (score={result.score:.2f})")
                if result.skill.description:
                    print(f"   Description: {shorten_line(result.skill.description, 140)}")
                if result.matched_terms:
                    print(f"   Matched terms: {', '.join(result.matched_terms)}")
                print(f"   Path: {result.skill.path}")
    return 0 if results else 1


def handle_install(args: argparse.Namespace) -> int:
    repo_path = resolve_repo(args)
    install_path = install_skill(repo_path, args.skill, Path(args.project_root), args.force)
    payload = {
        "skill": args.skill,
        "installed_to": str(install_path),
        "repo_path": str(repo_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Installed skill: {args.skill}")
        print(f"Installed to: {install_path}")
        print(f"Source repo: {repo_path}")
    return 0


def handle_auto_install(args: argparse.Namespace) -> int:
    repo_path = resolve_repo(args)
    results = search_repo(repo_path, args.query, args.limit, 0.0)
    if not results:
        raise SkillError("No skills found in the repository.")

    filtered = [result for result in results if result.score >= args.min_score]
    if not filtered:
        payload = {
            "repo_path": str(repo_path),
            "query": args.query,
            "reason": f"No match met the minimum score {args.min_score:.2f}.",
            "results": [search_result_to_dict(result) for result in results],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(payload["reason"])
        return 1

    best = filtered[0]
    second = filtered[1] if len(filtered) > 1 else None
    if second and (best.score - second.score) < args.min_gap:
        reason = (
            f"Best match is ambiguous: {best.skill.folder_name} leads {second.skill.folder_name} "
            f"by {best.score - second.score:.2f}, below the required gap {args.min_gap:.2f}."
        )
        payload = {
            "repo_path": str(repo_path),
            "query": args.query,
            "reason": reason,
            "results": [search_result_to_dict(result) for result in filtered],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(reason)
        return 1

    install_path = install_skill(repo_path, best.skill.folder_name, Path(args.project_root), args.force)
    payload = {
        "repo_path": str(repo_path),
        "query": args.query,
        "installed_skill": best.skill.folder_name,
        "install_path": str(install_path),
        "results": [search_result_to_dict(result) for result in filtered],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Installed best match: {best.skill.folder_name}")
        print(f"Installed to: {install_path}")
    return 0


def search_result_to_dict(result: SearchResult) -> dict[str, object]:
    return {
        "skill": result.skill.folder_name,
        "name": result.skill.name,
        "description": result.skill.description,
        "score": round(result.score, 4),
        "matched_terms": result.matched_terms,
        "path": str(result.skill.path),
    }


def compare_skill_profiles(source: SkillProfile, target: SkillProfile, scope: str) -> MatchResult:
    exact_folder_name = normalize_identifier(source.folder_name) == normalize_identifier(target.folder_name)
    exact_frontmatter_name = normalize_identifier(source.name) == normalize_identifier(target.name)

    source_tokens = tokenize(f"{source.name} {source.description} {source.headings}")
    target_tokens = tokenize(f"{target.name} {target.description} {target.headings}")
    overlap = source_tokens & target_tokens
    overlap_weight = total_weight(overlap)
    source_weight = total_weight(source_tokens)
    target_weight = total_weight(target_tokens)
    symmetric_overlap = 0.0
    if source_weight and target_weight:
        symmetric_overlap = 0.5 * ((overlap_weight / source_weight) + (overlap_weight / target_weight))

    name_ratio = max(
        SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()
        for left in {source.folder_name, source.name}
        for right in {target.folder_name, target.name}
    )
    description_ratio = SequenceMatcher(
        None,
        normalize_text(source.description),
        normalize_text(target.description),
    ).ratio()
    heading_ratio = SequenceMatcher(
        None,
        normalize_text(source.headings),
        normalize_text(target.headings),
    ).ratio()

    if exact_folder_name or exact_frontmatter_name:
        score = 1.0
    else:
        score = (
            0.42 * symmetric_overlap
            + 0.26 * name_ratio
            + 0.18 * description_ratio
            + 0.14 * heading_ratio
        )
        score = min(score, 0.999)

    return MatchResult(
        skill=target,
        scope=scope,
        score=score,
        exact_folder_name=exact_folder_name,
        exact_frontmatter_name=exact_frontmatter_name,
        matched_terms=compress_terms(overlap)[:8],
    )


def compare_local_skill_to_repo(source_skill: SkillProfile, repo_path: Path, limit: int) -> list[MatchResult]:
    results: list[MatchResult] = []
    source_real = source_skill.path.resolve()
    for target in load_repo_skills(repo_path):
        if target.path.resolve() == source_real:
            continue
        results.append(compare_skill_profiles(source_skill, target, "repo"))
    results.sort(key=lambda item: (-item.score, item.skill.folder_name))
    return results[: max(limit, 1)]


def classify_upload_decision(
    source_skill: SkillProfile,
    repo_path: Path,
    results: list[MatchResult],
    similar_threshold: float,
) -> SubmissionDecision:
    source_repo_parent = source_skill.path.parent.parent if source_skill.path.parent.name == "skills" else None
    if source_repo_parent and source_repo_parent.name == "reallink-skills":
        return SubmissionDecision(
            blocked=True,
            reason="Source skill already lives inside a reallink-skills repository.",
            action=None,
            target_path=None,
        )

    exact_target = None
    best_similar = None
    for result in results:
        if result.exact_folder_name:
            exact_target = result
            break
        if result.exact_frontmatter_name and exact_target is None:
            exact_target = result
        if best_similar is None and result.score >= similar_threshold:
            best_similar = result

    if exact_target is not None:
        if exact_target.exact_folder_name:
            return SubmissionDecision(
                blocked=False,
                reason=None,
                action="Update",
                target_path=exact_target.skill.path,
            )
        return SubmissionDecision(
            blocked=True,
            reason=(
                f"Repository already contains the same frontmatter name in a different folder: "
                f"{exact_target.skill.folder_name}."
            ),
            action=None,
            target_path=None,
        )

    if best_similar is not None:
        return SubmissionDecision(
            blocked=True,
            reason=(
                f"Found similar skill '{best_similar.skill.folder_name}' with score "
                f"{best_similar.score:.2f}, meeting the block threshold {similar_threshold:.2f}."
            ),
            action=None,
            target_path=None,
        )

    return SubmissionDecision(
        blocked=False,
        reason=None,
        action="Create",
        target_path=repo_path / "skills" / source_skill.folder_name,
    )


def copy_skill_to_repo(source_skill: SkillProfile, destination: Path, replace_existing: bool) -> Path:
    if destination.exists():
        if not replace_existing:
            raise SkillError(f"Target path already exists: {destination}")
        shutil.rmtree(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill.path, destination, ignore=IGNORED_COPY_PATTERNS)
    return destination


def has_repo_changes(repo_path: Path, destination: Path) -> bool:
    relative_path = destination.relative_to(repo_path)
    status_output = run_git(["-C", str(repo_path), "status", "--porcelain", "--", str(relative_path)])
    return bool(status_output.strip())


def stage_in_git(repo_path: Path, destination: Path) -> None:
    if not (repo_path / ".git").exists():
        raise SkillError(f"Repository has no .git directory: {repo_path}")
    relative_path = destination.relative_to(repo_path)
    run_git(["-C", str(repo_path), "add", "--", str(relative_path)])


def build_commit_message(source_skill: SkillProfile, action: str, repo_path: Path, destination: Path) -> str:
    if action == "Create":
        detail = compact_sentence(source_skill.description or "Create new skill files.")
    else:
        detail = summarize_changed_content(repo_path, destination) or compact_sentence(source_skill.description or "Update skill content.")
    return f"[{source_skill.folder_name}][{action}] {detail}"


def summarize_changed_content(repo_path: Path, destination: Path) -> str:
    relative_path = destination.relative_to(repo_path)
    diff_output = run_git(["-C", str(repo_path), "diff", "--name-only", "--", str(relative_path)])
    untracked_output = run_git(
        ["-C", str(repo_path), "ls-files", "--others", "--exclude-standard", "--", str(relative_path)]
    )
    prefix = relative_path.as_posix().rstrip("/") + "/"
    files: list[str] = []
    seen: set[str] = set()
    for output in (diff_output, untracked_output):
        for raw_line in output.splitlines():
            normalized = raw_line.strip().replace("\\", "/")
            if not normalized:
                continue
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
            normalized = normalized.strip("/")
            if not normalized:
                continue
            if normalized not in seen:
                seen.add(normalized)
                files.append(normalized)

    filtered = [path for path in files if "__pycache__/" not in path and not path.endswith(".pyc")]
    files = filtered or files
    if not files:
        return ""
    if len(files) == 1:
        return compact_sentence(f"Update {files[0]}.")
    if len(files) == 2:
        return compact_sentence(f"Update {files[0]} and {files[1]}.")
    return compact_sentence(f"Update {files[0]}, {files[1]}, and {len(files) - 2} more files.")


def compact_sentence(text: str) -> str:
    compact = " ".join(text.split()).strip()
    if not compact:
        return ""
    if len(compact) > 120:
        compact = compact[:117].rstrip() + "..."
    if compact.endswith((".", "!", "?")):
        return compact
    return compact + "."


def commit_skill(repo_path: Path, destination: Path, commit_message: str) -> str:
    stage_in_git(repo_path, destination)
    relative_path = destination.relative_to(repo_path)
    run_git(["-C", str(repo_path), "commit", "--only", "-m", commit_message, "--", str(relative_path)])
    return run_git(["-C", str(repo_path), "rev-parse", "HEAD"])


def push_current_branch(repo_path: Path) -> str:
    branch = run_git(["-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"])
    if not branch or branch == "HEAD":
        raise SkillError("Cannot push from a detached HEAD state.")
    try:
        upstream = run_git(["-C", str(repo_path), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
        run_git(["-C", str(repo_path), "push"])
        return upstream
    except SkillError:
        remotes = {line.strip() for line in run_git(["-C", str(repo_path), "remote"]).splitlines() if line.strip()}
        if "origin" not in remotes:
            raise SkillError("No upstream is configured and origin remote is missing.")
        run_git(["-C", str(repo_path), "push", "-u", "origin", branch])
        return f"origin/{branch}"


def handle_upload_check(args: argparse.Namespace) -> int:
    repo_path = resolve_repo(args)
    source_skill = load_local_skill(args.skill, args.project_root, args.source_dir)
    results = compare_local_skill_to_repo(source_skill, repo_path, args.limit)
    decision = classify_upload_decision(source_skill, repo_path, results, args.similar_threshold)
    payload = {
        "source_skill": source_skill.folder_name,
        "source_path": str(source_skill.path),
        "repo_path": str(repo_path),
        "blocked": decision.blocked,
        "reason": decision.reason,
        "action": decision.action,
        "target_path": str(decision.target_path) if decision.target_path else None,
        "results": [match_result_to_dict(result) for result in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Source skill: {source_skill.folder_name}")
        print(f"Source path: {source_skill.path}")
        print(f"Repository: {repo_path}")
        print("Status: BLOCKED" if decision.blocked else f"Status: READY ({decision.action})")
        if decision.reason:
            print(f"Reason: {decision.reason}")
    return 1 if decision.blocked else 0


def handle_upload(args: argparse.Namespace) -> int:
    repo_path = resolve_repo(args)
    source_skill = load_local_skill(args.skill, args.project_root, args.source_dir)
    results = compare_local_skill_to_repo(source_skill, repo_path, args.limit)
    decision = classify_upload_decision(source_skill, repo_path, results, args.similar_threshold)
    if decision.blocked or decision.target_path is None or decision.action is None:
        payload = {
            "source_skill": source_skill.folder_name,
            "source_path": str(source_skill.path),
            "repo_path": str(repo_path),
            "blocked": True,
            "reason": decision.reason,
            "results": [match_result_to_dict(result) for result in results],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("Submit cancelled.")
            if decision.reason:
                print(f"Reason: {decision.reason}")
        return 1

    destination = copy_skill_to_repo(source_skill, decision.target_path, replace_existing=decision.action == "Update")
    if not has_repo_changes(repo_path, destination):
        raise SkillError("No file changes detected after syncing the skill.")

    commit_message = build_commit_message(source_skill, decision.action, repo_path, destination)
    commit_hash = None
    push_target = None
    if not args.no_commit:
        commit_hash = commit_skill(repo_path, destination, commit_message)
        if not args.no_push:
            push_target = push_current_branch(repo_path)

    payload = {
        "source_skill": source_skill.folder_name,
        "source_path": str(source_skill.path),
        "repo_path": str(repo_path),
        "action": decision.action,
        "destination": str(destination),
        "committed": not args.no_commit,
        "commit_message": commit_message if not args.no_commit else None,
        "commit_hash": commit_hash,
        "pushed": (not args.no_commit and not args.no_push),
        "push_target": push_target,
        "results": [match_result_to_dict(result) for result in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Action: {decision.action}")
        print(f"Synced to: {destination}")
        if not args.no_commit:
            print(f"Committed: {commit_message}")
            if commit_hash:
                print(f"Commit: {commit_hash}")
            if not args.no_push:
                print(f"Pushed to: {push_target}")
            else:
                print("Push skipped.")
        else:
            print("Commit skipped.")
    return 0


def match_result_to_dict(result: MatchResult) -> dict[str, object]:
    return {
        "skill": result.skill.folder_name,
        "name": result.skill.name,
        "description": result.skill.description,
        "path": str(result.skill.path),
        "scope": result.scope,
        "score": round(result.score, 4),
        "exact_folder_name": result.exact_folder_name,
        "exact_frontmatter_name": result.exact_frontmatter_name,
        "matched_terms": result.matched_terms,
    }


def compare_proposed_skill(
    proposed_name: str,
    request: str,
    proposed_tokens: set[str],
    skill: SkillProfile,
    scope: str,
) -> MatchResult:
    exact_folder_name = normalize_identifier(proposed_name) == normalize_identifier(skill.folder_name)
    exact_frontmatter_name = normalize_identifier(proposed_name) == normalize_identifier(skill.name)

    summary_text = f"{skill.name} {skill.description} {skill.headings}"
    summary_tokens = tokenize(summary_text)
    name_tokens = tokenize(skill.name)
    overlap = proposed_tokens & summary_tokens
    proposed_weight = total_weight(proposed_tokens)
    overlap_weight = total_weight(overlap)
    coverage = overlap_weight / proposed_weight if proposed_weight else 0.0
    name_bonus = total_weight(overlap & name_tokens) / proposed_weight if proposed_weight else 0.0
    summary_bonus = total_weight(overlap & tokenize(f"{skill.name} {skill.description}")) / proposed_weight if proposed_weight else 0.0
    phrase_ratio = SequenceMatcher(
        None,
        normalize_text(f"{proposed_name} {request}"),
        normalize_text(summary_text),
    ).ratio()

    if exact_folder_name or exact_frontmatter_name:
        score = 1.0
    else:
        score = (
            0.55 * coverage
            + 0.20 * summary_bonus
            + 0.15 * name_bonus
            + 0.10 * phrase_ratio
        )
        score = min(score, 0.999)

    return MatchResult(
        skill=skill,
        scope=scope,
        score=score,
        exact_folder_name=exact_folder_name,
        exact_frontmatter_name=exact_frontmatter_name,
        matched_terms=compress_terms(overlap)[:8],
    )


def collect_proposed_matches(skill_name: str, request: str, skills_root: Path, scope: str, limit: int) -> list[MatchResult]:
    root = skills_root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []

    proposed_name = normalize_skill_name(skill_name)
    proposed_tokens = tokenize(f"{proposed_name} {request}")
    results: list[MatchResult] = []

    for skill_dir in sorted(child for child in root.iterdir() if child.is_dir()):
        if not (skill_dir / "SKILL.md").exists():
            continue
        profile = load_skill_profile(skill_dir)
        results.append(compare_proposed_skill(proposed_name, request, proposed_tokens, profile, scope))

    results.sort(key=lambda item: (-item.score, item.skill.folder_name))
    return results[: max(limit, 1)]


def first_exact_match(results: list[MatchResult]) -> MatchResult | None:
    for result in results:
        if result.exact_folder_name or result.exact_frontmatter_name:
            return result
    return None


def first_similar_match(results: list[MatchResult], threshold: float) -> MatchResult | None:
    for result in results:
        if result.score >= threshold:
            return result
    return None


def classify_create_outcome(
    skill_name: str,
    local_skills_dir: Path,
    repo_path: Path,
    local_results: list[MatchResult],
    repo_results: list[MatchResult],
    similar_threshold: float,
) -> CreateOutcome:
    normalized_name = normalize_skill_name(skill_name)
    target_path = local_skills_dir / normalized_name

    if target_path.exists():
        return CreateOutcome(
            blocked=True,
            reason=f"Local skill directory already exists: {target_path}",
            recommendation="Reuse or update the existing local skill instead of creating a duplicate.",
            scope="local",
            match=None,
            target_path=target_path,
        )

    repo_exact = first_exact_match(repo_results)
    if repo_exact is not None:
        return CreateOutcome(
            blocked=True,
            reason=f"Found matching skill in reallink-skills: {repo_exact.skill.folder_name}",
            recommendation=(
                f"Download or install '{repo_exact.skill.folder_name}' from reallink-skills instead of creating a duplicate."
            ),
            scope="repo",
            match=repo_exact,
            target_path=target_path,
        )

    local_exact = first_exact_match(local_results)
    if local_exact is not None:
        return CreateOutcome(
            blocked=True,
            reason=f"Found matching local skill: {local_exact.skill.folder_name}",
            recommendation="Reuse or update the existing local skill instead of creating a duplicate.",
            scope="local",
            match=local_exact,
            target_path=target_path,
        )

    repo_similar = first_similar_match(repo_results, similar_threshold)
    if repo_similar is not None:
        return CreateOutcome(
            blocked=True,
            reason=(
                f"Found similar skill in reallink-skills: {repo_similar.skill.folder_name} "
                f"(score={repo_similar.score:.2f})"
            ),
            recommendation=(
                f"Download or review '{repo_similar.skill.folder_name}' from reallink-skills instead of creating a new skill."
            ),
            scope="repo",
            match=repo_similar,
            target_path=target_path,
        )

    local_similar = first_similar_match(local_results, similar_threshold)
    if local_similar is not None:
        return CreateOutcome(
            blocked=True,
            reason=(
                f"Found similar local skill: {local_similar.skill.folder_name} "
                f"(score={local_similar.score:.2f})"
            ),
            recommendation="Update the existing local skill instead of creating a near-duplicate.",
            scope="local",
            match=local_similar,
            target_path=target_path,
        )

    return CreateOutcome(
        blocked=False,
        reason=None,
        recommendation=None,
        scope=None,
        match=None,
        target_path=target_path,
    )


def resolve_skill_creator_init_script() -> Path:
    candidates: list[Path] = []
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "skills" / ".system" / "skill-creator" / "scripts" / "init_skill.py")
    for home_subdir in (".codex", ".Codex"):
        candidates.append(Path.home() / home_subdir / "skills" / ".system" / "skill-creator" / "scripts" / "init_skill.py")
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise SkillError("Could not locate skill-creator/scripts/init_skill.py in the local Codex installation.")


def create_local_skill(args: argparse.Namespace, local_skills_dir: Path) -> tuple[Path, str]:
    init_script = resolve_skill_creator_init_script()
    normalized_name = normalize_skill_name(args.skill_name)
    command = [sys.executable, str(init_script), normalized_name, "--path", str(local_skills_dir)]
    if args.resources:
        command.extend(["--resources", args.resources])
    if args.examples:
        command.append("--examples")
    if args.display_name:
        command.extend(["--interface", f"display_name={args.display_name}"])
    if args.short_description:
        command.extend(["--interface", f"short_description={args.short_description}"])
    if args.default_prompt:
        command.extend(["--interface", f"default_prompt={args.default_prompt}"])

    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "init_skill.py failed"
        raise SkillError(message)

    created_path = local_skills_dir / normalized_name
    if not created_path.exists():
        raise SkillError(f"skill-creator reported success but the skill was not created: {created_path}")
    return created_path, completed.stdout.strip()


def handle_create_check(args: argparse.Namespace) -> int:
    repo_path = resolve_repo(args)
    local_skills_dir = resolve_local_skills_dir(args.local_skills_dir, args.project_root)
    local_results = collect_proposed_matches(args.skill_name, args.request, local_skills_dir, "local", args.limit)
    repo_results = collect_proposed_matches(args.skill_name, args.request, repo_path / "skills", "repo", args.limit)
    outcome = classify_create_outcome(
        args.skill_name,
        local_skills_dir,
        repo_path,
        local_results,
        repo_results,
        args.similar_threshold,
    )
    payload = {
        "skill_name": normalize_skill_name(args.skill_name),
        "target_path": str(outcome.target_path),
        "local_skills_dir": str(local_skills_dir),
        "repo_path": str(repo_path),
        "blocked": outcome.blocked,
        "reason": outcome.reason,
        "recommendation": outcome.recommendation,
        "local_matches": [match_result_to_dict(result) for result in local_results],
        "repo_matches": [match_result_to_dict(result) for result in repo_results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Planned skill: {normalize_skill_name(args.skill_name)}")
        print(f"Target path: {outcome.target_path}")
        print("Status: BLOCKED" if outcome.blocked else "Status: CLEAR")
        if outcome.reason:
            print(f"Reason: {outcome.reason}")
        if outcome.recommendation:
            print(f"Recommendation: {outcome.recommendation}")
    return 1 if outcome.blocked else 0


def handle_create(args: argparse.Namespace) -> int:
    repo_path = resolve_repo(args)
    local_skills_dir = resolve_local_skills_dir(args.local_skills_dir, args.project_root)
    local_results = collect_proposed_matches(args.skill_name, args.request, local_skills_dir, "local", args.limit)
    repo_results = collect_proposed_matches(args.skill_name, args.request, repo_path / "skills", "repo", args.limit)
    outcome = classify_create_outcome(
        args.skill_name,
        local_skills_dir,
        repo_path,
        local_results,
        repo_results,
        args.similar_threshold,
    )
    if outcome.blocked:
        payload = {
            "skill_name": normalize_skill_name(args.skill_name),
            "created": False,
            "reason": outcome.reason,
            "recommendation": outcome.recommendation,
            "local_matches": [match_result_to_dict(result) for result in local_results],
            "repo_matches": [match_result_to_dict(result) for result in repo_results],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("Create cancelled.")
            if outcome.reason:
                print(f"Reason: {outcome.reason}")
            if outcome.recommendation:
                print(f"Recommendation: {outcome.recommendation}")
        return 1

    created_path, init_output = create_local_skill(args, local_skills_dir)
    payload = {
        "skill_name": normalize_skill_name(args.skill_name),
        "created": True,
        "created_path": str(created_path),
        "ask_upload": "是否需要我立即使用 reallink-upload-skills 把这个新 skill 上传到 reallink-skills 仓库？",
        "init_output": init_output,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Created skill: {created_path}")
        print("Next step: fill the generated SKILL.md and replace the TODO placeholders.")
        print("Ask user: 是否需要我立即使用 reallink-upload-skills 把这个新 skill 上传到 reallink-skills 仓库？")
    return 0


if __name__ == "__main__":
    sys.exit(main())
