"""玩法协调层共享的运行时错误。"""


class StalePreparationError(RuntimeError):
    """锁外准备结果连续过期，调用方应重新发起操作。"""


__all__ = ["StalePreparationError"]
