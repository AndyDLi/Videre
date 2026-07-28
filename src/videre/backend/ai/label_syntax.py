"""
PromQL and LogQL share the same label-matcher quoting rules.
"""


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
