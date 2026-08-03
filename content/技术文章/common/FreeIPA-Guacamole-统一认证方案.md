# FreeIPA + Apache Guacamole 统一认证与虚拟机管理方案

> **适用场景**：ESXi 虚拟化平台 + 多台 Ubuntu 虚拟机 + 需要统一账号密码管理 + 支持长期关机（有效期 10 年）
>
> **预计部署时间**：2-3 小时

---

## 一、方案概述

### 1.1 架构图

```
┌──────────────────────────────────────────────────────┐
│                   用户 (浏览器)                        │
│          https://guacamole.yourdomain.com             │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│              Apache Guacamole (Web UI)                │
│    用户通过 LDAP 登录 → Web SSH 终端 → 连接 VM         │
│    也支持用户直接用 SSH 客户端 (如 PuTTY) 直连 VM       │
└──────────────────────┬───────────────────────────────┘
                       │ LDAP 认证
                       ▼
┌──────────────────────────────────────────────────────┐
│                 FreeIPA Server                        │
│  ┌──────────┬──────────┬──────────┬────────────┐     │
│  │  LDAP    │ Kerberos │   DNS    │    NTP     │     │
│  │ 目录服务  │ 单点登录  │ 域名解析  │  时间同步   │     │
│  └──────────┴──────────┴──────────┴────────────┘     │
│  Web 管理界面: https://ipa.yourdomain.com             │
│  可在此增删改用户、设置密码策略、管理 sudo 权限         │
└──────────────────────┬───────────────────────────────┘
                       │ SSSD 协议 (LDAP + Kerberos)
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │  VM-01   │ │  VM-02   │ │  VM-03   │
    │  Ubuntu  │ │  Ubuntu  │ │  Ubuntu  │
    │  (SSSD)  │ │  (SSSD)  │ │  (SSSD)  │
    └──────────┘ └──────────┘ └──────────┘
          ▲            ▲            ▲
          └────────────┼────────────┘
                       │
              ESXi 虚拟化平台 (手动创建 VM)
```

### 1.2 核心组件

| 组件 | 作用 | 部署方式 |
|------|------|----------|
| **FreeIPA Server** | 统一身份认证服务器，管理所有用户、密码、权限、证书 | Ubuntu 26.04 LTS 虚拟机 |
| **SSSD** | 每台 VM 上的客户端守护进程，连接 FreeIPA 实现统一登录 | 每台业务 VM 安装 |
| **Apache Guacamole** | Web 管理页面 + 浏览器 SSH 终端 | Docker Compose |

### 1.3 密码同步原理

```
页面/CLI 修改用户密码
        │
        ▼
  FreeIPA LDAP 更新密码哈希
        │
        ▼
  所有 VM 的 SSSD 实时查询 LDAP 验证
  (VM 本地不存储密码，每次登录都向 FreeIPA 验证)
        │
        ▼
  用户 SSH 登录任意 VM → 使用新密码 → 即时生效
```

**关键优势**：VM 不存储密码副本，所有认证请求实时转发到 FreeIPA，因此**天然同步，不存在不一致问题**。

### 1.4 需求对照

| 你的需求 | 方案实现 |
|----------|----------|
| 创建多个虚拟机 | ESXi 手动创建，FreeIPA 统一管理认证 |
| 虚拟机镜像重新设置/制作 | 制作加入 FreeIPA 域的模板 VM，克隆后重新注册 |
| 页面管理添加用户 | FreeIPA Web UI (`https://ipa.lab.local`) |
| 用户 SSH 连接虚拟机 | SSSD 统一认证，任何 VM 都可用同一账号 SSH |
| 删除用户所有 VM 同步 | FreeIPA 删除用户 → SSSD 即时生效 → 所有 VM 无法登录 |
| 修改密码所有 VM 同步 | FreeIPA 修改密码 → LDAP 更新 → 所有 VM SSSD 实时验证 |
| 长期关机（半年以上） | 所有有效期改为 10 年 + 开机自检脚本兜底 |

---

## 二、环境规划

### 2.1 服务器规划

| 角色 | 主机名 | IP 地址 | 操作系统 | 配置 |
|------|--------|---------|----------|------|
| **FreeIPA Server** | `ipa.lab.local` | 192.168.1.10 | Ubuntu 26.04 Server | 2C4G, 20G 磁盘 |
| **Guacamole Server** | `guac.lab.local` | 192.168.1.11 | Ubuntu 26.04 Server | 2C2G, 20G 磁盘 |
| **业务 VM-01** | `vm01.lab.local` | 192.168.1.101 | Ubuntu 26.04 Server | 按需 |
| **业务 VM-02** | `vm02.lab.local` | 192.168.1.102 | Ubuntu 26.04 Server | 按需 |
| **业务 VM-03** | `vm03.lab.local` | 192.168.1.103 | Ubuntu 26.04 Server | 按需 |

> 以上 VM 均在 ESXi 上手动创建。`lab.local` 为示例域名，请替换为实际域名。

### 2.2 域名规划

| 项目 | 值 |
|------|-----|
| DNS 域名 | `lab.local` |
| Kerberos Realm | `LAB.LOCAL`（必须大写） |
| FreeIPA 管理员 | `admin` |
| FreeIPA Web UI | `https://ipa.lab.local` |
| Guacamole Web UI | `http://guac.lab.local:8080/guacamole` |

### 2.3 为什么选 Ubuntu 26.04 LTS

