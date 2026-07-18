"""Agent Skills manager – Anthropic Agent Skills progressive disclosure.

Spec: https://agentskills.io/specification
Flow: Discovery → Activation → Execution
"""

import os
import sys
import logging
import yaml
import utils

from dataclasses import dataclass
from langchain_core.tools import tool
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)s:%(lineno)d | %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("skill")

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(WORKING_DIR, "skills")
ARTIFACTS_DIR = os.path.join(WORKING_DIR, "artifacts")

config = utils.load_config()


@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    path: str


class SkillManager:
    """Discovers, loads and selects Agent Skills following the Anthropic spec."""

    def __init__(self, skills_dir: str = SKILLS_DIR):
        self.skills_dir = skills_dir
        self.registry: dict[str, Skill] = {}
        self._discover(skills_dir)

    def _discover(self, skills_dir: str):
        """Scan a skills directory and load metadata into registry."""
        if not os.path.isdir(skills_dir):
            logger.info(f"skills directory is not found: {skills_dir}")
            return

        for entry in os.listdir(skills_dir):
            skill_md = os.path.join(skills_dir, entry, "SKILL.md")
            if os.path.isfile(skill_md):
                try:
                    meta, instructions = self._parse_skill_md(skill_md)
                    skill = Skill(
                        name=meta.get("name", entry),
                        description=meta.get("description", ""),
                        instructions=instructions,
                        path=os.path.join(skills_dir, entry),
                    )
                    self.registry[skill.name] = skill
                    logger.info(f"Skill discovered: {skill.name}")
                except Exception as e:
                    logger.warning(f"Failed to load skill '{entry}': {e}")

    @staticmethod
    def _parse_skill_md(filepath: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + markdown body from a SKILL.md file."""
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        if not raw.startswith("---"):
            return {}, raw

        parts = raw.split("---", 2)
        if len(parts) < 3:
            return {}, raw

        frontmatter = yaml.safe_load(parts[1]) or {}
        body = parts[2].strip()
        return frontmatter, body

    def get_skill_instructions(self, name: str) -> Optional[str]:
        """Return full instructions for a skill (loaded on demand)."""
        skill = self.registry.get(name)
        return skill.instructions if skill else None


skill_manager: Optional[SkillManager] = None


def _get_manager() -> SkillManager:
    global skill_manager
    if skill_manager is None:
        skill_manager = SkillManager(SKILLS_DIR)
    return skill_manager


def get_skills_xml(skill_info: list) -> str:
    lines = ["<available_skills>"]
    for s in skill_info:
        lines.append("  <skill>")
        lines.append(f"    <name>{s['name']}</name>")
        lines.append(f"    <description>{s['description']}</description>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def get_skill_info(skill_list: list) -> list:
    registry = _get_manager().registry
    if not registry:
        return []

    skill_info = []
    for s in registry.values():
        if s.name in skill_list:
            skill_info.append({"name": s.name, "description": s.description})
    return skill_info


def available_skill_info() -> list:
    registry = _get_manager().registry
    if not registry:
        return []
    return [{"name": s.name, "description": s.description} for s in registry.values()]


SKILL_SYSTEM_PROMPT = (
    "당신의 이름은 서연이고, 질문에 친근한 방식으로 대답하도록 설계된 대화형 AI입니다.\n"
    "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다.\n"
    "모르는 질문을 받으면 솔직히 모른다고 말합니다.\n"
    "한국어로 답변하세요.\n\n"
    "## Agent Workflow\n"
    "1. 사용자 입력을 받는다\n"
    "2. 요청에 맞는 skill이 있으면 get_skill_instructions 도구로 상세 지침을 로드한다\n"
    "3. skill 지침에 따라 execute_code, write_file, bash 등의 도구를 사용하여 작업을 수행한다\n"
    "4. 결과 파일이 있으면 upload_file_to_s3로 업로드하여 URL을 제공한다\n"
    "5. 최종 결과를 사용자에게 전달한다\n\n"
)

SKILL_USAGE_GUIDE = (
    "\n## Skill 사용 가이드\n"
    "위의 <available_skills>에 나열된 skill이 사용자의 요청과 관련될 때:\n"
    "1. 먼저 get_skill_instructions 도구로 해당 skill의 상세 지침을 로드하세요.\n"
    "2. **중요: 지침을 읽기 전에 어떤 작업을 할지 단정짓지 마세요.** "
    "skill의 description에 서브커맨드(query, path, explain 등)가 있다면, "
    "사용자 명령의 서브커맨드를 정확히 파악한 후 그에 맞는 동작을 설명하세요.\n"
    "3. 지침에 포함된 코드 패턴을 execute_code 또는 bash 도구로 실행하세요.\n"
)


def build_skill_prompt(skill_info: list) -> str:
    """Build skill-related prompt: path info, available skills XML, and usage guide."""
    path_info = (
        f"## Paths (use absolute paths for write_file, read_file)\n"
        f"- WORKING_DIR: {WORKING_DIR}\n"
        f"- ARTIFACTS_DIR: {ARTIFACTS_DIR}\n"
        f"Example: write_file(filepath='{os.path.join(ARTIFACTS_DIR, 'report.docx')}', content='...')\n\n"
    )

    skills_xml = get_skills_xml(skill_info)
    if skills_xml:
        return f"{SKILL_SYSTEM_PROMPT}\n{path_info}\n{skills_xml}\n{SKILL_USAGE_GUIDE}"
    return f"{SKILL_SYSTEM_PROMPT}\n{path_info}"


@tool
def get_skill_instructions(skill_name: str) -> str:
    """Load the full instructions for a specific skill by name.

    Use this when you need detailed instructions for a task that matches
    one of the available skills listed in the system prompt.

    Args:
        skill_name: The name of the skill to load (e.g. 'pdf', 'docx').

    Returns:
        The full skill instructions, or an error message if not found.
    """
    logger.info(f"###### get_skill_instructions: {skill_name} ######")
    manager = _get_manager()
    instructions = manager.get_skill_instructions(skill_name)
    if instructions:
        return instructions

    available = ", ".join(manager.registry.keys())
    return f"Skill '{skill_name}' not found. Available skills: {available}"


def get_skill_tools():
    """Return the list of skill tools for the skill-aware agent."""
    return [get_skill_instructions]
