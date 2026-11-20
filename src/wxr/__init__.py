"""wxr —— WeChat macOS 本地数据工具包。

分层：
  config   配置与路径解析（唯一来源）
  wx       快照 + 只读查询 + zstd
  core     会话语义层（会话/消息/发送者/搜索）
  llm      模型调用
  digest / chatquery / watcher / daily / autoreply   能力
  web      本地服务与页面
  pipeline 离线批处理（导出、建库、生成 HTML、画像）
"""
__version__ = "1.0.0"
