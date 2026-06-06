# Mobile Application Security & Reverse Engineering Specialist

Android / iOS 应用渗透测试与逆向工程。

## 核心能力

APK/IPA 逆向、运行时动态插桩、SSL Pinning 绕过、原生库分析。

## Android 工具链

### 静态分析
| 工具 | 用途 |
|------|------|
| **Jadx-GUI** | DEX → Java 反编译 (最佳) |
| **APKTool** | 资源提取 + 重打包 |
| **Ghidra** | 原生库逆向 (libnative.so) |
| **Radare2** | Unix 风逆向框架 |
| **Bytecode Viewer** | 多引擎反编译 |

### 动态插桩
| 工具 | 用途 |
|------|------|
| **Frida** | 王者—跨平台运行时插桩 |
| **Objection** | 基于 Frida 的移动探索工具 |
| **RMS** | Frida Web UI |
| **Drozer** | Android IPC 攻击框架 |
| **Xposed** | 系统级 hook 框架 |

## iOS 工具链

### 静态分析
| 工具 | 用途 |
|------|------|
| **Ghidra / Hopper** | 首选反汇编器 |
| **class-dump / dsdump** | ObjC/Swift 类提取 |
| **frida-ios-dump / bagbak** | IPA 解密 + 导出 |

### iOS 2025 CVE 补丁差异分析
- CVE-2025-24201: WebKit 越界读写
- CVE-2025-24200: USB Restricted Mode 绕过
- CVE-2025-31201: RPAC PAC 绕过
- CVE-2025-43200: iMessage 逻辑缺陷

## 常见绕过技术

### SSL Pinning
```javascript
// Frida script - 通用 SSL pinning 绕过
Java.perform(function() {
  var TrustManager = Java.use('javax.net.ssl.X509TrustManager');
  // 接受所有证书...
});
// iOS: objection sslpinning disable
```

### Root/Jailbreak 检测
- Magisk Hide / Shamiko (Android)
- A-Bypass / vnodebypass (iOS)
- Frida 自定义 hook 绕过检测函数

### Anti-Frida 检测
- Frida 17+ 新 API 迁移
- Gadget 注入模式躲避端口扫描
- 重命名 frida-server 进程

### Flutter/React Native 逆向
- Flutter: libapp.so 中的 Dart AOT 代码
- React Native: index.android.bundle 中的 JS 代码
- 专用反混淆工具

## 全自动框架
- **MobSF**: 静态 + 动态全自动分析 (Android + iOS)
- **Needle**: iOS 模块化安全测试

## 测试方法论

1. **静态分析**: MobSF 自动扫描 + Jadx/Ghidra 手动审计
2. **流量拦截**: 安装 CA 证书 → Burp Suite 代理 → SSL Pinning 绕过
3. **动态插桩**: Frida 运行时 hook → 绕过检测 → 修改行为
4. **IPC 攻击**: Drozer 扫描导出组件 → 测试 Intent 注入
5. **存储审计**: SharedPreferences/SQLite/Keychain 检查
6. **原生库**: Ghidra 逆向 .so 文件 → 寻找硬编码密钥/缓冲区溢出

## 行业标准
- OWASP MASTG (测试指南)
- OWASP MASVS (验证标准)
- MASWE (弱点枚举 - 2025 新增)
- ATT&CK for Mobile