| 对比维度 | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS | **Ubuntu 26.04 LTS** |
|----------|:---:|:---:|:---:|
| 发布时间 | 2022年4月 | 2024年4月 | **2026年4月** |
| 标准支持截止 | 2027年4月 | 2029年4月 | **2031年4月** |
| 内核版本 | 5.15 / 6.8 | 6.8 | **7.0** |
| FreeIPA 版本 | 4.9.x | 4.11.x | **4.13.x** |
| SSSD 版本 | 2.8.x | 2.9.x | **2.12** |
| OpenSSH | 8.9 | 9.6 | **10.2** |
| systemd | 249 | 255 | **259** |

**核心理由**：
1. **生命周期最长**：标准支持到 2031 年，至少 5 年无需大版本升级
2. **FreeIPA 4.13.x**：Ubuntu 上兼容性最佳，`ipa-server-install` 流程最顺畅
3. **SSSD 2.12**：以专用 `sssd` 用户（非 root）运行，安全性大幅提升
4. **内核 7.0 + systemd 259**：DNS 和网络栈最稳定，FreeIPA 强依赖 DNS

> 不推荐非 LTS 版本（如 26.10），支持周期仅 9 个月，不适合基础设施。

---

## 三、步骤一：安装 Ubuntu Server 26.04

> 本节涵盖 FreeIPA Server 虚拟机的安装。Guacamole Server 和业务 VM 安装步骤完全相同，仅 IP 和主机名不同。

### 3.1 在 ESXi 上创建虚拟机

1. 登录 ESXi Web Client
2. 右键 → **创建/注册虚拟机** → **创建新虚拟机**
3. 配置：
   - **名称**：`ipa-server`
   - **客户机操作系统**：Linux → Ubuntu Linux (64-bit)
   - **CPU**：2 核
   - **内存**：4 GB（最低 1.2 GB）
   - **硬盘**：20 GB（精简置备）
   - **网络**：VM Network（桥接）
4. 挂载 ISO：`ubuntu-26.04-live-server-amd64.iso`
5. 启动虚拟机

### 3.2 安装过程

**语言选择**：English（推荐，避免中文终端乱码）

**Installer update**：选择 `Continue without updating`

**Keyboard configuration**：默认 English (US) → Done

**Choose type of install**：选择 `Ubuntu Server` → Done

**Network connections**：
- 选中网卡 → Edit IPv4
- IPv4 Method: `Manual`
- 填写：
  ```
  Subnet:        192.168.1.0/24
  Address:       192.168.1.10
  Gateway:       192.168.1.1
  Name Servers:  192.168.1.10, 8.8.8.8
  Search domains: lab.local
  ```
- Save → Done

**Proxy**：留空 → Done

**Mirror**：默认 → Done（或改为 `http://mirrors.aliyun.com/ubuntu/`）

**Guided storage**：
- 选择 `Use an entire disk`
- 勾选 `Set up this disk as an LVM group`（默认已勾选）
- Done → Continue

**Storage configuration**（确认分区方案）：
- 默认即可：/boot 约 2G，剩余为 LVM 根分区
- Done → Continue → Continue

**Profile**：
```
Your name:            Administrator
Your server's name:   ipa
Pick a username:      adminuser          # 本地管理员（不是 FreeIPA 的 admin）
Password:             ********
Confirm:              ********
```
- Done

**Ubuntu Pro**：Skip for now → Continue

**SSH Setup**：
- 勾选 `Install OpenSSH server`
- Done

**Featured snaps**：全部不选 → Done

安装完成后 → **Reboot Now**

### 3.3 首次登录配置

```bash
# 使用安装时创建的用户登录
ssh adminuser@192.168.1.10

# 设置主机名为 FQDN 格式（安装时只设了短名）
sudo hostnamectl set-hostname ipa.lab.local

# 配置 /etc/hosts
sudo tee -a /etc/hosts << 'EOF'
192.168.1.10  ipa.lab.local  ipa
EOF

# 验证
hostname -f    # 应输出 ipa.lab.local

# 配置时区
sudo timedatectl set-timezone Asia/Shanghai

# 确认网络配置
ip a
```

### 3.4 处理磁盘空间（如果 2T 只显示 100G）

Ubuntu Server 默认 LVM 安装可能只分配部分磁盘空间：

```bash
# 1. 查看磁盘结构
lsblk
# sda3 可能只占用了 100G，但 sda 是 2T

# 2. 扩展分区
sudo apt install -y cloud-guest-utils
sudo growpart /dev/sda 3

# 3. 扩展 LVM 物理卷
sudo pvresize /dev/sda3

# 4. 扩展逻辑卷到全部空间
sudo lvextend -l +100%FREE /dev/mapper/ubuntu--vg-ubuntu--lv

# 5. 扩展文件系统
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv

# 6. 验证
df -h /
```

> 如果磁盘是 NVMe（`/dev/nvme0n1`），把 `/dev/sda` 替换为 `/dev/nvme0n1`。

---

## 四、步骤二：部署 FreeIPA Server（Docker 方式）

> **为什么用 Docker**：Ubuntu 26.04 官方仓库中没有 `freeipa-server` 包（仅 `freeipa-client` 可用）。FreeIPA 官方提供了 Docker 镜像，一行命令即可部署，不依赖系统仓库，且支持所有后续配置。

### 4.1 安装 Docker

```bash
# 安装 Docker
sudo apt update
sudo apt install -y docker.io
sudo systemctl enable --now docker

# 验证
docker --version
```

