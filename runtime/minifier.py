from __future__ import annotations

import re
from typing import Tuple


class ManifestMinifier:
    MARKDOWN_FENCES = re.compile(r"```[a-zA-Z0-9_-]*|```")
    MULTISPACE = re.compile(r"\s+")

    def minify(self, system_declaration: str, dynamic_context: str) -> Tuple[str, str]:
        def clean(value: str) -> str:
            value = self.MARKDOWN_FENCES.sub("", value)
            value = " ".join(line.strip() for line in value.splitlines() if line.strip())
            value = self.MULTISPACE.sub(" ", value)
            return value.strip()
        return clean(system_declaration), clean(dynamic_context)
