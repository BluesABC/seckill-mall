# 模型客服配置

2026-11-05 核对官方文档。默认测试配置选择 Groq 的 openai/gpt-oss-20b。这是 Groq 托管的开放权重模型。免费限额及地区、账户可用性以服务商控制台为准。

1. 在 https://console.groq.com/keys 创建密钥。
2. 在本机 deploy/.env.stack 的 MALL_SUPPORT_API_KEY 填入密钥。不要提交或发送密钥。
3. 模型地址、模型名参考 deploy/.env.support.example。
4. 构建订单服务镜像并重新创建订单容器后，用登录账号在商城客服发送问题。

当前每轮最多提供12条公开SKU快照，只覆盖目录子集。聊天及这些公开商品资料会发给所配置的服务商。客服最多返回150字符。没有配置密钥时，网页会标识并使用商城知识库回复。

Groq 文档 https://console.groq.com/docs/openai
免费限额 https://console.groq.com/docs/rate-limits
OpenAI GPT 文档 https://developers.openai.com/api/docs/models/gpt-4.1-mini
Gemini 免费层 https://ai.google.dev/gemini-api/docs/pricing

真实渠道调用须有服务商密钥。没有渠道成功返回前，构建或网页知识库回复均不作为模型联调成功。
