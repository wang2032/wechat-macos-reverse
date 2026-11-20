#!/usr/bin/env bash
# 写入账号与主密钥：./scripts/setup_key.sh <account> <64位hex key>
set -euo pipefail
[ $# -eq 2 ] || { echo "用法: $0 <account> <64位hex key>"; exit 1; }
ACCOUNT="$1"; KEY="$2"
[[ "$KEY" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "密钥应为 64 位十六进制（32 字节）"; exit 1; }
DIR="$HOME/.wxre"; mkdir -p "$DIR"; chmod 700 "$DIR"
printf '{\n  "account": "%s",\n  "key": "%s"\n}\n' "$ACCOUNT" "${KEY,,}" > "$DIR/config.json"
chmod 600 "$DIR/config.json"
echo "已写入 $DIR/config.json"
