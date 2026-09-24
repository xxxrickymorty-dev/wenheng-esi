#!/usr/bin/env bash
# ============================================================================
# 文衡 · 学科信息参考自动化演示站 —— Linux 一键部署
#
# 适配：Ubuntu / Debian（apt）与 CentOS / RHEL / Alibaba Cloud Linux（dnf / yum）
#
# 用法：
#   sudo bash server/deploy/deploy_linux.sh [公网URL]
#   例：sudo bash server/deploy/deploy_linux.sh http://116.62.37.161:8080
#
# 🔴 若该机是「nginx 占 8080、反代到 uvicorn 8081」的拓扑（116.62.37.161 就是这样），
#    **必须显式给 PORT=8081**，否则 uvicorn 去绑 8080 会和 nginx 撞，
#    日志只有一行 `[Errno 98] address already in use`，外部看到的是 nginx 的 502：
#       sudo PORT=8081 bash server/deploy/deploy_linux.sh http://116.62.37.161:8080
#    （下面的「0.1 端口预检」会在撞之前拦住你）
#
# 前置条件：
#   ① 部署包已解包到 /opt，即 /opt/wenheng/pyproject.toml 存在
#      （tar -C /opt -xzf wenheng-deploy-*.tar.gz）
#   ② 阿里云**安全组**已放行 8080/tcp 入方向 —— 脚本管不了云控制台
#
# 幂等：可重复执行。venv / .env / 服务会复用，代码与依赖更新到最新。
# 停止：systemctl stop wenheng-demo ；卸载：rm /etc/systemd/system/wenheng-demo.service
#
# 红线（勿改）：
#   · 必须**单 worker** —— SSE 推送 + 内存态任务队列，多进程必崩。别加 --workers。
#   · 服务用户须对 APP_DIR 可写（流水线要往 out/ 写产物）。
# ============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/wenheng}"
SVC_USER="${SVC_USER:-www-data}"
SVC_NAME="${SVC_NAME:-wenheng-demo}"
PORT="${PORT:-8080}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PUBLIC_URL="${1:-}"

C_CYAN='\033[1;36m'; C_RED='\033[1;31m'; C_YEL='\033[1;33m'; C_OFF='\033[0m'
log()  { printf "\n${C_CYAN}==> %s${C_OFF}\n" "$*"; }
warn() { printf "${C_YEL}[警告] %s${C_OFF}\n" "$*"; }
die()  { printf "\n${C_RED}[失败] %s${C_OFF}\n" "$*" >&2; exit 1; }

# 依赖清单 = pyproject.toml 的 [project]dependencies + [dependency-groups]server
# （不含 dev/pytest）。服务器若无 uv 就由 pip 按这份清单装，保证与本地一致。
DEPS=(
  "pandas>=2.2" "numpy>=1.26" "matplotlib>=3.8" "statsmodels>=0.14"
  "python-docx>=1.1" "pyarrow>=15" "openpyxl>=3.1" "scipy>=1.11"
  "pillow>=10" "pyyaml>=6.0"
  "fastapi>=0.110" "uvicorn[standard]>=0.27" "jinja2>=3.1"
  "python-multipart>=0.0.9" "itsdangerous>=2.1" "qrcode[pil]>=7.4"
)

# ---------------------------------------------------------------- 0. 前置检查
[ "$(id -u)" -eq 0 ] || die "请用 root 运行：sudo bash $0"
[ -f "$APP_DIR/pyproject.toml" ] || die "未找到 $APP_DIR/pyproject.toml —— 先把部署包解包到 /opt"

# --------------------------------------------- 0.2 首屏资产预检（ADR-0001 要求）
# /app 是 web/dist 的构建产物（服务器不装 Node，dist 必须随包带）。缺了它服务**照样起得来**，
# 只有浏览器里白屏——所以在这里拦死，别等验收现场才发现。重新打包用 tools/make_deploy_pkg.py。
[ -f "$APP_DIR/web/dist/index.html" ] \
  || die "未找到 $APP_DIR/web/dist/index.html —— 部署包必须含 web/dist（/app 首屏）。
    在本地 wenheng/ 下重新打包：python tools/make_deploy_pkg.py"