### 4.2 释放 53 端口（DNS 端口冲突处理）

FreeIPA 容器内置 DNS 服务，需要占用 53 端口。Ubuntu 默认的 `systemd-resolved` 也占用 53 端口，需要先释放：

```bash
# 停止并禁用 systemd-resolved
sudo systemctl stop systemd-resolved
sudo systemctl disable systemd-resolved

# 重建 /etc/resolv.conf（否则 DNS 解析会失效）
sudo rm /etc/resolv.conf
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
echo "nameserver 114.114.114.114" | sudo tee -a /etc/resolv.conf

# 验证 DNS 可用
ping -c 2 baidu.com
```

### 4.3 部署 FreeIPA Server 容器

```bash
# 创建数据持久化目录
sudo mkdir -p /var/lib/ipa-data

# 拉取镜像（可选，run 时会自动拉取）
sudo docker pull freeipa/freeipa-server:centos-9-stream

# 启动 FreeIPA Server（一键部署，约 5-10 分钟）
sudo docker run --name freeipa-server -ti \
    -h ipa.lab.local \
    --read-only \
    --restart unless-stopped \
    -v /var/lib/ipa-data:/data:Z \
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    -p 53:53/udp -p 53:53 \
    -p 80:80 -p 443:443 \
    -p 389:389 -p 636:636 \
    -p 88:88 -p 464:464 \
    -p 88:88/udp -p 464:464/udp \
    -p 123:123/udp \
    -e PASSWORD=YourPassword123 \
    --dns=127.0.0.1 \
    --sysctl net.ipv6.conf.all.disable_ipv6=0 \
    --cgroupns=host \
    freeipa/freeipa-server:centos-9-stream \
    ipa-server-install -U -r LAB.LOCAL --no-ntp --setup-dns
```

**参数说明**：

| 参数 | 说明 |
|------|------|
| `-h ipa.lab.local` | 容器主机名（FQDN 格式，必须能解析） |
| `--restart unless-stopped` | 开机自启，除非手动停止 |
| `-v /var/lib/ipa-data:/data:Z` | 数据持久化（容器删除后数据不丢） |
| `-e PASSWORD=YourPassword123` | 同时设置 Directory Manager 和 admin 密码 |
| `-r LAB.LOCAL` | Kerberos Realm（必须大写） |
| `--setup-dns` | 启用内置 DNS 服务 |
| `-U` | 无人值守安装，不需交互 |
| `--no-ntp` | 跳过 NTP 配置（宿主机已配置时间同步） |
| `--dns=127.0.0.1` | 容器内部 DNS 指向自己 |

> **重要**：将 `YourPassword123` 替换为你自己的密码。该密码同时作为 Directory Manager 和 IPA admin 的密码。

安装过程中容器会输出大量日志，约 5-10 分钟后看到以下信息即表示成功：

```
==============================================================================
Setup complete
==============================================================================
```

### 4.4 容器日常管理

```bash
# 查看容器状态
sudo docker ps

# 查看容器日志
sudo docker logs freeipa-server

# 进入容器执行命令
sudo docker exec -it freeipa-server bash

# 在容器内获取 admin 凭证
sudo docker exec -it freeipa-server kinit admin
# 输入密码

# 停止/启动/重启
sudo docker stop freeipa-server
sudo docker start freeipa-server
sudo docker restart freeipa-server

# 从宿主机直接使用 ipa 命令
# （容器内的命令需要通过 docker exec 执行，或配置别名）
alias ipa='sudo docker exec -it freeipa-server ipa'
alias kinit='sudo docker exec -it freeipa-server kinit'
```

### 4.5 配置防火墙

```bash
sudo ufw allow 53/tcp
sudo ufw allow 53/udp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 389/tcp
sudo ufw allow 636/tcp
sudo ufw allow 88/tcp
sudo ufw allow 88/udp
sudo ufw allow 464/tcp
sudo ufw allow 464/udp
sudo ufw allow 123/udp
```

### 4.6 配置宿主机 DNS 指向 FreeIPA

FreeIPA 强依赖 DNS，宿主机和其他 VM 需要能解析 FreeIPA 的域名：

```bash
# 方式一：修改 /etc/hosts（简单）
echo "127.0.0.1  ipa.lab.local  ipa" | sudo tee -a /etc/hosts

# 方式二：使用 FreeIPA 容器作为 DNS 服务器
# 在 /etc/resolv.conf 中将 nameserver 指向宿主机 IP
# FreeIPA 容器的 53 端口已映射到宿主机
echo "nameserver 127.0.0.1" | sudo tee /etc/resolv.conf
# 测试
nslookup ipa.lab.local 127.0.0.1
```

### 4.7 验证安装

```bash
# 进入容器获取 admin 凭证
sudo docker exec -it freeipa-server kinit admin
# 输入密码

# 查看服务状态
sudo docker exec -it freeipa-server ipactl status
# 所有服务应为 RUNNING

# 查看用户列表
sudo docker exec -it freeipa-server ipa user-find

# 确认 Web UI 可访问
curl -k https://localhost
```

### 4.8 备份与恢复

```bash
# 备份：只需备份数据目录
sudo tar -czf /backup/ipa-data-$(date +%Y%m%d).tar.gz -C /var/lib/ipa-data .

# 恢复：停止容器 → 恢复数据 → 重新创建容器
sudo docker stop freeipa-server
sudo docker rm freeipa-server
sudo rm -rf /var/lib/ipa-data/*
sudo tar -xzf /backup/ipa-data-20260101.tar.gz -C /var/lib/ipa-data/
# 重新执行 4.3 的 docker run 命令
```

