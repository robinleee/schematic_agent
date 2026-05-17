# Ducc 远程机器配置指南

## 问题背景

在无法直接访问百度内网 Passport 服务的远程机器上，`ducc` 命令会出现以下错误：

- `ducc login` → `Get QR code failed`
- `ducc` → `error: failed to get username`

## 根因分析

### 1. QR 码登录失败

`ducc login` 需要访问 Baidu Passport（UUAP 认证中心）生成二维码，但该服务的内部 IP（10.11.x.x）从远程机器不可达。同时 `ducc` wrapper 脚本会强制清除代理：

```sh
unset http_proxy
unset https_proxy
unset HTTP_PROXY
unset HTTPS_PROXY
```

如果机器需要代理才能访问内网服务，清除代理后 Passport 服务更不可达。

### 2. 无法获取用户名

`ducc` 通过两种方式获取用户名：

1. **从 JWT Token 解析**（`getUsernameFromJWTToken`）—— `~/.baidu-cc/user.json` 中的 `ANTHROPIC_AUTH_TOKEN` 是 OneAPI Key（48字符），不是 JWT 格式，无法解析出用户名
2. **从 Platform Token 获取**（`getUsernameFromPlatformToken`）—— `BAIDU_CC_PLATFORM_TOKEN` 环境变量未设置

两条路径都走不通，导致 `failed to get username`。

### 3. Comate IDE 认证与 ducc CLI 认证是两套独立系统

| | Comate IDE | ducc CLI |
|---|---|---|
| 认证方式 | OneAPI Key（内部生成） | QR 码扫码 → JWT/Platform Token |
| Token 位置 | `user.json` 的 `ANTHROPIC_AUTH_TOKEN` | `COMATE_AUTH_TOKEN` 环境变量 |
| 用户名来源 | IDE 内部管理 | `BAIDU_CC_USERNAME` 环境变量 |

Comate IDE 重新登录**不会**自动为 `ducc` 设置 `COMATE_AUTH_TOKEN` 或 `BAIDU_CC_PLATFORM_TOKEN`。

## 解决方案

### 步骤一：设置环境变量

在 `~/.bashrc` 中添加：

```bash
export BAIDU_CC_USERNAME=<你的百度用户名>
export COMATE_AUTH_TOKEN=<你的OneAPI Key>
```

其中 `COMATE_AUTH_TOKEN` 的值即 `~/.baidu-cc/user.json` 中 `ANTHROPIC_AUTH_TOKEN` 的值。

生效：

```bash
source ~/.bashrc
```

### 步骤二：更新 ducc wrapper 脚本指向新版二进制

自动更新下载的新版二进制支持 `BAIDU_CC_USERNAME`，但 wrapper 脚本仍指向旧版。编辑 `~/.comate/baidu-cc/bin/ducc`，将末尾的：

```sh
# 拼出 claude-go 的绝对路径
CLAUDE_PATH="$PARENT_DIR/claude-go"

# 执行 claude-go，并把脚本的所有参数传过去
"$CLAUDE_PATH" "$@"
```

改为：

```sh
# 优先使用更新后的新版二进制
UPDATED_BIN="$ROOT_DIR/baidu-cc/bin/ducc"
if [ -x "$UPDATED_BIN" ]; then
    CLAUDE_PATH="$UPDATED_BIN"
else
    CLAUDE_PATH="$PARENT_DIR/claude-go"
fi

# 执行二进制，并把脚本的所有参数传过去
"$CLAUDE_PATH" "$@"
```

### 步骤三：创建 version 文件触发自动更新

### 步骤三：触发自动更新下载新版二进制

新版二进制支持 `BAIDU_CC_USERNAME` 环境变量，由旧版 `claude-go` 自动从 BOS 下载（公网可访问）。

如需手动触发，创建 version 文件后运行一次旧版二进制：

```bash
mkdir -p /home/caros/.comate-server/extensions/baidu.baidu-cc-<版本号>/baidu-cc/
echo "<版本号>" > /home/caros/.comate-server/extensions/baidu.baidu-cc-<版本号>/baidu-cc/version

# 运行一次旧版二进制，它会自动检查更新并下载新版
/home/caros/.comate-server/extensions/baidu.baidu-cc-<版本号>/resources/native-binary/claude-go --version
```

更新成功后会看到类似输出：
```
Try to update baidu-cc client, current version is [2.1.76-rc.8] ...
baidu-cc client updates from [2.1.76-rc.8] to [2.1.138.1] successfully!
```

### 验证

```bash
ducc models
ducc --version
```

## 模型配置

### 命令行修改（推荐）

```bash
ducc config model <模型名>     # 设置默认模型
ducc models                     # 查看可用模型
```

### 编辑配置文件

修改 `~/.baidu-cc/user.json`：

```json
{
  "env": {
    "ANTHROPIC_MODEL": "Kimi-K2.6",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "GLM-5.1",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "GLM-5.1",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "Kimi-K2.6"
  }
}
```

| 字段 | 用途 |
|---|---|
| `ANTHROPIC_MODEL` | 默认模型 |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | 快速/轻量模型 |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | 中等模型 |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | 重型模型 |

### 启动时临时指定

```bash
ducc --model Claude-Sonnet-4.6
```

## 关键文件路径

| 文件 | 路径 | 用途 |
|---|---|---|
| 用户配置 | `~/.baidu-cc/user.json` | 存储 Token 和模型偏好 |
| ducc wrapper | `~/.comate/baidu-cc/bin/ducc` | 启动脚本 |
| 旧版二进制 | `.../resources/native-binary/claude-go` | 不支持 BAIDU_CC_USERNAME |
| 新版二进制 | `.../baidu-cc/bin/ducc` → `claude` | 支持 BAIDU_CC_USERNAME |
| settings.json | `.../resources/settings.json` | API 网关、权限、钩子配置 |

## 功能可用性

| 功能 | 是否需要完整内网 | 说明 |
|---|---|---|
| 模型调用/对话 | 否，只需 OneAPI 网关 | `oneapi-comate.baidu-int.com` |
| `ducc models` | 否 | 同上 |
| `ducc config` | 否 | 本地操作 |
| `ducc login`（扫码登录） | 是 | 需要 Passport 服务 |
| 自动更新 | 部分 | 下载服务可能不可达 |

## 注意事项

1. **Token 过期**：`COMATE_AUTH_TOKEN`（OneAPI Key）如果过期，需要从能正常登录的机器（如本地 Mac）重新获取并更新 `~/.bashrc` 中的值
2. **警告可忽略**：运行时可能出现 `warning: COMATE_AUTH_TOKEN authentication failed: failed to get username`，不影响使用
3. **wrapper 脚本更新**：如果 Comate 扩展更新，wrapper 脚本可能被覆盖，需要重新修改指向新版二进制
4. **如需帮助**：百度 CC 如流用户群 12431011
