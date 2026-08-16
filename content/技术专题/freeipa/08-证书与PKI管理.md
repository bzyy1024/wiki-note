# 08 — 证书与 PKI 管理

## 8.1 FreeIPA 中的 PKI 体系

FreeIPA 内置 **Dogtag Certificate System**，是一个完整的 PKI（公钥基础设施）。

### 证书层次结构

```
         ┌─────────────────────┐
         │   Root CA (自签名)   │
         │   CN=Certificate     │
         │   Authority,O=THINKMETA│
         └──────────┬──────────┘
                    │ 签发
         ┌──────────▼──────────┐
         │  IPA CA (从属 CA)    │
         │  (日常签发证书用)    │
         └──────────┬──────────┘
                    │ 签发
     ┌──────────────┼──────────────┐
     │              │              │
┌────▼────┐   ┌────▼────┐   ┌────▼────┐
│ 服务器   │   │ 用户    │   │ 服务    │
│ 证书    │   │ 证书    │   │ 证书    │
│ (HTTPS) │   │ (认证)  │   │ (LDAP等)│
└─────────┘   └─────────┘   └─────────┘
```

### FreeIPA 自动管理哪些证书？

| 证书类型 | 创建时机 | 用途 |
|---------|---------|------|
| 服务器 SSL 证书 | 安装 FreeIPA 时 | HTTPS Web UI |
| LDAP 服务证书 | 安装 FreeIPA 时 | LDAPS（636端口） |
| 主机证书 | **客户端接入时自动签发** | 主机间 Kerberos 认证 |
| 用户证书 | 按需手动签发 | 用户客户端证书认证 |
| 服务证书 | 按需手动签发 | 其他服务（如 Web 服务）的 HTTPS |

## 8.2 查看证书状态

```bash
# 查看 CA 状态
ipa cert-find

# 查看 CA 证书详情
ipa ca-show ipa

# 查看所有证书（包括自动签发的）
ipa cert-find --all

# 搜索特定主机证书
ipa cert-find --hostname=dev.thinkmeta.site

# 查看即将过期的证书
ipa cert-find --validnotafter-to="$(date -u -d '+30 days' +%Y-%m-%d)"
```

## 8.3 手动签发服务证书

### 场景：为内网 Web 服务签发 HTTPS 证书

```bash
# 1. 创建服务主体
ipa service-add HTTP/wiki.thinkmeta.site

# 2. 签发服务证书
ipa-getcert request \
  -f /etc/pki/tls/certs/wiki.crt \
  -k /etc/pki/tls/private/wiki.key \
  -N CN=wiki.thinkmeta.site \
  -D wiki.thinkmeta.site \
  -K HTTP/wiki.thinkmeta.site

# 3. 验证证书
openssl x509 -in /etc/pki/tls/certs/wiki.crt -text -noout

# 4. 查看证书追踪状态
getcert list
```

### 场景：获取当前主机的证书

```bash
# 查看本机由 certmonger 管理的证书
sudo getcert list

# 获取主机证书并保存
ipa-getcert request \
  -f /etc/pki/tls/certs/host.crt \
  -k /etc/pki/tls/private/host.key \
  -N CN=$(hostname -f)
```

## 8.4 证书续期

FreeIPA 证书默认有效期 2 年。**自动续期**由 `certmonger` 服务负责。

### 检查自动续期状态

```bash
# 在 FreeIPA 服务器上
docker exec freeipa-server getcert list

# 查看续期配置
docker exec freeipa-server getcert list | grep -A 5 "auto-renew"
```

### 手动续期证书

```bash
# 手动续期指定证书
getcert resubmit -i <request_id>

# 或强制续期所有证书
ipa-certupdate
```

### 续期 CA 证书（关键！）

```bash
# CA 证书过期会导致整个 IPA 体系崩溃
# 提前检查 CA 证书过期时间
ipa ca-show ipa | grep -i "expir"

# 手动更新 CA 证书链
ipa-cacert-manage renew
```

## 8.5 证书撤销

