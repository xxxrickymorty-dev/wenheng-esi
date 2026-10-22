# 部署手册（Linux 服务器）

> ⚠ **2026-09-24 起以 `server/deploy/部署执行清单.md` 为准**（本文只作背景存档）。
> 三个变化点先记住：
> ① 打包改用 `tools/make_deploy_pkg.py`——含 `web/dist`（/app 首屏必需），
>    **不含 `server/.env`**（下面 §1 的旧 tar 命令会把密钥打进包，别再用）；
> ② 首屏是新工作区 `/app/`（`/` 302 过去），不再是老站对勘本；
> ③ 老站页面已 302 到新站对应视图；目标拓扑是 nginx:8080 → uvicorn:8081。

演示站 = FastAPI + uvicorn，**单 worker**，端口 8080，目标目录 `/opt/wenheng`。
一键脚本：`server/deploy/deploy_linux.sh`，适配 Ubuntu/Debian 与 CentOS/RHEL/阿里云 Linux。

---

## 0. 前置（唯一必须人工在云控制台做的事）

**阿里云控制台 → 安全组 → 入方向 → 放行 8080/tcp。**

脚本管不了云控制台。这一步没做，症状恒定是「本机 curl 200，外网打不开」——
别去查代码，就是它。

---

## 1. 本地打包

产物落在**项目根目录**：`wenheng-deploy-20260916.tar.gz`（≈59 MB）。

包内含：代码 + `master/`（结构金母版）+ `input/`（202607、202609 台账）
+ `out/`（4 期产物，演示站「选期次」必需）+ `server/.env`。
**不含** `.venv/`（服务器重建）、`.git/`、`out/_jobs`（运行态）。

改了代码后重新打包：

```bash
cd <工作区根>          # 包含 wenheng/ 的那一层
tar -czf wenheng-deploy-$(date +%Y%m%d).tar.gz \
  --exclude='wenheng/.venv' --exclude='*/__pycache__' --exclude='*.pyc' \
  --exclude='wenheng/.pytest_cache' --exclude='wenheng/.git' \
  --exclude='wenheng/tmp' --exclude='wenheng/out/_jobs' --exclude='wenheng/out/_pending' \
  --exclude='*.log' --exclude='wenheng/server/e2e_report.txt' wenheng
```

---

## 2. 上传

Windows 的 PowerShell / Git Bash 均可（Win10+ 自带 OpenSSH）：

```bash
scp wenheng-deploy-20260916.tar.gz root@116.62.37.161:/root/
```

---

## 3. 一键部署

```bash
ssh root@116.62.37.161
mkdir -p /opt && tar -C /opt -xzf /root/wenheng-deploy-20260916.tar.gz
cd /opt/wenheng && sudo bash server/deploy/deploy_linux.sh http://116.62.37.161:8080
```

脚本依次做 8 件事，可重复执行（幂等）：

| # | 动作 | 说明 |
|---|---|---|
| 1 | 装系统包 | `fonts-noto-cjk`（图表中文回退，**缺了中文全变方框**）+ `python3-venv`/`pip` |
| 2 | 校验 Python | 要求 ≥3.10，低了直接报错退出，不糊弄 |
| 3 | 建 `.venv` 装依赖 | 按 `pyproject.toml` 清单，默认清华源；失败时提示换阿里云源 |
| 4 | 准备服务用户 | 默认 `www-data`（不存在则建系统用户） |
| 5 | 写 `server/.env` | 保留已有账号密码；**弱密钥自动换成 64 位随机串**；写入 `WENHENG_PUBLIC_URL` |
| 6 | 装 systemd 单元 | `wenheng-demo.service`，`chown` 给服务用户（流水线要写 `out/`） |
| 7 | 本机防火墙 | ufw / firewalld 放行 8080 |
| 8 | 验活 | `curl 127.0.0.1:8080/login` 期望 200 |

换源重试：

```bash
PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/ sudo bash server/deploy/deploy_linux.sh http://116.62.37.161:8080
```

---

## 4. 验证

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/login   # 期望 200
systemctl status wenheng-demo --no-pager
```

浏览器打开 `http://116.62.37.161:8080/login`。
测试账号在 `/opt/wenheng/server/.env`：`WENHENG_USER` / `WENHENG_PASS`（管理员）；
`WENHENG_OPERATOR_USER` / `WENHENG_OPERATOR_PASS`（操作员·评委，只读；2026-10-11 起取代 guest）。

推荐自检顺序：登录 → 首屏对勘本（应显示最新一期）→ 控制台选某期次→ 一键生成 →
看五步进度跑完 → 下载报告初稿。跑通这一串才算部署成功。

---

## 5. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| 外网打不开，本机 curl 200 | 阿里云**安全组**没放行 | 控制台加 8080/tcp 入方向 |
| 图表里中文是方框 | 缺中文字体 | `apt install fonts-noto-cjk && systemctl restart wenheng-demo` |
| 服务起不来 / 502 | 依赖或路径问题 | `journalctl -u wenheng-demo -n 50 --no-pager` |
| 登录一直失败 | 改了 `.env` 没重启 | `systemctl restart wenheng-demo` |
| pip 装依赖超时 | 网络 | 见 §3 换源重试 |
| 一键生成后任务不动 | 看任务日志 | `journalctl -u wenheng-demo -f` |
| 上传台账报错 | 台账格式/断言不过 | 演示站会拦停并给出原因，属预期行为（断言闸） |

---

## 6. 日常运维

| 动作 | 命令 |
|---|---|
| 看实时日志 | `journalctl -u wenheng-demo -f` |
| 重启 | `systemctl restart wenheng-demo` |
| 停止 | `systemctl stop wenheng-demo` |
| 更新代码 | 重传包 → `tar -C /opt -xzf 新包.tar.gz` → 重跑 §3 脚本（`.venv` 保留，不重装） |
| 卸载 | `systemctl disable --now wenheng-demo && rm -f /etc/systemd/system/wenheng-demo.service && systemctl daemon-reload` |

---

## 7. 可选增强（第 4 期金样回测）

把第 4 期人工原件 docx 传到服务器（如 `/opt/wenheng/reference/`），
在 `/opt/wenheng/server/.env` 填 `WENHENG_REFERENCE_DOCX=/opt/wenheng/reference/<文件名>.docx`
并重启服务，登录页/控制台才会出现「附加金样回测」选项。不配则该选项隐藏，不影响主流程。

---

## 红线（勿改）

- **单 worker**。绝不给 uvicorn 加 `--workers`——SSE 推送 + 内存态任务队列，多进程必崩。
- 服务用户须对 `/opt/wenheng` 可写（流水线要往 `out/` 写产物）；脚本已 `chown`。
- 服务器上的台账若需修改，走 **zip 级 XML 替换**，**禁止 openpyxl 存盘**
  （会丢图表、条件格式、打印设置）——与本地同一条红线。
