#!/bin/bash
for d in /proc/[0-9]*; do
  if tr '\0' ' ' < $d/cmdline 2>/dev/null | grep -q "^python -m uvicorn glycotwin.backend.app:app"; then kill ${d#/proc/}; fi
done
sleep 2
rm -f "$1"
cd /tmp/vid/clean
PYTHONPATH=/tmp/vid/clean/src GLYCOTWIN_DATABASE_URL=sqlite:///$1 nohup python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000 > /tmp/vid/backend.log 2>&1 &
for i in $(seq 1 40); do curl -s -m 2 http://127.0.0.1:8000/health >/dev/null && echo up && exit 0; sleep 2; done; echo notup