### 4.9 为什么用 Docker 而非 apt 安装

| 对比 | apt 安装 | Docker 部署 |
|------|:---:|:---:|
| Ubuntu 26.04 支持 | ❌ 官方仓库无 freeipa-server | ✅ 任意系统 |
| 安装命令 | 多步配置 | 一行命令 |
| 依赖处理 | 需解决依赖冲突 | 容器内自包含 |
| 升级 | 依赖 Ubuntu 发新版 | `docker pull` 新镜像即可 |
| 备份 | `ipa-backup` 命令 | 备份数据目录即可 |
| 隔离性 | 与系统混在一起 | 完全隔离 |
| 迁移 | 复杂 | 拷贝数据目录即可 |

---

## 五、步骤三：配置有效期全部改为 10 年

> FreeIPA 默认密码 90 天过期、证书 2 年过期、Kerberos 票据 7 天过期。长期关机场景下需全部延长。

### 5.1 用户密码：永不过期

```bash
# 在宿主机执行（所有 ipa 命令都通过 docker exec 执行）
# 以下设置别名简化后续操作
alias ipa='sudo docker exec -i freeipa-server ipa'

# 获取 admin 凭证
echo 'YourPassword123' | sudo docker exec -i freeipa-server kinit admin

# 全局密码策略：密码永不过期
sudo docker exec -i freeipa-server ipa pwpolicy-mod global_policy --maxlife=0 --minlife=0

# 验证
sudo docker exec -i freeipa-server ipa pwpolicy-show global_policy
```

### 5.2 Kerberos 票据：续订窗口改为 10 年

```bash
# 10 年 = 10 × 365 × 24 × 3600 = 315360000 秒
sudo docker exec -i freeipa-server ipa krbtpolicy-mod \
  --maxlife=2592000 \
  --maxrenew=315360000

# 验证
sudo docker exec -i freeipa-server ipa krbtpolicy-show
```

| 参数 | 秒数 | 含义 |
|------|------|------|
| `--maxlife=2592000` | 30天 | 单张票据最大有效期 |
| `--maxrenew=315360000` | 10年 | 票据可续订总窗口 |

### 5.3 主机/服务证书有效期：改为 10 年

```bash
# 1. 导出当前默认证书配置文件
sudo docker exec -i freeipa-server ipa certprofile-show caIPAserviceCert --out /tmp/caIPAserviceCert.cfg

# 2. 备份
sudo docker exec -i freeipa-server cp /tmp/caIPAserviceCert.cfg /tmp/caIPAserviceCert.cfg.bak

# 3. 修改有效期参数为 3650 天（10 年）
sudo docker exec -i freeipa-server sed -i 's/policyset\.serverCertSet\.[0-9]*\.default\.params\.range=[0-9]*/policyset.serverCertSet.5.default.params.range=3650/' /tmp/caIPAserviceCert.cfg
sudo docker exec -i freeipa-server sed -i 's/policyset\.serverCertSet\.[0-9]*\.constraint\.params\.range=[0-9]*/policyset.serverCertSet.5.constraint.params.range=3650/' /tmp/caIPAserviceCert.cfg

# 4. 导入修改后的配置
sudo docker exec -i freeipa-server ipa certprofile-mod caIPAserviceCert --file=/tmp/caIPAserviceCert.cfg

# 5. 验证
sudo docker exec -i freeipa-server ipa certprofile-show caIPAserviceCert
```

> **提示**：为了方便，可在宿主机 `~/.bashrc` 中添加别名，之后直接输入 `ipa` 命令：
> ```bash
> echo "alias ipa='sudo docker exec -i freeipa-server ipa'" >> ~/.bashrc
> echo "alias kinit='sudo docker exec -it freeipa-server kinit'" >> ~/.bashrc
> source ~/.bashrc
> ```

### 5.4 汇总

```
配置项                    默认值        →  改为 10 年
─────────────────────────────────────────────────────────
用户密码有效期             90天          →  永不过期 (maxlife=0)
Kerberos 票据 maxlife      24小时        →  30天 (2592000秒)
Kerberos 票据 maxrenew     7天           →  10年 (315360000秒)
主机/服务证书有效期        2年           →  10年 (3650天)
CA 根证书有效期            20年          →  无需改，已覆盖
```

---

## 六、步骤四：FreeIPA Web UI 用户管理

### 6.1 访问 Web UI

浏览器打开 `https://192.168.1.10`（或 `https://ipa.lab.local`），用 `admin` 账号和 IPA 管理员密码登录。

> 浏览器会提示证书不受信任（自签名证书），点击"高级"→"继续访问"即可。

### 6.2 添加用户

1. 点击顶部菜单 **Identity** → **Users** → 点击 **+ Add**
2. 填写：
   - **User login**: `zhangsan`
   - **First name**: `三`
   - **Last name**: `张`
   - **New Password** / **Verify Password**: 设置初始密码
   - 取消勾选 **Force password change**（我们已设密码永不过期）
3. 点击 **Add**

### 6.3 修改密码

1. 在用户列表点击目标用户名
2. 点击 **Actions** → **Reset Password**
3. 输入新密码 → 确定
4. 所有 VM 上的该用户密码即时同步生效

### 6.4 删除/停用用户

