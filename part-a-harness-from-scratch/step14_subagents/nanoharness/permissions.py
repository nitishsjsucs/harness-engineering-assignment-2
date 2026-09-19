"""What may run on its own, what needs a human, and what never runs.

This is policy, not enforcement. It decides what to *ask* about, using what the
model wrote. A clever command can still slip past a text rule, which is why step
12 adds a kernel sandbox underneath. Two layers, two different jobs:

    permissions -> "should I bother the user about this?"
    sandbox     -> "can this even touch that file?"

Rules of the engine: compound commands are split and the strictest verdict wins;
anything we cannot read confidently (command substitution, an unparsable line)
becomes "ask" rather than "allow".
"""
import json
import shlex
from dataclasses import dataclass
from pathlib import Path

ALLOW, ASK, DENY = "allow", "ask", "deny"
_STRICTNESS = {ALLOW: 0, ASK: 1, DENY: 2}

DEFAULT, YOLO, READ_ONLY = "default", "yolo", "read-only"

SEPARATORS = {"&&", "||", ";", "|", "&", "|&", ";;", "(", ")", "\n"}
SHELLS = {"sh", "bash", "zsh", "ksh", "fish", "eval", "source"}

# Commands that only look. Multi-word entries must match the first words exactly.
READ_ONLY_COMMANDS = (
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "rg", "find", "file", "stat", "tree",
    "sort", "uniq", "cut", "diff", "date", "echo", "which", "type", "du", "df", "ps", "printenv",
    "git status", "git diff", "git log", "git show", "git branch", "git rev-parse", "git ls-files",
    "git blame", "git remote", "python --version", "python3 --version", "pip list", "pytest --collect-only",
)

# Flags that turn a reading command into a writing one.
WRITING_FLAGS = {"find": {"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint", "-fls"}}

# Never, in any mode. Token prefixes.
DENIED_COMMANDS = (
    ("sudo",), ("su",), ("doas",),
    ("shutdown",), ("reboot",), ("halt",), ("poweroff",),
    ("mkfs",), ("fdisk",), ("diskutil",),
    ("rm", "-rf", "/"), ("rm", "-fr", "/"), ("rm", "-rf", "~"), ("rm", "-rf", "/*"),
    ("git", "push", "--force"), ("git", "push", "-f"),
    ("chmod", "-R", "777", "/"),
)

# "task" is safe in itself: everything the subagent then does is gated on its own.
SAFE_TOOLS = {"read_file", "list_dir", "load_skill", "write_todos", "task"}
WRITING_TOOLS = {"write_file", "edit_file"}


@dataclass
class Verdict:
    decision: str
    reason: str = ""

    def __bool__(self) -> bool:
        return self.decision == ALLOW


