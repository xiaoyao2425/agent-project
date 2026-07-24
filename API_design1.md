# 定制化Agent项目统一API设计规范 V1.0
## 文档说明
1. 适用项目：儿童语音助手 + RTL自动代码生成
2. 当前版本范围：仅同步文本生成接口 `/generate`。（异步任务、ASR/TTS、RAG、安全审核、评测等功能为后续迭代需求，目前暂未实现）
3. 调用方：儿童语音脚本、RTL需求生成脚本、自动化测试脚本
4. 通信协议：HTTP/1.1 + JSON（UTF-8）
5. Base URL：`http://<server_ip>:8000/api/v1`
6. 认证方式：请求Header固定携带 `X-API-Key: test_key_123`
7. 时间格式：全局统一 ISO 8601（当前版本仅日志打印使用，无业务依赖）

## 1. 精简设计原则
1. 同步优先：当前仅实现快速同步生成接口，单次请求超时限制100s；异步任务流水线规划于V1.1开发
2. 统一返回结构：所有接口固定 `code/message/data` 三层JSON结构，降低调用方解析成本
3. 轻量化可观测：所有请求携带唯一 `request_id`，日志用于问题定位，暂不落地持久化日志存储

## 2. 统一响应格式
### 2.1 成功响应模板
```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

### 2.2 错误响应模板
```json
{
  "code": 40001,
  "message": "参数缺失: prompt 字段为必填",
  "data": null
}
```

## 3. 生效错误码表（V0.1仅支持以下4种）
| 错误码 | 含义 | 触发场景 |
|--------|------|----------|
| 0 | 执行成功 | 接口正常返回生成内容 |
| 40001 | 参数缺失 | 请求体必填字段未传入 |
| 40100 | API-Key无效 | 请求头X-API-Key与服务密钥不匹配 |
| 50002 | 本地大模型调用异常 | Ollama/Qwen服务未启动、网络超时、模型报错 |

> 其余错误码统一规划至V1.1及之后版本，当前版本不支持。

## 4. 唯一可用接口：POST /generate
### 4.1 接口用途
统一文本生成入口，区分两条业务线：
- business=child：儿童对话、故事、科普问答生成，模型qwen2.5:7b，默认temperature=0.7
- business=rtl：Verilog硬件代码生成，模型qwen2.5-coder:7b，强制temperature=0.2

### 4.2 请求Header要求
| Header字段 | 取值 | 说明 |
|-----------|------|------|
| X-API-Key | test_key_123 | 必填，服务鉴权密钥 |

### 4.3 请求体字段说明
```json
{
  "business": "child",
  "prompt": "需要AI处理的文本内容",
  "temperature": 0.7,
  "max_tokens": 2048
}
```
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| business | string | 是 | 业务标识，仅支持 `child` / `rtl` |
| prompt | string | 是 | 用户提问/硬件需求描述 |
| temperature | float | 否 | 生成随机性，rtl业务会强制覆盖为0.2 |
| max_tokens | int | 否 | 最大输出文本长度，默认2048 |

### 4.4 请求示例
#### 示例1：儿童对话场景
```json
{
  "business": "child",
  "prompt": "讲一个小恐龙交朋友的小故事",
  "temperature": 0.7,
  "max_tokens": 1024
}
```

#### 示例2：RTL代码生成场景
```json
{
  "business": "rtl",
  "prompt": "生成8位计数器，带使能信号与异步低电平复位",
  "temperature": 0.2,
  "max_tokens": 2048
}
```

### 4.5 正常响应示例
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "text": "此处为AI生成完整文本/Verilog代码",
    "rag_used": false
  }
}
```
说明：`rag_used` 固定false，知识库检索功能8月迭代开发。

## 5. 认证与安全
1. 所有接口强制校验 `X-API-Key`，校验失败直接返回错误码40100；
2. 速率限制、多用户分级权限、密钥轮换管理为V1.3规划内容，当前版本无请求限流；
3. 密钥仅在服务代码内配置，禁止硬编码上传公共代码仓库。

## 6. 日志与可观测性
1. 每一次接口请求自动生成唯一 `request_id`，打印在控制台日志；
2. 作用：本地模型报错、参数异常时，通过request_id回溯完整请求信息；
3. 持久化日志、日志分割、按日期归档功能9月迭代实现，V0.1仅控制台输出。

## 7. 快速上手教程

### 7.1 启动API服务
```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```
在线调试文档地址：`http://127.0.0.1:8000/docs`

### 7.2  Python调用示例脚本
```python
import requests

url = "http://127.0.0.1:8000/api/v1/generate"
headers = {
    "X-API-Key": "test_key_123",
    "Content-Type": "application/json"
}
body = {
    "business": "rtl",
    "prompt": "生成8位异步复位计数器"
}

resp = requests.post(url, json=body, headers=headers)
print(resp.json())
```


## 8. 后续迭代规划（V1.1~V1.3待开发功能）
1. V1.1（8月中旬）
   - 全套异步任务接口：任务提交、状态查询、任务取消、任务状态机
   - RAG知识库检索、文档入库接口
   - 完整错误码覆盖、基础重试降级策略
2. V1.2（9月初）
   - ASR语音转文字、TTS文字转语音接口
   - 内容安全审核接口、完整持久化日志系统
3. V1.3（10月起）
   - 请求速率限制、批量任务提交
   - 模型版本管理、自动化评测报表接口
   - 任务过期自动清理、分级权限管控

## 9. 常见问题FAQ
1. 报错40100：X-API-Key填写错误，固定密钥为 `test_key_123`
2. 报错50002：检查Ollama是否正常启动、对应模型是否已拉取
3. 报错40001：请求体缺少business或prompt必填字段
4. RTL生成代码质量差：确认business参数填写为rtl，服务会自动调低temperature