```bash
# 查看证书序列号
ipa cert-find --hostname=dev.thinkmeta.site

# 撤销证书（需要证书序列号）
ipa cert-revoke 0x0012

# 查看已撤销的证书
ipa cert-find --revocation-reason=6
```

撤销原因码：

| 码 | 含义 |
|----|------|
| 0 | 未指定 |
| 1 | 密钥泄露 |
| 2 | CA 泄露 |
| 3 | 从属关系变更 |
| 4 | 被取代 |
| 5 | 停止运营 |
| 6 | 证书冻结 |

## 8.6 外部 CA 集成

如果希望使用公司已有的 CA 或购买的公网证书：

### 方案一：安装时使用外部 CA

不在本教程 Docker 一键部署的使用范围，但原理如下：

```bash
ipa-server-install \
  --external-ca \
  ...其他参数...

# 会生成 CSR，提交给外部 CA 签名
# 然后：
ipa-server-install --external-cert-file=/path/to/signed.crt
```

### 方案二：替换现有 Web 证书

```bash
# 1. 获取外部签发的证书（假设已获取）
# 2. 导入证书
ipa-server-certinstall \
  -w \                          # Web 服务器证书
  -p /path/to/private.key \
  /path/to/certificate.crt

# 3. 重启 HTTP 服务
docker exec freeipa-server ipactl restart
```

## 8.7 客户端信任 FreeIPA CA

### Linux 客户端（Ubuntu）

注册 `ipa-client-install` 时会自动添加 CA 证书到系统信任链。

手动添加（如需）：

```bash
# 下载 CA 证书
curl -k -o /etc/ssl/certs/ipa-ca.crt https://ipa-local.thinkmeta.site/ipa/config/ca.crt

# 添加到系统信任链
sudo cp /etc/ssl/certs/ipa-ca.crt /usr/local/share/ca-certificates/ipa-ca.crt
sudo update-ca-certificates
```

### 浏览器信任

每个需要访问 Web UI 的浏览器都需要导入 CA：

1. 下载 CA 证书：`https://192.168.3.90/ipa/config/ca.crt`
2. Chrome：设置 → 隐私和安全 → 安全 → 管理证书 → 受信任的根证书颁发机构 → 导入
3. Firefox：设置 → 隐私与安全 → 证书 → 查看证书 → 导入

### Windows 客户端

```powershell
# 下载 CA 证书后
certutil -addstore -f "Root" ipa-ca.crt
```

## 8.8 证书最佳实践

```bash
# 1. 定期检查证书过期（建议加入监控）
ipa cert-find --validnotafter-to="$(date -u -d '+30 days' +%Y-%m-%d)"

# 2. 在证书过期前 30 天告警
# 可以写一个 cron 脚本：
# 0 9 * * * ipa cert-find --validnotafter-to="$(date -u -d '+30 days' +%Y-%m-%d)" | \
#   grep "Serial number" && echo "CERT EXPIRING!" | mail -s "CERT ALERT" admin@thinkmeta.site

# 3. 主机退役时撤销其证书
ipa host-del old-server.thinkmeta.site --updatedns
# host-del 会自动撤销相关证书

# 4. 定期备份 CA 密钥（非常重要！）
# CA 密钥丢失 = 整个 PKI 体系完蛋，需要重建
```

## 8.9 常见问题

### Q1：浏览器提示"您的连接不是私密连接"

这是自签名 CA 的正常警告。需要将 FreeIPA CA 证书导入浏览器信任链（见 8.7 节）。

### Q2：主机证书自动续期失败

```bash
# 查看 certmonger 日志
docker exec freeipa-server journalctl -u certmonger -f

# 手动触发续期
docker exec freeipa-server getcert resubmit -i <id>

# 清理并重新获取
getcert stop-tracking -i <id>
ipa-getcert request -f /path/to/cert -k /path/to/key ...
```

### Q3：CA 证书已过期怎么办？

这是严重问题。需要：

```bash
# 1. 先备份当前数据
# 2. 尝试续期
ipa-cacert-manage renew --force

# 3. 如果失败，可能需要重建 IPA
```

**再次强调：定期备份 `/data/docker-space/ipa-data/` 是救命稻草。**
