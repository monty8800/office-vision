"""Debug Center（开发调试中心）—— 独立模块。

设计约束（用户 Spec）：
- 调试代码不散落在业务代码中：本包是唯一载体，业务侧仅有一个可选 frame_tap 钩子
- 所有调试数据通过 EventBus 获取，不读取业务模块内部状态
- 新增 Detector / Plugin 后自动展示（事件驱动 + 注册机制），无需修改本模块
- 仅 debug.enabled=true 时装配；发布版零开销
"""
