from __future__ import annotations

import re
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union

def _field_regex(spec: Union[Dict, None]) -> str:
    """Return a regex for a field spec.

    If *spec* is missing or empty, a permissive pattern ``.+`` is used.
    Anchors in patterns are stripped so they integrate into larger regexes.
    """
    if not spec:
        return ".+"
    if "enum" in spec:
        return "(?:" + "|".join(re.escape(v) for v in spec["enum"]) + ")"
    if "oneOf" in spec:
        options = [
            _field_regex(option)
            for option in spec["oneOf"]
            if option is not None
        ]
        if not options:
            return ".+"
        return "(?:" + "|".join(f"(?:{option})" for option in options) + ")"
    pattern = spec.get("pattern")
    if pattern is None:
        raise KeyError("Field spec missing 'pattern' or 'enum'")
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$"):
        pattern = pattern[:-1]
    return pattern

def compile_template(template: str, fields: Dict[str, Dict]) -> Tuple[str, List[str]]:
    """Compile *template* into a regex pattern and extract field order.

    ``{field}`` placeholders are replaced using patterns or enums from
    *fields*. Optional segments can be denoted with ``[ ... ]`` and will be
    converted into non-capturing optional groups. The returned pattern is
    anchored with ``^`` and ``$``.
    """
    order: List[str] = []

    def _compile(segment: str) -> str:
        result = ""
        i = 0
        while i < len(segment):
            ch = segment[i]
            if ch == "{":
                j = segment.index("}", i)
                name = segment[i + 1 : j]
                if name not in order:
                    order.append(name)
                regex = _field_regex(fields.get(name))
                result += f"(?P<{name}>{regex})"
                i = j + 1
            elif ch == "[":
                depth = 1
                j = i + 1
                while j < len(segment) and depth:
                    if segment[j] == "[":
                        depth += 1
                    elif segment[j] == "]":
                        depth -= 1
                    j += 1
                inner = segment[i + 1 : j - 1]
                result += f"(?:{_compile(inner)})?"
                i = j
            else:
                result += re.escape(ch)
                i += 1
        return result

    pattern = "^" + _compile(template) + "$"
    return pattern, order