- **删除**：用户列表勾选 → **Delete** → 确认（所有 VM 即时失效）
- **停用**：用户详情 → **Actions** → **Disable**（保留账号但禁止登录）
- **启用**：用户详情 → **Actions** → **Enable**

### 6.5 命令行管理（备用）

```bash
# 所有 ipa 命令通过 docker exec 执行

# 添加用户
sudo docker exec -i freeipa-server ipa user-add zhangsan --first=三 --last=张 --password

# 修改密码
sudo docker exec -i freeipa-server ipa user-mod zhangsan --password

# 删除用户
sudo docker exec -i freeipa-server ipa user-del zhangsan

# 停用/启用
sudo docker exec -i freeipa-server ipa user-disable zhangsan
sudo docker exec -i freeipa-server ipa user-enable zhangsan

# 查看所有用户
sudo docker exec -i freeipa-server ipa user-find
```

---

## 七、步骤五：业务 VM 安装与加入域

> 每台业务 VM 都需要：安装 Ubuntu Server → 安装 FreeIPA Client → 加入域。
>
> Guacamole Server 也用同样方式安装 Ubuntu Server，但不需要加入域（第八步单独处理）。

### 7.1 安装 Ubuntu Server

与步骤三完全相同，仅修改：

| 项目 | FreeIPA Server | 业务 VM-01 |
|------|:---:|:---:|
| 名称 | `ipa-server` | `vm01` |
| IP | 192.168.1.10 | 192.168.1.101 |
| 主机名 | `ipa` | `vm01` |

### 7.2 安装后基础配置

```bash
# SSH 登录业务 VM
ssh adminuser@192.168.1.101

# 设置 FQDN 主机名
sudo hostnamectl set-hostname vm01.lab.local

# 配置 hosts（指向 FreeIPA Server）
sudo tee -a /etc/hosts << 'EOF'
192.168.1.10  ipa.lab.local  ipa
EOF

# 配置时区
sudo timedatectl set-timezone Asia/Shanghai

# 如果 DNS 使用的是 FreeIPA Server，确认能解析
nslookup ipa.lab.local
```

### 7.3 安装 FreeIPA Client 并加入域

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 启用 universe 仓库（freeipa-client 在 universe 中）
sudo apt install -y software-properties-common
sudo add-apt-repository universe
sudo apt update

# 安装客户端
sudo apt install -y freeipa-client
```

#### 方式一：安全方式（推荐）

**第一步：在 FreeIPA Server 上生成一次性密码**

```bash
# 在 FreeIPA Server 宿主机上执行（通过 docker exec）
sudo docker exec -i freeipa-server ipa host-add vm01.lab.local --random
```

输出示例：
```
Random password: AbCdEf123456!@#
```

**第二步：在业务 VM 上执行加入命令**

```bash
sudo ipa-client-install \
  --domain=lab.local \
  --realm=LAB.LOCAL \
  --server=ipa.lab.local \
  --hostname=$(hostname -f) \
  --password='AbCdEf123456!@#' \
  --mkhomedir \
  --unattended
```

#### 方式二：交互式（简单）

```bash
sudo ipa-client-install --mkhomedir
# 提示输入授权用户：admin
# 提示输入密码：IPA admin 密码
```

### 7.4 参数说明

| 参数 | 说明 |
|------|------|
| `--domain` | FreeIPA 域名 |
| `--realm` | Kerberos Realm（大写） |
| `--server` | FreeIPA Server 地址 |
| `--hostname` | 本机 FQDN |
| `--password` | 一次性随机密码（方式一） |
| `--mkhomedir` | 用户首次登录时自动创建家目录 |
| `--unattended` | 非交互式安装 |

### 7.5 验证加入成功

```bash
# 1. 检查 SSSD 状态
sudo systemctl status sssd

# 2. 测试能否解析 FreeIPA 用户
id zhangsan
# 应输出 uid、gid 等信息

# 3. 测试 SSH 登录（从另一台机器）
ssh zhangsan@vm01.lab.local
# 使用 FreeIPA 中设置的密码登录

# 4. 验证密码同步
# 在 FreeIPA Web UI 上修改 zhangsan 密码
# 再次 SSH 登录 → 必须用新密码
```

### 7.6 让已有证书也变成 10 年

修改签发策略后，新签的证书自动 10 年。已签发的旧证书需重新签发：

```bash
# 在业务 VM 上执行
for id in $(sudo getcert list | grep "Request ID" | awk -F"'" '{print $2}'); do
    echo "重新签发证书: $id"
    sudo getcert resubmit -i "$id"
done

# 验证新证书有效期（约 10 年后过期）
sudo getcert list | grep expires
```

### 7.7 配置开机自检脚本

> 极端情况下（FreeIPA Server 在 VM 关机期间更新了主机密钥），开机后 keytab 可能失效。配置自检脚本自动发现并告警。

```bash
sudo tee /usr/local/bin/ipa-healthcheck.sh << 'SCRIPT'
#!/bin/bash
# FreeIPA 客户端健康检查脚本

LOG_FILE="/var/log/ipa-healthcheck.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# 1. 检查 SSSD
if ! systemctl is-active --quiet sssd; then
    log "SSSD 未运行，启动中..."
    systemctl start sssd
fi

