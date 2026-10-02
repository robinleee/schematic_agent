"""
规则模板抽象基类与注册表

定义 Layer 1 的核心接口：
- RuleTemplate: 所有检查模板的抽象基类
- RuleContext: 模板执行上下文（Neo4j driver + graph_tools + knowledge_router）
- TemplateRegistry: 模板注册中心
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any

from agent_system.schemas import Violation


@dataclass
class RuleContext:
    """规则执行上下文"""
    neo4j_driver: Any
    project_id: str | None = None
    infrastructure_error: BaseException | None = field(default=None, init=False, repr=False)
    # 可选扩展
    # graph_tools: Any = None
    # knowledge_router: Any = None

    def run_query(self, query: str, params: dict | None = None):
        """Run a review query, applying project isolation when requested.

        Aggregate review keeps the original query and parameter set unchanged.
        A project-scoped review gets a predicate for every node variable in each
        MATCH/OPTIONAL MATCH clause.  If a query cannot be safely scoped, it
        fails closed instead of falling back to an aggregate read.
        """
        scoped_query, params = self._prepare_query(query, params)
        try:
            with self.neo4j_driver.session() as session:
                return list(session.run(scoped_query, params))
        except Exception as exc:
            self.infrastructure_error = exc
            raise

    def _prepare_query(self, query: str, params: dict | None = None):
        params = dict(params or {})
        if self.project_id is None:
            return query, params
        params["project_id"] = self.project_id
        try:
            return _scope_review_query(query), params
        except RuntimeError as exc:
            self.infrastructure_error = exc
            raise

    @property
    def scoped_driver(self):
        """Compatibility driver proxy for legacy template helper methods."""
        return _ScopedDriver(self)


class _ScopedSession:
    def __init__(self, context: RuleContext, session: Any):
        self._context = context
        self._session = session

    def __enter__(self):
        try:
            self._session.__enter__()
        except Exception as exc:
            self._context.infrastructure_error = exc
            raise
        return self

    def __exit__(self, *args):
        return self._session.__exit__(*args)

    def run(self, query: str, parameters: dict | None = None, **kwargs):
        if parameters is None:
            parameters = kwargs
        elif kwargs:
            parameters = {**parameters, **kwargs}
        scoped_query, scoped_params = self._context._prepare_query(query, parameters)
        try:
            return self._session.run(scoped_query, scoped_params)
        except Exception as exc:
            self._context.infrastructure_error = exc
            raise

    def __getattr__(self, name):
        return getattr(self._session, name)


class _ScopedDriver:
    def __init__(self, context: RuleContext):
        self._context = context

    def session(self, *args, **kwargs):
        try:
            raw_session = self._context.neo4j_driver.session(*args, **kwargs)
        except Exception as exc:
            self._context.infrastructure_error = exc
            raise
        return _ScopedSession(self._context, raw_session)


def _scope_review_query(query: str) -> str:
    """Add project predicates to all node patterns in MATCH clauses.

    The review templates use ordinary Cypher and a number of helper methods
    still receive a driver rather than RuleContext.  Scoping at this single
    boundary prevents a missed helper call from silently becoming global.
    """
    if not query or not re.search(r"\bMATCH\b", query, re.IGNORECASE):
        raise RuntimeError("Unsafe project-scoped review query: no MATCH clause")
    if re.search(
        r"\b(?:CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP)\b",
        query,
        re.IGNORECASE,
    ):
        raise RuntimeError("Unsafe project-scoped review query: writes are forbidden")

    # ``WITH`` is also an operator in ``STARTS WITH``.  Clause boundaries
    # must therefore be found only at the top level, not with a regex.
    clause_positions = _top_level_keyword_positions(
        query,
        ("OPTIONAL MATCH", "MATCH", "WITH", "RETURN", "UNWIND"),
    )
    clause_positions = [
        (position, keyword)
        for index, (position, keyword) in enumerate(clause_positions)
        if not (
            index > 0
            and keyword.upper() == "MATCH"
            and clause_positions[index - 1][1].upper() == "OPTIONAL MATCH"
            and position
            <= clause_positions[index - 1][0]
            + len(clause_positions[index - 1][1])
            + 1
        )
    ]
    matches = [
        (position, head)
        for position, head in clause_positions
        if head.upper() in ("MATCH", "OPTIONAL MATCH")
    ]
    if not matches:
        raise RuntimeError("Unsafe project-scoped review query")

    pieces = []
    cursor = 0
    changed = False
    for start, head in matches:
        end = len(query)
        for boundary, _keyword in clause_positions:
            if boundary > start:
                end = boundary
                break
        pieces.append(query[cursor:start])
        body = query[start + len(head):end]
        variables = []
        # A node pattern starts with ``(`` followed by a variable and then a
        # node-pattern delimiter.  In particular, do not treat identifiers in
        # expressions such as ``ANY(pattern IN $patterns ...)`` as variables:
        # the whitespace after ``pattern`` is followed by ``IN``, not by a
        # label, property map, or the closing node-pattern parenthesis.
        node_pattern_re = re.compile(
            r"\(\s*(?P<var>[A-Za-z_]\w*)\s*(?=[:{})])"
        )
        for node_match in node_pattern_re.finditer(body):
            var = node_match.group("var")
            if var not in variables:
                variables.append(var)
        if not variables:
            raise RuntimeError("Unsafe project-scoped review query: unscoped MATCH")
        predicate = " AND ".join(
            f"{var}.project_id = $project_id" for var in variables
        )
        # ``WHERE`` is also valid inside predicates such as
        # ``ANY(item IN $items WHERE ...)``.  Searching for the first WHERE
        # therefore corrupts the outer predicate (for example, it can turn
        # ``STARTS WITH`` into an invalid ``STARTS)`` fragment).  Only an
        # outer-clause WHERE may receive the project predicate.
        where = _find_top_level_keyword(body, "WHERE")
        if where:
            body = body[:where.start()] + f"WHERE {predicate} AND (" + body[where.end():].rstrip() + ")\n"
        else:
            body = body.rstrip() + f"\nWHERE {predicate}\n"
        pieces.append(head + body)
        cursor = end
        changed = True
    pieces.append(query[cursor:])
    if not changed:
        raise RuntimeError("Unsafe project-scoped review query")
    return "".join(pieces)


def _find_top_level_keyword(text: str, keyword: str) -> re.Match | None:
    """Find a keyword outside Cypher grouping expressions and string literals."""
    keyword_re = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
    depth_paren = 0
    depth_bracket = 0
    quote: str | None = None
    escaped = False

    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        if char == "(":
            depth_paren += 1
            index += 1
            continue
        if char == ")":
            depth_paren = max(0, depth_paren - 1)
            index += 1
            continue
        if char == "[":
            depth_bracket += 1
            index += 1
            continue
        if char == "]":
            depth_bracket = max(0, depth_bracket - 1)
            index += 1
            continue
        if depth_paren or depth_bracket:
            index += 1
            continue
        match = keyword_re.match(text, index)
        if match:
            return match
        index += 1
    return None


def _top_level_keyword_positions(
    text: str,
    keywords: tuple[str, ...],
) -> list[tuple[int, str]]:
    """Return keyword positions outside Cypher grouping and string literals."""
    keyword_re = re.compile(
        "|".join(
            rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])"
            for keyword in sorted(keywords, key=len, reverse=True)
        ),
        re.IGNORECASE,
    )
    positions: list[tuple[int, str]] = []
    depth_paren = 0
    depth_bracket = 0
    quote: str | None = None
    escaped = False
    previous_word: str | None = None

    for index, char in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            previous_word = None
            continue
        if char == "(":
            depth_paren += 1
            previous_word = None
            continue
        if char == ")":
            depth_paren = max(0, depth_paren - 1)
            previous_word = None
            continue
        if char == "[":
            depth_bracket += 1
            previous_word = None
            continue
        if char == "]":
            depth_bracket = max(0, depth_bracket - 1)
            previous_word = None
            continue
        if depth_paren or depth_bracket:
            continue
        match = keyword_re.match(text, index)
        if (match and (not positions or
                       positions[-1][0] + len(positions[-1][1]) <= index)
                and not (match.group().upper() == "WITH" and previous_word == "STARTS")):
            positions.append((index, match.group()))
        # Remember only top-level words: a quoted ``'STARTS'`` must not
        # suppress a real WITH clause, while STARTS WITH is one operator.
        if (char.isalpha() or char == "_") and (
            index == 0 or not (text[index - 1].isalnum() or text[index - 1] == "_")
        ):
            previous_word = re.match(r"[A-Za-z_]\w*", text[index:]).group().upper()
        elif not char.isspace() and not (char.isalnum() or char == "_"):
            previous_word = None
    if quote or depth_paren or depth_bracket:
        raise RuntimeError("Unsafe project-scoped review query: unterminated expression")
    return positions


class RuleTemplate(ABC):
    """
    规则模板抽象基类

    子类必须实现：
    - template_id: str  模板唯一标识
    - name: str          模板名称
    - description: str   模板描述
    - check(): 执行检查，返回 Violation 列表
    """

    template_id: str = ""
    name: str = ""
    description: str = ""
    default_severity: str = "WARNING"

    @abstractmethod
    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        """
        执行规则检查

        Args:
            params: 规则参数（来自 YAML/JSON 配置）
            context: 执行上下文（含 Neo4j driver 等）

        Returns:
            违规列表，空列表表示无违规
        """
        pass

    def validate_params(self, params: dict) -> bool:
        """验证参数合法性，默认始终通过"""
        return True


class TemplateRegistry:
    """规则模板注册表（类级别单例）"""

    _templates: dict[str, RuleTemplate] = {}

    @classmethod
    def register(cls, template: RuleTemplate):
        """注册模板实例"""
        cls._templates[template.template_id] = template

    @classmethod
    def get(cls, template_id: str) -> RuleTemplate | None:
        """按 ID 获取模板"""
        return cls._templates.get(template_id)

    @classmethod
    def list_templates(cls) -> list[dict]:
        """列出所有已注册模板"""
        return [
            {
                "id": t.template_id,
                "name": t.name,
                "description": t.description,
            }
            for t in cls._templates.values()
        ]

    @classmethod
    def clear(cls):
        """清空注册表（测试用）"""
        cls._templates.clear()
