#!/bin/sh
set -eu

# Docker/Linux 环境始终从脚本所在的项目根目录启动。
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_ROOT"

# .env 是项目配置文件；Python 虚拟环境固定放在 .venv。
VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_READY="$VENV_DIR/.dependencies-ready"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"

# PYTHON_BIN 只负责首次创建虚拟环境，默认使用 PATH 中的 python。
PYTHON_BIN=${PYTHON_BIN:-python}
if [ ! -x "$VENV_PYTHON" ]; then
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        echo "[错误] 找不到用于创建 .venv 的 Python 解释器: $PYTHON_BIN" >&2
        exit 1
    fi

    echo "[初始化] 创建 Python 虚拟环境: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    rm -f "$VENV_READY"
fi

if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "[错误] 找不到依赖文件: $REQUIREMENTS_FILE" >&2
    exit 1
fi

# 标记保存依赖文件指纹；依赖变化或入口依赖缺失时自动重新安装。
REQUIREMENTS_FINGERPRINT=$("$VENV_PYTHON" -c \
    'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
    "$REQUIREMENTS_FILE")
INSTALLED_FINGERPRINT=""
if [ -f "$VENV_READY" ]; then
    INSTALLED_FINGERPRINT=$(cat "$VENV_READY")
fi

if [ "$INSTALLED_FINGERPRINT" != "$REQUIREMENTS_FINGERPRINT" ] || \
    ! "$VENV_PYTHON" -c 'import uvicorn' >/dev/null 2>&1; then
    echo "[初始化] 安装项目依赖: $REQUIREMENTS_FILE"
    "$VENV_PYTHON" -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        -r "$REQUIREMENTS_FILE"
    printf '%s\n' "$REQUIREMENTS_FINGERPRINT" > "$VENV_READY"
fi

# 显式 Docker 命令也优先使用虚拟环境中的 python、pip 等可执行文件。
PATH="$VENV_DIR/bin:$PATH"
export PATH

# 传入参数时允许 Docker ENTRYPOINT 执行显式命令；无参数时启动服务。
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec "$VENV_PYTHON" main.py
