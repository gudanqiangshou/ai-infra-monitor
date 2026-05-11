#!/bin/bash
# 每日运行包装脚本 - 加载 .env.local 后执行 main.py
cd "$(dirname "$0")"

# 加载环境变量
if [ -f .env.local ]; then
    set -a
    source .env.local
    set +a
fi

exec /Library/Developer/CommandLineTools/usr/bin/python3 scripts/main.py "$@"
