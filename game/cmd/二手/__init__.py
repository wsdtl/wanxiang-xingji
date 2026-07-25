"""归航市场与税务查询二级组件命令。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character_overview
from . import jobs as jobs  # noqa: F401
from . import service


@GameCommand.handler(
    cmd="二手",
    help=HelpSpec(
        category="资产",
        summary="浏览归航市场或查看指定挂单",
        usage=(
            "二手",
            "二手 页码",
            "二手 部位 [页码]",
            "二手 类别 [页码]",
            "二手 挂单编号",
        ),
        order=150,
    ),
)
async def market(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.market(message, overview)


@GameCommand.handler(
    cmd="上架",
    help=HelpSpec(
        category="资产",
        summary="按指定价格直接上架可交易物品",
        usage=("上架 物品编号 价格", "上架 物品编号 数量 价格"),
        side_effect="物品会直接进入挂单并暂时不能装配或回收",
        order=160,
    ),
)
async def list_item(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.list_item(message, overview)


@GameCommand.handler(
    cmd="下架",
    help=HelpSpec(
        category="资产",
        summary="撤销自己尚未成交的二手挂单",
        usage=("下架 挂单编号",),
        order=170,
    ),
)
async def cancel_listing(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.cancel_listing(message, overview)


@GameCommand.handler(
    cmd="购买",
    help=HelpSpec(
        category="资产",
        summary="直接购买一份二手挂单",
        usage=("购买 挂单编号",),
        side_effect="直接扣除货币并取得物品，卖方获得税后收入",
        order=180,
    ),
)
async def buy(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.buy(message, overview)


@GameCommand.handler(
    cmd="我的上架",
    help=HelpSpec(
        category="资产",
        summary="查看自己当前有效的二手挂单",
        usage=("我的上架", "我的上架 页码"),
        order=190,
    ),
)
async def my_listings(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.my_listings(message, overview)


@GameCommand.handler(
    cmd="税务",
    help=HelpSpec(
        category="资产",
        summary="查看归航公约的交易税务和归航库",
        usage=("税务",),
        order=200,
    ),
)
async def tax(overview=Depends(current_character_overview)) -> None:
    await service.tax(overview)


@GameCommand.handler(cmd="economy_market_list_confirm", hidden=True)
async def confirm_listing(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.confirm_listing(message, overview)


@GameCommand.handler(cmd="economy_market_buy_confirm", hidden=True)
async def confirm_purchase(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.confirm_purchase(message, overview)


__all__ = []
