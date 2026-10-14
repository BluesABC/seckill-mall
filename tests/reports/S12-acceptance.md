# S12 非视觉验证码替代验收

日期：2026-10-14。S5-003要求视障用户能完成秒杀验证；本阶段在保留图片验证码的同时，新增屏幕阅读器可读取的文字算术题。

## 实现

- C++使用OpenSSL安全随机数生成两个10–99的加数，响应返回`mode=accessible`及中文题面；不返回答案，也不返回图片。
- 答案SHA256摘要继续绑定用户、活动、SKU和活动epoch保存在Redis。原有60秒过期、最多5次错误、一次性兑换与双凭证交易流程不变。
- Vue提供模式切换和重新出题，题面放在`role=status`/`aria-live=polite`区域，数字输入使用明确标签、数字键盘和1–6位校验。

## WSL 验收

- 环境：Ubuntu 24.04.4 / WSL2；C++、CMake、Python3.12.3、Java21.0.12.1、Maven、Node22.20.0、Docker29.8.2、Chromium141。
- `bash scripts/test-s2.sh`：CTest 3/3，真实C++/Redis接口24/24；文字题错误答案拒绝、正确答案发放一次性凭证、答案不在响应中、未知mode拒绝。
- `bash scripts/test-s5-wsl.sh`：Java verify成功，Vue/TypeScript生产构建成功，真实Chromium浏览器17/17。第二笔真实商城订单切换到文字模式，题目答案由浏览器按可见题面求得，经C++→RocketMQ→Java/MySQL建单，随后超时关闭；axe页面检查通过。
- SQL核对：2笔唯一订单、1笔MOCK支付；状态PAID 1 / CLOSED 1，库存守恒检查PASS。无JavaScript异常。
- 验收退出码：两入口最终运行均为0。逐项结果：`wsl/sports-ui/results.json`；数据库核验：`wsl/sports-ui/sql.json`；无障碍验证码截图：`wsl/sports-ui/accessible-captcha.png`；S2复跑日志：`wsl/s12-s2-run.log`；完整浏览器日志：`wsl/s5-run.log`。

自动axe及Chromium检查验证了可读题面语义和真实流程，不等于NVDA/JAWS等读屏软件人工认证。算术题是基础挑战，不保证抗自动化求解；生产防刷仍需真实风险控制与容量验证。
