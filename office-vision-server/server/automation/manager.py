"""Automation Engine（后续版本实现）。

只订阅事件，例如：
    SmokingStarted → 开启空气净化器 + 空调换气
    SmokingEnded + 10 分钟 → 关闭设备

Vision Engine / Agent 永不直接控制设备。
"""
