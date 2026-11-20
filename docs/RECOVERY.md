# 事故记录：微信把库"工厂化"并换钥

这是真实踩过的坑，写下来是因为**它看起来像"聊天记录被删了"，其实数据还在**。

## 现象

- 微信里聊天记录突然全空，会话列表还在，点进去没消息。
- 磁盘上：

```
db_storage/message/message_0.db                        106,496 字节   ← 新的空库
db_storage/message/message_0.db.factory/
    2026-11-19_15-14-54.502190000/message_0.db         305,336,320 字节 ← 原来的库
    2026-11-19_15-14-54.502190000/message_0.db-wal
    2026-11-19_15-14-54.502190000/message_0.db-first.material
    2026-11-19_15-14-54.502190000/message_0.db-last.material
```

## 关键判断

| 文件 | 开头 16 字节（salt） | 用原 key 能开吗 |
|---|---|---|
| 原库 | `b3feee561e4d5c05e2ad9890a51591f4` | ✅ |
| `.factory` 里那份 | `fcefe8d583216c7d3d34d9aab1f14622` | ❌ `file is not a database` |
| 新建的空库 | `5c7a925499a9abb5b02fb5571d2aadf3` | ✅ |

salt 变了 ⇒ 微信在归档时**重新加密**（SQLCipher `rekey`）了那份库，新口令没有留存。
新库能被原 key 打开 ⇒ 账号主密钥本身没变，变的是归档副本。

## 恢复步骤

1. **先退出微信**（正常 `quit`，别强杀），避免它继续写。
2. 把 `.factory/<时间戳>/` 整个目录拷到安全位置（比如桌面），**原样保留 `-wal`**。
3. 找一个"换钥之前"的库副本。如果有 `cp -c` 克隆（推荐日常就留一份），直接用。
4. 替换：

```bash
# 备份当前空库
cp message_0.db message_0.db.broken

# 用旧库覆盖，并清掉不属于它的 wal/shm（关键，否则 SQLite 会尝试回放不匹配的 WAL）
rm -f message_0.db-wal message_0.db-shm
cp /path/to/good-copy.db message_0.db
```

5. 启动微信。验证是否成功：

```bash
ls -la message_0.db message_0.db-wal    # 出现新的 -wal 且大小在变 = 微信在用这个库
ls -d message_0.db.factory/*            # 没有新增目录 = 没有被再次工厂化
```

6. 剩下的缺口（从上次克隆到事故时刻）只能靠手机端 **聊天记录迁移到电脑** 补齐，那是官方合并路径，不会覆盖已有记录。

## 教训

- 日常留一份 `cp -c` 克隆（APFS 克隆基本不占空间），成本几乎为零。
- 一切读取走克隆 + 只读连接，不要对正在写的原库开连接。
- 看到 `.factory/` 先别慌也先别删——那是原数据，只是换了钥匙。
