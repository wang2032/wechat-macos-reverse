# 常用命令都收在这里；不使用 make 也能逐条拷出来跑。
#
#   make tools     编译 C 工具到 build/（wxq / wxdec / wxsql / wxhook.dylib）
#   make test      跑冒烟测试（不需要微信在跑）
#   make fmt       粗略格式化检查（可选）
#   make clean     清掉 build/ work/ out/ export/

PY      ?= python3
CC      ?= cc
SQLC    ?= /opt/homebrew/opt/sqlcipher
OPENSSL ?= /opt/homebrew/opt/openssl@3
BUILD   ?= build

TOOL_LIBS := $(SQLC)/lib/libsqlcipher.a $(OPENSSL)/lib/libcrypto.a
CFLAGS    := -O2 -I$(SQLC)/include -I$(OPENSSL)/include
LDFLAGS   := -framework Security -framework CoreFoundation -lz

.PHONY: all tools test clean dist fmt

all: tools

tools: $(BUILD)/wxq $(BUILD)/wxdec $(BUILD)/wxsql $(BUILD)/wxhook.dylib

$(BUILD):
	@mkdir -p $@

# 只读查询（静态链接，拷到别的机器也能跑）
$(BUILD)/wxq: tools/wxq.c | $(BUILD)
	$(CC) $(CFLAGS) -o $@ $< $(TOOL_LIBS) $(LDFLAGS)

# 整库解密
$(BUILD)/wxdec: tools/wxdec.c | $(BUILD)
	$(CC) $(CFLAGS) -o $@ $< $(TOOL_LIBS) $(LDFLAGS)

# 小工具：跑一条 SQL 看结果（调试用）
$(BUILD)/wxsql: tools/wxsql.c | $(BUILD)
	$(CC) $(CFLAGS) -o $@ $< $(TOOL_LIBS) $(LDFLAGS)

# 抓钥 dylib：微信主程序是 arm64e，必须同架构
$(BUILD)/wxhook.dylib: tools/wxhook_dylib.c | $(BUILD)
	$(CC) -O2 -arch arm64e -dynamiclib -o $@ $< -framework CoreFoundation
	@codesign -f -s - $@ && echo "signed: $@"

test:
	PYTHONPATH=src $(PY) -m pytest -q

fmt:
	PYTHONPATH=src $(PY) -m compileall -q src

clean:
	rm -rf $(BUILD) work out export data .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# 打一个可移植的插件包（DSH 用）
dist: 
	cd plugins/dsh && npm pack --pack-destination ../../dist
