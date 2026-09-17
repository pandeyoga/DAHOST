#!/usr/bin/env bash
cd /app/backend && grep -v -E "^(emergentintegrations|litellm)" requirements.txt > /app/.req_rest.txt
pip install -q -r /app/.req_rest.txt > /app/.pip.log 2>&1; echo "PIP_DONE $?" >> /app/.pip.log
