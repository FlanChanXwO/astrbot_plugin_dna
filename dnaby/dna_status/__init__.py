"""状态指标模块（AstrBot 移植中的可选能力）。

原 gsucore ``register_status`` 注册的 Dashboard 状态指标在 AstrBot 移植中为可选能力，
本阶段暂不注册任何指标。保留以下数据统计函数供未来接入。
"""

from ..utils.database.models import DNASign, DNAUser
from ..utils.utils import get_yesterday_date


async def get_today_sign_num():
    datas = await DNASign.get_all_sign_data_by_date()
    return len(datas)


async def get_yesterday_sign_num():
    yesterday = get_yesterday_date()
    datas = await DNASign.get_all_sign_data_by_date(date=yesterday)
    return len(datas)


async def get_user_num():
    datas = await DNAUser.get_dna_all_user()
    return len(datas)