# 2. 测试主机 keytab 认证
HOST_PRINCIPAL="host/$(hostname -f)"
if ! echo "" | kinit -k "$HOST_PRINCIPAL" 2>/dev/null; then
    log "WARN: 主机 keytab 认证失败，需手动重新加入 FreeIPA 域！"
    log "执行: sudo ipa-client-install --uninstall --unattended"
    log "然后: sudo ipa-client-install --domain=lab.local --realm=LAB.LOCAL --server=ipa.lab.local --hostname=$(hostname -f) --password='注册密码' --mkhomedir --unattended"
fi

# 3. 检查证书状态
sudo getcert list | grep -E "status|expires" | tee -a "$LOG_FILE"

# 4. 测试用户解析
if id admin 2>/dev/null | grep -q "no such user"; then
    log "WARN: 无法解析 FreeIPA 用户，重启 SSSD..."
    systemctl restart sssd
    sleep 5
    id admin 2>/dev/null && log "OK: 恢复" || log "ERROR: 仍无法工作"
else
    log "OK: FreeIPA 用户解析正常"
fi
SCRIPT

sudo chmod +x /usr/local/bin/ipa-healthcheck.sh

# 创建 systemd 服务
sudo tee /etc/systemd/system/ipa-healthcheck.service << 'SERVICE'
[Unit]
Description=FreeIPA Client Health Check
After=network-online.target sssd.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ipa-healthcheck.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable ipa-healthcheck.service

# 手动测试
sudo /usr/local/bin/ipa-healthcheck.sh
```

### 7.8 制作 VM 模板

完成以上配置的 VM 可转换为模板，后续克隆即可：

1. 在 ESXi 上关机 → 右键 → **模板** → **转换为模板**
2. 克隆新 VM 时：
   - 修改主机名和 IP
   - 在 FreeIPA Server 上执行 `ipa host-add <新主机名> --random`
   - 用新密码执行 `ipa-client-install`

---

## 八、步骤六：部署 Apache Guacamole（Web SSH 网关）

### 8.1 安装 Guacamole Server 虚拟机

按照步骤三的方式安装 Ubuntu Server 26.04，配置如下：

- **名称**：`guac-server`
- **IP**：192.168.1.11
- **主机名**：`guac.lab.local`
- **CPU**：2 核，**内存**：2 GB，**磁盘**：20 GB

```bash
# SSH 登录后
sudo hostnamectl set-hostname guac.lab.local

sudo tee -a /etc/hosts << 'EOF'
192.168.1.10  ipa.lab.local  ipa
EOF

sudo timedatectl set-timezone Asia/Shanghai
```

### 8.2 安装 Docker

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker

# 验证
docker --version
docker compose version
```

### 8.3 准备 Guacamole

```bash
# 创建部署目录
mkdir -p /opt/guacamole/init
cd /opt/guacamole

# 拉取镜像
docker pull guacamole/guacamole:1.6.0
docker pull guacamole/guacd:1.6.0
docker pull postgres:16

# 生成数据库初始化 SQL
docker run --rm guacamole/guacamole:1.6.0 /opt/guacamole/bin/initdb.sh --postgresql > ./init/initdb.sql
```

### 8.4 创建 docker-compose.yml

```bash
cat > /opt/guacamole/docker-compose.yml << 'EOF'
version: '3.8'

services:
  guacd:
    image: guacamole/guacd:1.6.0
    container_name: guacd
    restart: unless-stopped
    volumes:
      - guacd-drive:/drive
    networks:
      - guac-net

  postgres:
    image: postgres:16
    container_name: guac-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: guacamole_db
      POSTGRES_USER: guacamole_user
      POSTGRES_PASSWORD: ChangeMe123!        # 请修改为强密码
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./init:/docker-entrypoint-initdb.d
    networks:
      - guac-net

  guacamole:
    image: guacamole/guacamole:1.6.0
    container_name: guacamole
    restart: unless-stopped
    depends_on:
      - guacd
      - postgres
    environment:
      GUACD_HOSTNAME: guacd
      GUACD_PORT: 4822

      POSTGRESQL_HOSTNAME: postgres
      POSTGRESQL_PORT: 5432
      POSTGRESQL_DATABASE: guacamole_db
      POSTGRESQL_USER: guacamole_user
      POSTGRESQL_PASSWORD: ChangeMe123!      # 与上面保持一致

      # LDAP 认证（对接 FreeIPA）
      LDAP_HOSTNAME: 192.168.1.10
      LDAP_PORT: 389
      LDAP_ENCRYPTION_METHOD: none
      LDAP_USER_BASE_DN: cn=users,cn=accounts,dc=lab,dc=local
      LDAP_USERNAME_ATTRIBUTE: uid
      LDAP_USER_SEARCH_FILTER: "(uid={0})"
      LDAP_SEARCH_BIND_DN: cn=Directory Manager
      LDAP_SEARCH_BIND_PASSWORD: YourDirMgrPassword  # 替换为 Directory Manager 密码

    ports:
      - "8080:8080"
    networks:
      - guac-net

volumes:
  postgres-data:
  guacd-drive:

networks:
  guac-net:
    driver: bridge
EOF
```

> **重要**：将 `YourDirMgrPassword` 替换为安装 FreeIPA 时设置的 Directory Manager 密码。

### 8.5 启动 Guacamole

```bash
cd /opt/guacamole
docker compose up -d

# 查看启动日志
docker compose logs -f

# 检查容器状态
docker compose ps
# 三个容器都应为 Up 状态
```

### 8.6 访问 Guacamole

浏览器打开 `http://192.168.1.11:8080/guacamole`

