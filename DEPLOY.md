# 部署指南（云服务器 + IP 访问，无域名）

## 一、购买服务器

- 腾讯云 / 阿里云「轻量应用服务器」，最低配（2 核 2G）即可，约 ¥30~60/月；
- 系统镜像选 **Ubuntu 22.04 或 24.04**；
- 记下：**公网 IP**、**root 密码**（购买后到控制台设置）。

## 二、连接服务器

Windows 电脑打开 PowerShell（或 CMD），执行：

```powershell
ssh root@你的公网IP
```

首次连接输 yes，再输入 root 密码。（也可用 Xshell / FinalShell 等图形工具）

## 三、部署（以下命令全部在服务器上执行）

### 1. 更新系统并安装依赖

```bash
apt update && apt install -y python3 python3-venv git
```

### 2. 下载代码

```bash
cd /opt
git clone https://github.com/WTXwang/lab-checkin.git
cd lab-checkin
```

### 3. 创建配置并填写

```bash
cp config.example.py config.py
nano config.py
```

改两处（编辑完按 `Ctrl+O` 回车保存、`Ctrl+X` 退出）：

- `ADMIN_PASSWORD = "..."` → 设一个**强密码**（全局超管密码，服务器上不要用简单密码）；
- `SECRET_KEY = "..."` → 生成随机值：
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
  把输出粘贴到 `SECRET_KEY`；
- 暂不用动 `HTTPS_ONLY`（保持 `False`，以后配好 HTTPS 再改 `True`）。

### 4. 创建虚拟环境并安装依赖

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 5. 试运行

```bash
./venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://你的公网IP:8000`，能出现登录页即成功（如打不开，去云控制台**防火墙/安全组**放行 8000 端口）。验证后 `Ctrl+C` 停掉。

### 6. 配置开机自启 + 崩溃自动重启（systemd）

```bash
nano /etc/systemd/system/lab-checkin.service
```

粘贴以下内容：

```ini
[Unit]
Description=Lab Check-in System
After=network.target

[Service]
WorkingDirectory=/opt/lab-checkin
ExecStart=/opt/lab-checkin/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

保存后启用：

```bash
systemctl daemon-reload
systemctl enable --now lab-checkin
systemctl status lab-checkin
```

看到 `active (running)` 即成功。之后服务器重启也会自动拉起。

### 7. 每日自动备份数据库

```bash
mkdir -p /opt/lab-checkin/backups
crontab -e
```

添加一行（每天凌晨 3 点备份 data.db）：

```text
0 3 * * * cp /opt/lab-checkin/data.db /opt/lab-checkin/backups/data-$(date +\%Y\%m\%d).db
```

### 8. 迁移本地数据（可选）

如果要把本机已有的学生数据搬到服务器：先在本地停掉签到系统（关 start.bat 窗口），然后在本机执行：

```powershell
scp "D:\signed system\data.db" root@你的公网IP:/opt/lab-checkin/data.db
```

服务器上重启服务生效：

```bash
systemctl restart lab-checkin
```

## 四、更新代码（以后改版后）

服务器上执行：

```bash
cd /opt/lab-checkin
git pull
systemctl restart lab-checkin
```

## 五、HTTPS（后续有域名再配）

目前无域名，先以 HTTP 运行（注意：密码为明文传输，**局域网/教学内网使用可接受；公网长期使用建议尽快补 HTTPS**）。

有域名后（国内服务器需 ICP 备案），安装 Caddy 即可自动申请免费证书并自动跳转 HTTPS：

```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
```

把域名解析到服务器 IP 后，编辑 `/etc/caddy/Caddyfile`：

```text
你的域名 {
    reverse_proxy localhost:8000
}
```

重启 Caddy：`systemctl reload caddy`。然后把 `config.py` 的 `HTTPS_ONLY = True` 并重启服务：`systemctl restart lab-checkin`。
