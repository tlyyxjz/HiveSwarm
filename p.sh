#!/bin/bash
# p — PI一键派发 + 蜂巢管线自动接入
AGENT="$1"
TASK="$2"

case "$AGENT" in
  s|scout)   A=scout ;;
  d|dev)     A=dev ;;
  a|audit)   A=audit ;;
  r|recon)   A=recon ;;
  t|trader)  A=trader ;;
  rep)       A=reporter ;;
  b|browser) A=browser ;;
  o|ops)     A=ops ;;
  res)       A=researcher ;;
  teach)     A=teacher ;;
  hive|swarm) 
    # 蜂巢入口: p hive "全面审计 https://xxx.com"
    python ~/.claude/scripts/hive-brain.py --target "$TASK" --url "$2" --execute 2>/dev/null &
    python ~/.claude/scripts/hive-mind.py status 2>/dev/null
    exit 0 ;;
  brain)
    python ~/.claude/scripts/hive-brain.py --target "$TASK"
    exit 0 ;;
  *)
    # 安全场景? -> 先走brain再派scout
    if echo "$TASK" | grep -qiE '审计|漏洞|安全|扫描|CTF|flag|渗透|bounty|SQL|XSS'; then
      echo "[p] 安全场景 -> hive-brain -> 蜂群"
      python ~/.claude/scripts/hive-brain.py --target "$TASK" --url "$TASK" 2>/dev/null
    fi
    A="$AGENT" ;;
esac

echo "[p] PI-$A <- $TASK"
python ~/.pi/dispatch.py "$A" "$TASK" 2>/dev/null || echo "PI not available — run directly: $TASK"
