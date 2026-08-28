# 03 — 部署 FreeIPA 服务器（Docker）

## 3.1 部署架构

```
┌──────────────────────────────────────────────────┐
│  宿主机: Ubuntu 26.04 / 192.168.3.90              │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │  Docker Container: freeipa-server            │ │
│  │  Image: freeipa/freeipa-server:almalinux-10 │ │
│  │  Hostname: ipa-local.thinkmeta.site         │ │
│  │                                             │ │
│  │  FreeIPA Domain: thinkmeta.site             │ │
│  │  Realm: THINKMETA.SITE                       │ │
│  │                                             │ │
│  │  /data (容器) ←──→ /data/docker-space/     │ │
│  │                         ipa-data (宿主机)    │ │
│  └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

## 3.2 准备数据目录

```bash
# 创建持久化数据目录
sudo mkdir -p /data/docker-space/ipa-data

# 如果之前有旧容器，彻底清理
sudo docker rm -f freeipa-server 2>/dev/null
sudo rm -rf /data/docker-space/ipa-data/*
```

## 3.3 拉取镜像

```bash
# 拉取 FreeIPA 官方 Docker 镜像（AlmaLinux 10 版本）
docker pull freeipa/freeipa-server:almalinux-10-4.13.1

# 验证镜像
docker images | grep freeipa
```

## 3.4 启动容器并安装 FreeIPA

这是一条完整的部署命令，**一条命令同时启动容器并执行安装**：

```bash
docker run -d \
  --privileged \
  --cgroupns=host \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  -v /proc/meminfo:/proc/meminfo:ro \
  --name freeipa-server \
  --hostname ipa-local.thinkmeta.site \
  --restart unless-stopped \
  --sysctl net.ipv6.conf.all.disable_ipv6=0 \
  --add-host ipa-local.thinkmeta.site:192.168.3.90 \
  -e IPA_SERVER_IP=192.168.3.90 \
  -v /data/docker-space/ipa-data:/data \
  -p 192.168.3.90:53:53/tcp \
  -p 192.168.3.90:53:53/udp \
  -p 80:80/tcp \
  -p 443:443/tcp \
  -p 389:389/tcp \
  -p 636:636/tcp \
  -p 88:88/tcp \
  -p 88:88/udp \
  -p 464:464/tcp \
  -p 464:464/udp \
  -p 123:123/udp \
  -e PASSWORD="YourAdminPassword" \
  freeipa/freeipa-server:almalinux-10-4.13.1 \
  ipa-server-install \
  -U \
  --domain=thinkmeta.site \
  --realm=THINKMETA.SITE \
  --hostname=ipa-local.thinkmeta.site \
  --ip-address=192.168.3.90 \
  --setup-dns \
  --forwarder=1.1.1.1 \
  --no-ntp \
  --skip-mem-check \
  --allow-zone-overlap
```

### 参数逐行解析

#### Docker 运行参数

| 参数 | 说明 |
|------|------|
| `-d` | 后台运行容器 |
| `--privileged` | 特权模式，FreeIPA 需要管理 cgroup、网络等 |
| `--cgroupns=host` | 使用宿主机 cgroup 命名空间 |
| `-v /sys/fs/cgroup:...` | 挂载 cgroup（systemd 需要） |
| `-v /proc/meminfo:...` | 暴露内存信息给容器 |
| `--name freeipa-server` | 容器名称 |
| `--hostname ipa-local.thinkmeta.site` | 容器内主机名 |
| `--restart unless-stopped` | 开机自启（除非手动停止） |
| `--sysctl net.ipv6...=0` | 不禁用 IPv6（Kerberos 可能需要） |
| `--add-host ...:192.168.3.90` | 手动添加 hosts 解析 |
| `-e IPA_SERVER_IP=192.168.3.90` | 告知 FreeIPA 服务器 IP |
| `-v .../ipa-data:/data` | **持久化数据**（最重要） |
| `-p 192.168.3.90:53:53/tcp` | DNS TCP 绑定到指定 IP |
| `-p 192.168.3.90:53:53/udp` | DNS UDP 绑定到指定 IP |
| `-p 80:80` 到 `-p 123:123` | 其余端口映射 |
| `-e PASSWORD="..."` | **admin 密码** |

#### ipa-server-install 安装参数

| 参数 | 说明 |
|------|------|
| `-U` | 无人值守安装（不询问确认） |
| `--domain=thinkmeta.site` | 域名 |
| `--realm=THINKMETA.SITE` | Kerberos Realm（大写） |
| `--hostname=...` | 服务器 FQDN |
| `--ip-address=192.168.3.90` | 服务器 IP |
| `--setup-dns` | 安装并配置内置 DNS |
| `--forwarder=1.1.1.1` | DNS 上游转发器 |
| `--no-ntp` | 不使用内置 NTP（依赖宿主机时钟） |
| `--skip-mem-check` | 跳过内存检查（Docker 环境可能误报） |
| `--allow-zone-overlap` | 允许 DNS 区域重叠（Docker 网络环境需要） |

## 3.5 监控安装进度

安装过程需要 **5-15 分钟**，可以通过以下命令查看进度：

```bash
# 实时查看安装日志
docker logs -f freeipa-server

# 查看最后 50 行日志
docker logs --tail 50 freeipa-server
```

### 成功的日志标志

安装成功后会看到类似以下输出：

```
Configuring ipa-server ...
  [1/28]: configuring directory server
  [2/28]: configuring kerberos
  ...
  [28/28]: restarting IPA services
===========================================================
Setup complete
===========================================================
Next steps:
    1. You must make sure these network ports are open:
       TCP Ports: 80, 443, 389, 636, 88, 464
       UDP Ports: 88, 464, 123, 53
    2. You can now obtain a kerberos ticket using:
       kinit admin
```

## 3.6 验证部署

### 方法一：Kerberos 认证测试

```bash
# 进入容器
docker exec -it freeipa-server bash

# 获取 admin 的 Kerberos 票据
echo "YourAdminPassword" | kinit admin

# 验证票据
klist
```

输出示例：

```
Ticket cache: KCM:0
Default principal: admin@THINKMETA.SITE

Valid starting     Expires            Service principal
08/09/26 10:00:00  08/10/26 10:00:00  krbtgt/THINKMETA.SITE@THINKMETA.SITE
```

### 方法二：IPA 命令验证

```bash
# 在容器内执行
docker exec -it freeipa-server bash -c '
echo "YourAdminPassword" | kinit admin
ipa user-find admin
ipa host-find
ipa dnszone-find
'
```

### 方法三：Web UI 访问

在浏览器打开：`https://192.168.3.90`

- 用户名：`admin`
- 密码：你设置的 `PASSWORD` 值

> 首次访问会提示证书不受信任（自签名证书），这是正常的，点击"高级"→"继续访问"即可。

## 3.7 常用容器操作命令

```bash
# 查看容器状态
docker ps -a | grep freeipa

# 启动容器
docker start freeipa-server

# 停止容器
docker stop freeipa-server

# 重启容器
docker restart freeipa-server

# 查看容器日志
docker logs -f freeipa-server

# 进入容器 Shell
docker exec -it freeipa-server bash
```

## 3.8 开机自启与持久化

### 数据持久化

所有 FreeIPA 数据（LDAP、Kerberos、证书）都保存在：

```
宿主机: /data/docker-space/ipa-data/
容器内: /data/
```

> **这是最重要的目录**，备份/迁移/恢复都围绕这个目录进行。

### 容器自启

`--restart unless-stopped` 确保：
- Docker 服务启动时 → 容器自动启动
- 容器异常退出时 → 自动重启
- 手动 `docker stop` 后 → 不会自动启动（直到下次 Docker 重启）

## 3.9 安装完成后立即做的事情

```bash
# 1. 进入容器
docker exec -it freeipa-server bash

# 2. 获取 admin 票据
echo "YourAdminPassword" | kinit admin

# 3. 检查 DNS 记录是否正常
ipa dnsrecord-find thinkmeta.site

# 4. 确认 SRV 记录
dig @127.0.0.1 _ldap._tcp.thinkmeta.site SRV

# 5. 退出容器
exit
```

## 3.10 常见问题

### Q1：安装失败如何重来？

```bash
# 停止并删除容器
docker stop freeipa-server
docker rm freeipa-server

# 清空数据目录（重要！否则残留数据会导致再次安装失败）
sudo rm -rf /data/docker-space/ipa-data/*

# 重新执行 docker run 命令
```

### Q2：容器启动后立刻退出？

```bash
# 查看退出日志
docker logs freeipa-server 2>&1 | tail -50
```

常见原因：端口冲突（特别是 53 端口）、内存不足。

### Q3：Web UI 打不开？

- 检查容器是否在运行：`docker ps | grep freeipa`
- 检查 443 端口是否监听：`curl -k https://192.168.3.90`
- 检查防火墙是否放行 443 端口

### Q4：安装时间过长（超过 30 分钟）？

查看日志中卡在哪一步：

```bash
docker logs freeipa-server 2>&1 | grep "configuring"
```

如果卡在 `configuring certificate server`，通常是内存不足。
