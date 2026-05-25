#!/bin/bash
LATEST=$(curl -sL https://api.github.com/repos/ast-grep/ast-grep/releases/latest \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
curl -sL "https://github.com/ast-grep/ast-grep/releases/download/${LATEST}/app-x86_64-unknown-linux-gnu.zip" \
  -o /tmp/ast-grep.zip
python3 -c "import zipfile; zipfile.ZipFile('/tmp/ast-grep.zip').extractall('/tmp/ast-grep-bin/')"
mkdir -p ~/.local/bin
cp /tmp/ast-grep-bin/ast-grep ~/.local/bin/ast-grep
cp /tmp/ast-grep-bin/sg ~/.local/bin/sg
chmod +x ~/.local/bin/ast-grep ~/.local/bin/sg
rm -rf /tmp/ast-grep.zip /tmp/ast-grep-bin
export PATH="$HOME/.local/bin:$PATH"
