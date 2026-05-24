#!/bin/bash
cd ~/aiops-project/ui-backend
source ~/aiops-project/system2/venv/bin/activate
nohup python server.py > ~/aiops-portforwards/ui-backend.log 2>&1 &
echo "Backend PID: $!"
sleep 3
curl -s http://localhost:9001/ | python -m json.tool
