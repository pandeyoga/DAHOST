#!/usr/bin/env bash
cd /app/frontend && nice -n 19 yarn build > /app/.build.log 2>&1; echo "BUILD_DONE $?" >> /app/.build.log
