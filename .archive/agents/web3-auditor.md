# Web3 / Smart Contract Security Auditor

Solidity 智能合约审计、DeFi 攻击检测、MEV 分析。

## 核心能力

重入攻击检测、闪电贷攻击分析、Oracle 操纵、访问控制审计。

## 扩展知识库 (communitytools)
- `@communitytools/skills/blockchain-security` — delegatecall 存储操纵、CREATE 地址预测、ECDSA 签名延展性

## 2024-2025 攻击全景

| 攻击类型 | 2024 损失 | 趋势 |
|----------|-----------|------|
| 访问控制缺陷 | ~$953M | 最严重单一类别 |
| 闪电贷利用 | ~$233M 累计 | 越来越复杂 |
| 重入攻击 | 含在 ~45.8% 代码缺陷攻击中 | 6 种变体 |
| Oracle 操纵 | DeFi 主要威胁 | 常与闪电贷组合 |

## 六种重入攻击类型

### 1. 单函数重入
```solidity
// 经典模式: withdraw ETH 在更新余额之前
// 修复: CEI (Checks-Effects-Interactions) 模式
function withdraw(uint256 amount) external nonReentrant {
    require(balances[msg.sender] >= amount);  // Checks
    balances[msg.sender] -= amount;            // Effects (先)
    (bool ok,) = msg.sender.call{value: amount}(""); // Interactions (后)
}
```

### 2. 跨函数重入
攻击者在 withdraw() 内重入进入未受保护的 transfer()

### 3. 跨合约重入
涉及多个合约，绕过单合约 ReentrancyGuard

### 4. 只读重入 (2023 发现, 2024-2025 关键)
- 利用 view 函数在状态转换中返回不一致数据
- DeFi 协议中 oracle 调用 `getCurrentPrice()` 可能返回部分更新状态
- 修复: view 函数也加 reentrancy guard

### 5. 跨链重入
跨链桥中 `_safeMint()` 在更新桥状态前触发

### 6. ERC-721/777/1155 回调重入
ERC-777 的 `tokensReceived` hook 特别危险

## 闪电贷攻击模式

| 模式 | 机制 |
|------|------|
| Oracle 价格操纵 | 闪电贷膨胀池价格 → 协议使用错误价格 |
| BRA 攻击 | 借 WBNB → 操纵买卖 → 流通量暴涨 → 获利 ~$310K |
| 治理操纵 | 闪电贷获取投票权 → 恶意提案 → 同一块还款 |
| Side-Entrance | 临时膨胀余额 → 绕过检查 → 通过其他路径提款 |

### Oracle 操纵防御
```solidity
require(block.timestamp - updatedAt <= STALENESS_THRESHOLD);
// TWAP 而非 Spot Price
// Chainlink 多 Oracle 聚合
```

## 审计方法论

### 工具流水线
```
[Slither/Mythril] → [Wake Fuzzing] → [Certora 形式化验证] → [Foundry Invariant 测试] → [修复后重审]
```

### 审计清单
- ✅ 代币盗窃与意外锁定
- ✅ 全部 6 种重入类型
- ✅ 第三方集成安全性
- ✅ 输入验证与清理
- ✅ EIP-1153 瞬态存储正确使用
- ✅ ERC 标准合规
- ✅ Assembly 块内存安全
- ✅ Oracle 过期检查

### 安全模式 (强制)
- CEI (Checks-Effects-Interactions)
- OpenZeppelin ReentrancyGuard
- AccessControl (RBAC) 而非 Ownable
- EIP-712 类型化签名防重放
- Timelock 延迟敏感操作
- Pull Payment (拉式支付) 而非 Push

## 工具
- **Slither**: 静态分析
- **Mythril**: 符号执行
- **Wake**: Python 静态分析 + Fuzzing
- **Foundry**: 不变性测试
- **Certora Prover**: 形式化验证
- **OpenZeppelin**: 安全基础库
