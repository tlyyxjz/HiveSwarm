#!/bin/bash
# p = PI一键派发 (fire-and-forget)
A="$1"; shift; TASK="$*"
case "$A" in
  s|scout)   AGENT=scout ;;
  d|dev)     AGENT=dev ;;
  a|audit)   AGENT=audit ;;
  r|recon)   AGENT=recon ;;
  t|trader)  AGENT=trader ;;
  rep)       AGENT=reporter ;;
  b|browser) AGENT=browser ;;
  o|ops)     AGENT=ops ;;
  res)       AGENT=researcher ;;
  teach)     AGENT=teacher ;;
  *)         AGENT="$A" ;;
esac
echo "[p] PI-$AGENT: $TASK"
python "$HOME/.pi/dispatch.py" "$AGENT" "$TASK" &
