# Active Directory Penetration Specialist

最新 AD 攻击技术，覆盖 Kerberos / ADCS / ESC1-16 / 横向移动。

## 核心能力

AD 域渗透、证书服务攻击、Kerberos 票据攻击、域提权。

## 攻击矩阵

### Kerberos 攻击

**AS-REP Roasting**
```
# 不需要凭据，枚举不需要预认证的用户
Get-DomainUser -PreauthNotRequired | Get-ASREPHash
```

**Kerberoasting**
```
# 请求服务票据，离线破解
Get-DomainUser -SPN | Get-SPNTicket | john --wordlist=rockyou.txt
```

**Reflective Kerberos Relay (2025新!)**
- 低权限域用户 → NT AUTHORITY\SYSTEM (工作站/服务器)
- 强制目标机器向攻击者认证 Kerberos 服务票据
- 通过 krbrelayx 转述回同一主机 = 提升的 SMB 会话
- 影响: 所有 Windows 10/11 ≤23H2, 所有 Windows Server 含 2025

**BadSuccessor — dMSA 提权 (Windows Server 2025)**
- 利用委托管理服务账户特性
- 默认配置即可利用
- 工具: SharpSuccessor / BadSuccessor.ps1

### ADCS 攻击 (ESC1-16)

| 技术 | 利用条件 | 影响 |
|------|----------|------|
| **ESC1** | 模板允许 ENROLLEE_SUPPLIES_SUBJECT + Client Auth EKU | → Domain Admin |
| **ESC4** | 对 CA 模板有 Write 权限 | 修改模板启用 ESC1 |
| **ESC8** | ADCS Web Enrollment HTTP 端点 | NTLM Relay → 证书注册 |
| **ESC10** | StrongCertificateBindingEnforcement=0 + GenericWrite | → Domain Admin |
| **ESC14** | 对 altSecurityIdentities 有 Write | 注入恶意证书映射 → DCSync |

### 工具链
```
Certipy:  ADCS 全链利用
Rubeus:   Kerberos 票据操作
BloodHound CE: 攻击路径图分析
krbrelayx: Kerberos 中继
ntlmrelayx: NTLM 中继 (含 WebDAV + --serve-image)
ADScan:   Linux 下全流程 (枚举→Roasting→ESC→DCSync)
ldeep:    LDAP 枚举
```

### 典型攻击链
```
1. 低权限域账户
2. BloodHound 枚举攻击路径
3. AS-REP / Kerberoast 获取哈希
4. 破解或中继
5. ADCS ESC1/ESC10 获取 Domain Admin 证书
6. DCSync 获取 krbtgt hash
7. Golden Ticket 持久化
```

### OPSEC 规避
- AS-REP 用 AES256 etype (0x12) 而非 RC4
- 设置 Name-canonicalize flag (0x40810010)
- 从浏览器进程注入 (msedge.exe) 绕过 Kerberos 流量检测
- 伪造登录时间、SID、PAC 签名

## 实验环境
- GOAD (Game of Active Directory)
- BadBlood
- Ludus
