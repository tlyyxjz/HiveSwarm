#!/bin/bash
# h = 蜂巢一键流。用法: h "目标URL或描述"
TASK="$*"
S="$HOME/.claude/scripts"
UF="$S/universal-probe.py"
BF="$HOME/.claude/data/brain-result.json"

echo "[h=1/4] brain..."
python "$S/hive-brain.py" --target "$TASK" 2>/dev/null
python "$S/hive-mind.py" init "$TASK" 2>/dev/null

# Parse brain result
AGENTS=$(python -c "import json;d=json.load(open('$BF'));print(','.join(d.get('agents',[])))" 2>/dev/null)
AGENTS=${AGENTS:-"api-hunter,sql-injector,xss-hunter"}
echo "[h=2/4] $AGENTS"

python "$S/hive-mind.py" queue --add "$AGENTS" 2>/dev/null

echo "[h=3/4] 万能探针..."
# Extract URL from task description
URL=$(echo "$TASK" | grep -oP 'https?://[^ ]+' | head -1)
if [ -n "$URL" ]; then
    python "$UF" "$URL" 2>/dev/null
else
    python "$UF" "$TASK" 2>/dev/null
fi

echo "[h=4/4] 战报:"
python "$S/hive-mind.py" status 2>/dev/null
