"""Formula stats (LGE-07): a small arithmetic grammar over named stats, parsed by hand. Never `eval`.

    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor)*
    factor := NUMBER | NAME | '(' expr ')' | '-' factor

Names are stat codes (letters, digits and '_', starting with a letter). A division by zero makes the value None
(shown as blank), never an error, so a goalkeeper with no shots has no save percentage rather than a crash.
"""

import re
from decimal import Decimal

_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z][A-Za-z0-9_]*)|(\S))")
MAX_LENGTH = 200
MAX_DEPTH = 30


class FormulaError(ValueError):
    pass


def _tokens(text: str) -> list[tuple[str, str]]:
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"A formula is at most {MAX_LENGTH} characters.")
    out = []
    for number, name, other in _TOKEN.findall(text):
        if number:
            out.append(("num", number))
        elif name:
            out.append(("name", name))
        elif other:
            if other not in "+-*/()":
                raise FormulaError(f"Unexpected character '{other}'.")
            out.append(("op", other))
    if not out:
        raise FormulaError("The formula is empty.")
    return out


def parse(text: str) -> tuple:
    """The syntax tree: ('num', Decimal) | ('name', str) | ('neg', node) | (op, left, right)."""
    tokens = _tokens(text)
    pos = 0

    def peek() -> tuple[str, str] | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> tuple[str, str]:
        nonlocal pos
        token = peek()
        if token is None:
            raise FormulaError("The formula ends too early.")
        pos += 1
        return token

    def at_op(ops: str) -> bool:
        token = peek()
        return token is not None and token[0] == "op" and token[1] in ops

    def expr(depth: int) -> tuple:
        if depth > MAX_DEPTH:
            raise FormulaError("The formula is nested too deeply.")
        node = term(depth)
        while at_op("+-"):
            node = (take()[1], node, term(depth))
        return node

    def term(depth: int) -> tuple:
        node = factor(depth)
        while at_op("*/"):
            node = (take()[1], node, factor(depth))
        return node

    def factor(depth: int) -> tuple:
        kind, value = take()
        if kind == "num":
            return ("num", Decimal(value))
        if kind == "name":
            return ("name", value)
        if value == "-":
            return ("neg", factor(depth + 1))
        if value == "(":
            node = expr(depth + 1)
            if take() != ("op", ")"):
                raise FormulaError("A bracket is not closed.")
            return node
        raise FormulaError(f"Unexpected '{value}'.")

    tree = expr(0)
    if (extra := peek()) is not None:
        raise FormulaError(f"Unexpected '{extra[1]}'.")
    return tree


def names(tree: tuple) -> set[str]:
    if tree[0] == "name":
        return {tree[1]}
    if tree[0] == "num":
        return set()
    return set().union(*(names(child) for child in tree[1:]))


def validate(text: str, known: set[str]) -> tuple:
    """Parse and check that every name is a known entry stat; returns the tree."""
    tree = parse(text)
    unknown = names(tree) - known
    if unknown:
        raise FormulaError(f"Unknown stat: {', '.join(sorted(unknown))}.")
    return tree


def evaluate(tree: tuple, values: dict[str, Decimal]) -> Decimal | None:
    kind = tree[0]
    if kind == "num":
        return tree[1]
    if kind == "name":
        return values.get(tree[1], Decimal(0))
    if kind == "neg":
        inner = evaluate(tree[1], values)
        return None if inner is None else -inner
    left, right = evaluate(tree[1], values), evaluate(tree[2], values)
    if left is None or right is None:
        return None
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    return left / right if right else None