- 使用 FreeIPA 中创建的用户名和密码登录（如 `zhangsan`）

### 8.7 配置 SSH 连接

1. 使用 Guacamole 默认管理员登录：`guacadmin` / `guacadmin`（**首次登录后务必修改密码**）
2. 点击右上角 **Settings** → **Connections** → **New Connection**
3. 填写：
   - **Name**: `VM-01 SSH`
   - **Protocol**: `SSH`
   - **Parameters** → **Hostname**: `192.168.1.101`
   - **Parameters** → **Port**: `22`
4. 在 **Users** 标签中，将连接授权给 LDAP 用户

---

## 九、步骤七：整体验证

### 9.1 用户管理验证

```bash
# FreeIPA Server 上创建测试用户（通过 docker exec）
sudo docker exec -i freeipa-server ipa user-add testuser --first=Test --last=User --password

# 在任意业务 VM 上测试登录
ssh testuser@vm01.lab.local
# 输入密码 → 应成功登录
```

### 9.2 密码同步验证

```bash
# 1. 在 FreeIPA Web UI 上修改 testuser 密码
# 2. 用旧密码 SSH 登录 → 失败
ssh testuser@vm01.lab.local   # 旧密码 → Permission denied

# 3. 用新密码 SSH 登录 → 成功
ssh testuser@vm01.lab.local   # 新密码 → 成功

# 4. 换一台 VM 测试 → 新密码同样生效
ssh testuser@vm02.lab.local   # 新密码 → 成功
```

### 9.3 删除用户验证

```bash
sudo docker exec -i freeipa-server ipa user-del testuser

# 尝试 SSH 登录任意 VM
ssh testuser@vm01.lab.local   # → 认证失败
```

### 9.4 Guacamole Web SSH 验证

1. 浏览器打开 `http://192.168.1.11:8080/guacamole`
2. 用 FreeIPA 用户登录
3. 点击 SSH 连接 → 进入 Web 终端

---

## 十、SSSD 原理说明

### 10.1 什么是 SSSD

**SSSD**（System Security Services Daemon，系统安全服务守护进程）是每台 VM 上的一个服务，充当**本地系统和 FreeIPA 之间的认证中间层**。

### 10.2 工作流程

```
用户 SSH 登录 VM
        │
        ▼
    SSH 服务 (sshd)
        │
        ▼
    PAM (可插拔认证模块)
        │
        ▼
    SSSD ──── LDAP 查询 ────▶ FreeIPA Server
        │                         │
        │                   验证用户名/密码
        │                         │
        ◀─── 认证结果 ────────────┘
        │
        ▼
   允许/拒绝登录
```

### 10.3 为什么需要 SSSD

| 没有 SSSD | 有 SSSD |
|-----------|---------|
| 每台 VM 手动 `useradd` 创建用户 | FreeIPA 统一管理，VM 自动识别 |
| 改密码逐台 `passwd` | FreeIPA 改一次，所有 VM 生效 |
| 删除用户逐台清理 | FreeIPA 删一次，所有 VM 失效 |
| 无法统一管理 sudo | FreeIPA 统一配置 sudo 规则 |
| VM 本地存密码 | 密码只在 FreeIPA，更安全 |

---

## 十一、证书体系

### 11.1 FreeIPA 自带的证书能力

```
┌─────────────────────────────────────────────────────────┐
│                  FreeIPA 内置 CA (Dogtag)                 │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │              IPA CA 根证书 (20年有效)              │    │
│  └────────────────────┬────────────────────────────┘    │
│                       │                                  │
│          ┌────────────┼────────────┐                     │
│          ▼            ▼            ▼                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
│  │ 主机证书  │ │ 服务证书  │ │ 用户证书  │                 │
│  │ (10年,   │ │ (HTTP/   │ │ (个人    │                 │
│  │  已修改) │ │  LDAP等) │ │  认证/   │                 │
│  │          │ │          │ │  签名)   │                 │
│  └──────────┘ └──────────┘ └──────────┘                 │
│                                                         │
│  配套能力: 证书吊销列表 (CRL) · OCSP 在线验证 · 自动续期   │
└─────────────────────────────────────────────────────────┘
```

### 11.2 三种证书方案

| 方案 | 适用场景 | 复杂度 |
|------|----------|:---:|
| **完全使用 FreeIPA CA** | 内部环境，不需要对接外部 PKI | 低 |
| **FreeIPA 作为中间 CA** | 企业已有 PKI，需纳入统一信任链 | 中 |
| **FreeIPA 认证 + 独立外部 CA** | FreeIPA 管认证，独立 CA 管对外证书 | 中 |

### 11.3 常用证书命令

```bash
# 导出 FreeIPA CA 根证书（分发给客户端信任）
cp /etc/ipa/ca.crt /tmp/ipa-ca.crt

# 查看所有签发证书
ipa cert-find

# 查看主机证书
ipa host-show vm01.lab.local --all | grep Certificate

# 吊销证书
ipa cert-revoke <证书序列号> --revocation-reason=6

# 查看 certmonger 自动续期状态
sudo getcert list
```

---

## 十二、日常运维

### 12.1 用户管理（FreeIPA Web UI）

| 操作 | 路径 | 说明 |
|------|------|------|
| 添加用户 | Identity → Users → Add | 设置用户名、姓名、初始密码 |
| 修改密码 | 用户详情 → Actions → Reset Password | 所有 VM 即时生效 |
| 删除用户 | 用户列表 → 勾选 → Delete | 所有 VM 即时失效 |
| 停用用户 | 用户详情 → Actions → Disable | 保留账号但禁止登录 |

