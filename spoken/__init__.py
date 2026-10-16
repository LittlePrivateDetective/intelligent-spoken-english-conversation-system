"""spoken —— 智能英语口语教练（Windows 桌面版）。

选择场景和难度后，AI 扮演对应角色陪你进行英语对话：
语音说话自动识别、AI 语音回复、实时委婉纠错，结束后输出总结报告。
"""

import os as _os

# 禁用 huggingface_hub 的 Xet 下载协议：该协议走
# cas-server.xethub.hf.co 端点，经 hf-mirror.com 镜像下载模型时会
# 返回 401 Unauthorized。禁用后回退到普通 S3 通道，镜像下载正常。
# run.bat 中也会设置同样的环境变量，此处兜底保证任何启动方式生效。
_os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

__version__ = "1.1.2"
