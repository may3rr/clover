"""Print the DeepSeek API key parsed from ~/.zshrc (never log the value)."""
import re
from pathlib import Path

for line in (Path.home() / ".zshrc").read_text().splitlines():
    m = re.match(r"\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*[\"']?([^\"'\s]+)", line)
    if m:
        print(m.group(1))
        break