[ -d "$APP_DIR/web/dist/assets" ] \
  || die "未找到 $APP_DIR/web/dist/assets —— web/dist 不完整（index.html 引的资源不在）。
    在本地 wenheng/ 下重新构建并打包：cd web && npm run build && cd .. && python tools/make_deploy_pkg.py"

log "目标：APP_DIR=$APP_DIR  服务用户=$SVC_USER  端口=$PORT"
[ -n "$PUBLIC_URL" ] && log "公网地址：$PUBLIC_URL" || warn "未传公网地址，二维码/说明书里的链接需事后补进 server/.env"

# ------------------------------------------------- 0.1 端口占用预检（别再踩 502）
# uvicorn 绑不上端口时**不会**让脚本失败——它只在 journal 里留一行 `[Errno 98]`，
# systemd 反复重启，外部拿到的是 nginx 的 502，很容易误判成「代码有 bug」。
# 已知拓扑：116.62.37.161 上 nginx 占 8080 并反代到 127.0.0.1:8081。
if command -v ss >/dev/null 2>&1; then
  HOLDER="$(ss -lntp 2>/dev/null | awk -v p=":$PORT\$" '$4 ~ p {print $NF}' | head -1)"
  if [ -n "$HOLDER" ] && ! printf '%s' "$HOLDER" | grep -qi 'python'; then
    die "端口 $PORT 已被占用：$HOLDER
    本机若是「nginx 占 $PORT、反代到 uvicorn」的拓扑，请显式改用后端端口重跑，例如：
      sudo PORT=8081 bash $0 ${PUBLIC_URL:-http://<公网IP>:$PORT}"
  fi
fi

# ------------------------------------------------------- 1. 系统包（字体优先）
# 中文字体是硬需求：缺了之后 matplotlib 出的图表中文全变方框，报告没法看。
log "安装系统依赖（中文字体 / venv / pip）"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || warn "apt-get update 失败，继续尝试安装"
  apt-get install -y -qq python3-venv python3-pip fonts-noto-cjk fonts-noto-cjk-extra || warn "apt 安装部分失败"
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y python3-pip google-noto-sans-cjk-ttc-fonts google-noto-serif-cjk-ttc-fonts || warn "dnf 安装部分失败"
elif command -v yum >/dev/null 2>&1; then
  yum install -y python3-pip google-noto-sans-cjk-ttc-fonts google-noto-serif-cjk-ttc-fonts || warn "yum 安装部分失败"
else
  warn "未识别的包管理器，请手动确保已装中文字体（否则图表中文变方框）"
fi
if command -v fc-list >/dev/null 2>&1; then
  printf "    中文字体条数：%s\n" "$(fc-list 2>/dev/null | grep -ci 'cjk\|wqy' || echo 0)"
fi

# ------------------------------------------------------------ 2. Python 版本
log "检查 Python"
command -v python3 >/dev/null 2>&1 || die "未找到 python3（请先安装 Python 3.10+）"
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' \
  || die "Python $PYV 过低，项目要求 >=3.10（建议装 3.11/3.12 后重跑）"
printf "    python3 = %s\n" "$PYV"

# ------------------------------------------------------- 3. venv + 依赖安装
log "建立虚拟环境并安装依赖（源：$PIP_INDEX）"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  python3 -m venv "$APP_DIR/.venv" || die "创建 venv 失败（Debian/Ubuntu 需 python3-venv 包）"
fi
VENV_PY="$APP_DIR/.venv/bin/python"
"$VENV_PY" -m pip install -q --upgrade pip -i "$PIP_INDEX"
"$VENV_PY" -m pip install --progress-bar off -i "$PIP_INDEX" "${DEPS[@]}" \
  || die "依赖安装失败 —— 换源重试：PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/ sudo bash $0"
printf "    已装包数：%s\n" "$("$VENV_PY" -m pip list --format=freeze | wc -l)"

# ------------------------------------------------------------ 4. 服务用户
log "准备服务用户"
if id -u "$SVC_USER" >/dev/null 2>&1; then
  printf "    %s 已存在\n" "$SVC_USER"
else
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER" 2>/dev/null \
    || useradd -r -M -s /sbin/nologin "$SVC_USER"
  printf "    已创建系统用户 %s\n" "$SVC_USER"
fi

# ----------------------------------------------------------- 5. .env 配置
log "写入 server/.env"
ENV_FILE="$APP_DIR/server/.env"
[ -f "$ENV_FILE" ] || cp "$APP_DIR/server/.env.example" "$ENV_FILE"
NEW_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
python3 - "$ENV_FILE" "$PUBLIC_URL" "$NEW_SECRET" <<'PYEOF'
import pathlib, sys
path, public_url, secret = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
kv, order = {}, []
for line in p.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k, v = s.split("=", 1)
    k = k.strip()
    if k not in kv:
        order.append(k)
    kv[k] = v.strip()

# 弱密钥一律换掉，避免公网用可猜的签名密钥（会话 cookie 靠它签）
cur = kv.get("WENHENG_SECRET", "")
weak = (not cur) or ("change-me" in cur) or ("wenheng-demo-secret" in cur) or len(cur) < 32
if weak:
    kv["WENHENG_SECRET"] = secret
if public_url:
    kv["WENHENG_PUBLIC_URL"] = public_url

defaults = ["WENHENG_USER", "WENHENG_PASS", "WENHENG_SECRET",
            "WENHENG_PUBLIC_URL", "WENHENG_REFERENCE_DOCX",
            "WENHENG_PYTHON", "WENHENG_SHOW_HINT"]
for k in defaults:
    if k not in kv:
        order.append(k)
        kv[k] = ""

p.write_text("\n".join(f"{k}={kv[k]}" for k in order) + "\n", encoding="utf-8")
print("    .env 键：", ", ".join(order))
print("    WENHENG_PUBLIC_URL =", kv["WENHENG_PUBLIC_URL"] or "(空)")
print("    WENHENG_SECRET =", "已生成新的 64 位随机串" if weak else ("保留原有（长度 %d）" % len(kv["WENHENG_SECRET"])))
PYEOF
chmod 600 "$ENV_FILE"

# 目录属主：流水线要往 out/ 写产物，必须是服务用户可写
mkdir -p "$APP_DIR/out/_jobs"
chown -R "$SVC_USER:$SVC_USER" "$APP_DIR"

# ------------------------------------------------------- 6. systemd 服务
log "安装 systemd 服务 $SVC_NAME.service"
sed -e "s|^User=.*|User=$SVC_USER|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" \
    -e "s|^ExecStart=.*|ExecStart=$APP_DIR/.venv/bin/python -m uvicorn server.app:app --host 0.0.0.0 --port $PORT|" \
    "$APP_DIR/server/deploy/wenheng-demo.service" \
    > "/etc/systemd/system/$SVC_NAME.service"
systemctl daemon-reload
systemctl enable "$SVC_NAME" >/dev/null 2>&1 || true
systemctl restart "$SVC_NAME"

# ------------------------------------------------------------ 7. 防火墙
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
  ufw allow "$PORT"/tcp >/dev/null 2>&1 && printf "    ufw 放行 %s/tcp\n" "$PORT" || true
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --permanent --add-port="$PORT"/tcp >/dev/null 2>&1 \
    && firewall-cmd --reload >/dev/null 2>&1 \
    && printf "    firewalld 放行 %s/tcp\n" "$PORT" || true
fi

# ------------------------------------------------------------ 8. 验活
log "验活"
sleep 3
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/login" || echo 000)"
if [ "$HTTP_CODE" = "200" ]; then
  printf "    本机 /login → 200 ✓\n"
else
  warn "本机 /login 返回 $HTTP_CODE —— 看日志：journalctl -u $SVC_NAME -n 50 --no-pager"
fi

printf "\n${C_CYAN}=========== 部署完成 ===========${C_OFF}\n"
cat <<EOF
  服务状态： systemctl status $SVC_NAME
  实时日志： journalctl -u $SVC_NAME -f
  本机访问： http://127.0.0.1:$PORT/login
  外网访问： ${PUBLIC_URL:-http://<公网IP>:$PORT/login}

  若外网打不开但本机 200 —— 九成是**阿里云安全组**没放行 $PORT/tcp（云控制台 → 安全组 → 入方向）。
  测试账号见 $APP_DIR/server/.env 的 WENHENG_USER / WENHENG_PASS。
EOF