class Policy:
    def __init__(self, root: Path | str, mode: str = DEFAULT):
        self.root = Path(root).resolve()
        self.mode = mode
        self.session_allow: set[str] = set()  # what the user answered "always" to

    # ----- the entry point the agent uses -------------------------------
    def check(self, name: str, raw_arguments: str) -> Verdict:
        arguments = parse(raw_arguments)
        if name == "bash":
            verdict = self.check_command(str(arguments.get("command", "")))
        elif name in WRITING_TOOLS:
            verdict = self.check_write(str(arguments.get("path", "")))
        elif name in SAFE_TOOLS:
            verdict = Verdict(ALLOW, "read-only tool")
        else:
            verdict = Verdict(ASK, f"{name} is not classified in the permission policy")
        if self.mode == READ_ONLY and verdict.decision == ASK:
            # In read-only mode there is nobody to ask: anything uncertain is refused.
            return Verdict(DENY, f"{verdict.reason} (read-only mode)")
        return verdict

    def check_write(self, path: str) -> Verdict:
        target = self.resolve(path)
        if ".git" in target.parts:
            return Verdict(DENY, "files inside a .git directory are never written by the agent")
        if self.mode == READ_ONLY:
            return Verdict(DENY, "read-only mode")
        if self.mode == YOLO or self.inside_project(target):
            return Verdict(ALLOW, "inside the project directory")
        return Verdict(ASK, f"{target} is outside the project directory {self.root}")

    def check_command(self, command: str) -> Verdict:
        try:
            segments = split_command(command)
        except ValueError as err:
            return Verdict(ASK, f"the command could not be parsed ({err})")
        if not segments:
            return Verdict(ASK, "empty command")

        verdict = Verdict(ALLOW, "")
        if uses_substitution(command):
            verdict = strictest(verdict, Verdict(ASK, "it uses command substitution, so the real command is hidden"))
        for separator, tokens in segments:
            verdict = strictest(verdict, self.check_segment(separator, tokens))
        return verdict

    def check_segment(self, separator: str, tokens: list[str]) -> Verdict:
        for rule in DENIED_COMMANDS:
            if tokens[: len(rule)] == list(rule):
                return Verdict(DENY, f"'{' '.join(rule)}' is on the deny list")
        verb = tokens[0]
        if separator == "|" and verb in SHELLS:
            return Verdict(DENY, "piping text into a shell runs code nobody has read")
        if self.mode == YOLO:
            return Verdict(ALLOW, "yolo mode")

        target = redirect_target(tokens)
        if target is not None:
            return Verdict(ASK, f"it redirects output into {target}")
        if f"bash:{verb}" in self.session_allow:
            return Verdict(ALLOW, f"you allowed '{verb}' for this session")

        rule = allowlist_match(tokens)
        if rule is None:
            return Verdict(ASK, f"'{verb}' is not on the read-only allow list")
        risky = WRITING_FLAGS.get(verb, set()).intersection(tokens)
        if risky:
            return Verdict(ASK, f"'{verb}' with {', '.join(sorted(risky))} can change files")
        return Verdict(ALLOW, f"'{rule}' only reads")

    # ----- helpers ------------------------------------------------------
    def remember(self, name: str, raw_arguments: str) -> str:
        """Record an 'always allow' answer for the rest of this session."""
        arguments = parse(raw_arguments)
        if name == "bash":
            tokens = str(arguments.get("command", "")).split()
            key = f"bash:{tokens[0]}" if tokens else "bash:"
        else:
            key = f"{name}:*"
        self.session_allow.add(key)
        return key

    def resolve(self, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        # resolve() also collapses "..", which is how a path escapes the project.
        return candidate.resolve()

    def inside_project(self, target: Path) -> bool:
        return target == self.root or self.root in target.parents

    def read_only(self) -> "Policy":
        """A copy that never asks (used for subagents in step 14)."""
        return Policy(self.root, READ_ONLY)


def parse(raw_arguments: str) -> dict:
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        return {}  # the registry will report the broken JSON; nothing runs either way
    return arguments if isinstance(arguments, dict) else {}


def strictest(left: Verdict, right: Verdict) -> Verdict:
    return right if _STRICTNESS[right.decision] > _STRICTNESS[left.decision] else left


def split_command(command: str) -> list[tuple[str, list[str]]]:
    """Split a compound command into (separator before it, tokens) segments."""
    # A newline is a command separator too; shlex would treat it as plain whitespace.
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[tuple[str, list[str]]] = []
    current: list[str] = []
    separator = ""
    for token in lexer:  # raises ValueError on unbalanced quotes
        if token in SEPARATORS:
            if current:
                segments.append((separator, current))
            current, separator = [], token
        else:
            current.append(token)
    if current:
        segments.append((separator, current))
    return segments


def uses_substitution(command: str) -> bool:
    return "$(" in command or "`" in command or "<(" in command or ">(" in command


def redirect_target(tokens: list[str]) -> str | None:
    """The file an output redirection would write, ignoring /dev/null and fd copies."""
    for index, token in enumerate(tokens):
        if not token or set(token) - set("<>&") or ">" not in token:
            continue
        target = tokens[index + 1] if index + 1 < len(tokens) else ""
        if target in ("/dev/null", "/dev/stdout", "/dev/stderr") or target.isdigit():
            continue
        return target or "a file"
    return None


def allowlist_match(tokens: list[str]) -> str | None:
    for rule in READ_ONLY_COMMANDS:
        parts = rule.split()
        if tokens[: len(parts)] == parts:
            return rule
    return None
