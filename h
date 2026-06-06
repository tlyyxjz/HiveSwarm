#!/bin/bash
TASK="$*"
S="$HOME/.claude/scripts"
BF="$HOME/.claude/data/brain-result.json"
MJ="$HOME/.claude/data/hive-mind.json"

echo "[h] brain..."
python "$S/hive-brain.py" --target "$TASK" 2>/dev/null
python "$S/hive-mind.py" init "$TASK" 2>/dev/null

# 用python文件而不是inline - 避免编码炸
cat > /tmp/parse_brain.py << 'PY'
import json,os,sys
bf=os.path.expanduser(r'~\.claude\data\brain-result.json')
if not os.path.exists(bf): bf=r'C:\Users\Lenovo\.claude\data\brain-result.json'
if os.path.exists(bf):
    d=json.load(open(bf,encoding='utf-8'))
    agents=d.get('agents',['api-hunter','sql-injector','xss-hunter'])
    print(','.join(agents))
else:
    print('api-hunter,sql-injector,xss-hunter')
PY
AGENTS=$(python /tmp/parse_brain.py)
echo "[h] $AGENTS"
python "$S/hive-mind.py" queue --add "$AGENTS" 2>/dev/null

# 提取URL
cat > /tmp/extract_url.py << 'PY'
import sys,re
t=sys.argv[1] if len(sys.argv)>1 else ''
m=re.search(r'(https?://[a-zA-Z0-9._/\-]+)',t)
print(m.group(1) if m else '')
PY
URL=$(python /tmp/extract_url.py "$TASK")

echo "[h] probe $URL..."
if [ -n "$URL" ]; then
    python "$S/universal-probe.py" "$URL" 2>/dev/null &
else
    python "$S/universal-probe.py" "https://ec1f5391cf27304d475df17255fbdc26.ctf.hacker101.com" 2>/dev/null &
fi
sleep 3

echo "[h] live..."
python "$S/hive-live.py" --show 2>/dev/null
