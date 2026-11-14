#!/bin/bash
cd "$(dirname "$0")" || exit 1
export VKV_AG_HOME="${VKV_AG_HOME:-$PWD/veri}"
export VKV_AG_HOST="${VKV_AG_HOST:-0.0.0.0}"
export VKV_AG_PORT="${VKV_AG_PORT:-8780}"
exec python3 -m vkv_backend
