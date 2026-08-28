# 01 — FreeIPA 概述与核心概念

## 1.1 什么是 FreeIPA？

FreeIPA（Free Identity, Policy, Audit）是一个开源的**集中式身份认证与策略管理系统**。它是 Red Hat 主导的开源项目，对标微软的 Active Directory，专为 Linux/Unix 环境设计。

简单来说：**一个系统管所有账号** — 员工只需一套账号密码，就能登录公司所有服务器。

## 1.2 FreeIPA 解决什么问题？

| 痛点 | FreeIPA 的解决方案 |
|------|-------------------|
| 每台服务器单独创建用户，离职需逐台删除 | 统一用户目录，一处创建处处可用 |
| 密码策略各自为政，弱密码难以约束 | 集中密码策略，强制复杂度与定期更换 |
| 无法追踪谁在什么时候登录了哪台机器 | 集中审计日志 |
| 服务器之间没有信任关系 | Kerberos 单点登录（SSO） |
| 手动管理 sudo 权限不安全 | 集中 sudo 规则管理 |
| 证书管理混乱 | 内置 CA，自动签发与管理证书 |

## 1.3 核心组件

FreeIPA 不是一个单一软件，而是**多个开源项目的集成**：

```
┌─────────────────────────────────────────────┐
│                 FreeIPA Server               │
│                                              │
│  ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │ 389 DS   │ │ Kerberos │ │  Dogtag CA  │  │
│  │ (LDAP)   │ │  (KDC)   │ │   (PKI)     │  │
│  └──────────┘ └──────────┘ └─────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │  BIND    │ │  NTP     │ │  Apache     │  │
│  │  (DNS)   │ │ (时钟)   │ │  (Web UI)   │  │
│  └──────────┘ └──────────┘ └─────────────┘  │
│  ┌──────────────────────────────────────┐    │
│  │         SSSD (客户端集成)            │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### 各组件说明

| 组件 | 全称 | 作用 |
|------|------|------|
| **389 Directory Server** | LDAP 目录服务 | 存储用户、组、主机、策略等所有数据 |
| **MIT Kerberos (KDC)** | 票据认证中心 | 提供单点登录，用户只需一次认证 |
| **Dogtag Certificate System** | PKI 证书系统 | 内置 CA，自动签发 SSL/TLS 证书 |
| **BIND DNS** | 域名解析服务 | 管理域内 DNS，服务发现依赖 DNS |
| **NTP** | 时间同步 | Kerberos 严格要求时钟同步（默认 5 分钟内） |
| **Apache + Web UI** | 管理界面 | 浏览器访问 `https://<hostname>` 进行管理 |
| **SSSD** | 客户端服务 | 运行在客户端，与 FreeIPA 服务端通信 |

## 1.4 关键概念

### 1.4.1 Realm（域/领域）

Kerberos 的"王国"概念。**Realm 名一定全大写**，通常是域名的大写形式：

```
域名: thinkmeta.site
Realm: THINKMETA.SITE
```

### 1.4.2 Kerberos 认证原理（简化版）

```
用户            KDC（密钥分发中心）        目标服务器
 │                    │                      │
 │──① 我是谁？──────→│                      │
 │←──② 给你TGT──────│                      │
 │   (门票授予票据)  │                      │
 │                    │                      │
 │──③ 我要访问主机A──→│                      │
 │←──④ 给你ST────────│                      │
 │   (服务票据)      │                      │
 │                    │                      │
 │──⑤ 这是我的ST────→│─────────────────────→│
 │←──⑥ 欢迎───────←│                      │
```

- **TGT（Ticket Granting Ticket）**：用户登录时获取，有效期通常 24 小时，类似于"游乐园通票"
- **ST（Service Ticket）**：访问具体服务时获取，类似于"单个游乐项目的门票"
- 用户只输一次密码，后续由票据自动认证 — 这就是 **SSO（单点登录）**

### 1.4.3 LDAP 目录结构

FreeIPA 的 LDAP 目录是树形结构：

```
dc=thinkmeta,dc=site           ← 根（基于域名）
├── cn=accounts                ← 账户子树
│   ├── uid=zhangsan           ← 用户
│   ├── cn=ops                 ← 用户组
│   └── cn=dev                 ← 用户组
├── cn=computers               ← 主机子树
│   └── fqdn=dev.thinkmeta.site
├── cn=hbac                    ← 访问控制策略
├── cn=sudorules               ← Sudo 规则
└── cn=certificates            ← 证书
```

### 1.4.4 DNS 的重要性

DNS 是 FreeIPA 的**命脉**。FreeIPA 通过 DNS SRV 记录（服务发现记录）来定位各种服务：

```bash
# Kerberos 服务在哪个服务器？
_kerberos._tcp.thinkmeta.site.    SRV → ipa-local.thinkmeta.site
# LDAP 服务在哪个服务器？
_ldap._tcp.thinkmeta.site.        SRV → ipa-local.thinkmeta.site
```

如果 DNS 配置错误，客户端找不到服务器，一切都会失败。

## 1.5 FreeIPA 与 Active Directory 对比

| 方面 | FreeIPA | Active Directory |
|------|---------|-----------------|
| 许可证 | 开源免费 | 商业许可 |
| 主要平台 | Linux/Unix | Windows |
| 用户目录 | LDAP (389 DS) | LDAP (AD) |
| 认证协议 | Kerberos | Kerberos + NTLM |
| 管理界面 | Web UI + CLI | GUI + PowerShell |
| 组策略 | HBAC + Sudo Rules | GPO |
| Windows 客户端 | 有限支持 | 原生支持 |
| 多域信任 | 支持 | 支持 |

## 1.6 典型企业架构

```
                    ┌────────────────────────────────┐
                    │      FreeIPA Server (主)        │
                    │      ipa-local.thinkmeta.site   │
                    │      192.168.3.90               │
                    │      (Docker 部署)              │
                    └──────────┬─────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
    ┌─────▼─────┐       ┌─────▼─────┐       ┌─────▼─────┐
    │ dev 服务器 │       │ ops 服务器 │       │ db 服务器  │
    │ dev.xxx    │       │ ops.xxx    │       │ db.xxx     │
    │ Ubuntu26.04│       │ Ubuntu26.04│       │ Ubuntu26.04│
    └───────────┘       └───────────┘       └───────────┘
    
    所有服务器通过 ipa-client 接入
    用户统一在 FreeIPA Web UI 或 CLI 管理
    一个账号登录所有服务器
```

## 1.7 本教程系列覆盖场景

本教程基于实际搭建的 FreeIPA 环境（`thinkmeta.site` 域），覆盖以下场景：

1. 从零理解 FreeIPA 的核心概念 ← **你在看这里**
2. 规划网络、DNS、主机名
3. 用 Docker 部署 FreeIPA 服务器
4. 将 Ubuntu 服务器注册为客户端
5. 创建用户、用户组，管理用户生命周期
6. 配置 HBAC 和 Sudo 权限
7. 设置密码策略与安全加固
8. 管理 SSL 证书
9. 备份、恢复与灾难恢复
10. 日常运维命令速查