### 12.2 新增业务 VM

```bash
# 1. ESXi 上克隆模板 VM，修改 IP 和主机名

# 2. FreeIPA Server 上注册（通过 docker exec）
sudo docker exec -i freeipa-server ipa host-add vm04.lab.local --random

# 3. 新 VM 上加入域
sudo ipa-client-install \
  --domain=lab.local \
  --realm=LAB.LOCAL \
  --server=ipa.lab.local \
  --hostname=vm04.lab.local \
  --password='<随机密码>' \
  --mkhomedir \
  --unattended

# 4. Guacamole 中添加 SSH 连接
```

### 12.3 删除业务 VM

```bash
# FreeIPA Server 上删除主机记录（通过 docker exec）
sudo docker exec -i freeipa-server ipa host-del vm04.lab.local

# ESXi 上删除 VM
# Guacamole 中删除对应连接
```

### 12.4 备份

Docker 方式部署，备份极其简单——只需备份数据目录：

```bash
# 备份（宿主机执行）
sudo tar -czf /backup/ipa-data-$(date +%Y%m%d).tar.gz -C /var/lib/ipa-data .

# 恢复流程
sudo docker stop freeipa-server
sudo docker rm freeipa-server
sudo rm -rf /var/lib/ipa-data/*
sudo tar -xzf /backup/ipa-data-20260101.tar.gz -C /var/lib/ipa-data/
# 重新执行 4.3 的 docker run 命令启动容器
```

---

## 十三、故障排查

### 13.1 用户无法 SSH 登录

```bash
# 1. 检查 SSSD
sudo systemctl status sssd

# 2. 清除 SSSD 缓存
sudo sss_cache -E
sudo systemctl restart sssd

# 3. 检查 DNS
nslookup ipa.lab.local

# 4. 测试 Kerberos
kinit zhangsan

# 5. 查看日志
sudo tail -f /var/log/sssd/sssd_lab.local.log
```

### 13.2 FreeIPA Web UI 无法访问

```bash
# 检查容器是否在运行
sudo docker ps | grep freeipa-server

# 查看容器日志
sudo docker logs freeipa-server

# 重启容器
sudo docker restart freeipa-server

# 检查容器内服务状态
sudo docker exec -it freeipa-server ipactl status
sudo docker exec -it freeipa-server ipactl restart
```

### 13.3 Guacamole LDAP 认证失败

```bash
docker logs guacamole

# 测试 LDAP 连接
ldapsearch -x -H ldap://192.168.1.10 -D "cn=Directory Manager" \
  -W -b "cn=users,cn=accounts,dc=lab,dc=local" "(uid=zhangsan)"
```

### 13.4 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `Clock skew too great` | 时间不同步 | `sudo chronyc -a makestep` |
| `Unable to resolve host` | DNS 解析失败 | 检查 `/etc/hosts` 和 DNS |
| `No credentials cache found` | Kerberos 票据过期 | `sudo docker exec -it freeipa-server kinit admin` |
| `Password expired` | 密码过期 | FreeIPA 上重置密码 |
| 开机后 keytab 失效 | FreeIPA 更新了主机密钥 | 执行开机自检脚本或手动 `ipa-client-install` |

---

## 十四、方案优缺点

### 14.1 优点

| 优点 | 说明 |
|------|------|
| **统一用户管理** | FreeIPA Web 页面管理所有用户，增删改即时生效 |
| **密码天然同步** | VM 不存密码，实时查询 LDAP |
| **Web SSH 终端** | Guacamole 提供浏览器端 SSH |
| **有效期 10 年** | 已配置所有关键有效期 10 年，适配长期关机 |
| **开机自检** | 自动检测 keytab/证书/SSSD 状态 |
| **sudo 统一管控** | FreeIPA 统一配置 sudo 权限 |
| **内置证书体系** | FreeIPA CA 签发主机/服务/用户证书 |
| **开源免费** | 全部组件开源，无授权费用 |

### 14.2 缺点与缓解

| 缺点 | 缓解措施 |
|------|----------|
| FreeIPA 单点故障 | 部署 Replica 副本实现高可用 |
| 需要 DNS 配合 | FreeIPA 自带 DNS，或手动配置 hosts |
| 学习成本 | 本文档按步操作即可 |
| keytab 可能过期 | 开机自检脚本自动发现并告警 |

---

## 十五、资源需求总结

| 组件 | 部署位置 | 数量 | 资源 |
|------|----------|:---:|------|
| FreeIPA Server (Docker) | ESXi VM | 1 | 2C2G, 20G |
| Guacamole Server | ESXi VM | 1 | 2C2G, 20G |
| 业务 VM | ESXi VM | N | 按需 |

---

## 十六、后续扩展方向

- **FreeIPA 副本（Replica）**：部署第二个 FreeIPA Server 实现高可用
- **HTTPS 反向代理**：Nginx 反代 Guacamole，使用 FreeIPA 签发的 SSL 证书
- **SSH Key 管理**：FreeIPA 中集中管理用户 SSH 公钥
- **HBAC 规则**：精细控制用户从哪些主机登录哪些服务
- **双因素认证**：FreeIPA 支持 OTP，Guacamole 支持 TOTP
- **外部 CA 集成**：FreeIPA CA 作为中间 CA 纳入企业 PKI
