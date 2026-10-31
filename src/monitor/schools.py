# -*- coding: utf-8 -*-
"""监测版内置院校名单：985 / 211 工程高校 → ESI 机构名（Filter Value）与省份。

ESI 名逐校对照 `数据与复现/ESI数据/202609/Institutions.xlsx` 核验（2026-10-31，CHINA MAINLAND
范围内）。三条命名规律写在这里，给后续补录的人：
- ESI 用 `&` 代 AND（HUAZHONG UNIVERSITY OF SCIENCE & TECHNOLOGY）；
- 与海外校撞名时加 `- CHINA` 消歧（SOUTHEAST UNIVERSITY - CHINA）；
- 个别校用拼音/现名（XIZANG UNIVERSITY、NAVAL MEDICAL UNIVERSITY）。
中国矿业大学 / 中国石油大学 / 中国地质大学在 ESI 是**单一实体**（多校区不分立），
故只列三条主卡；中国政法大学未入 ESI 机构总表（低于收录线），报告按「未入册」如实出。
"""
from __future__ import annotations

#: (中文名, ESI 机构名, 省份/直辖市, 是否985)——UI 槽位顺序即此顺序：985 在前。
SCHOOLS: list[dict] = [
    {"cn": "清华大学", "en": "TSINGHUA UNIVERSITY", "prov": "北京", "is985": True},
    {"cn": "北京大学", "en": "PEKING UNIVERSITY", "prov": "北京", "is985": True},
    {"cn": "中国人民大学", "en": "RENMIN UNIVERSITY OF CHINA", "prov": "北京", "is985": True},
    {"cn": "北京航空航天大学", "en": "BEIHANG UNIVERSITY", "prov": "北京", "is985": True},
    {"cn": "北京理工大学", "en": "BEIJING INSTITUTE OF TECHNOLOGY", "prov": "北京", "is985": True},
    {"cn": "北京师范大学", "en": "BEIJING NORMAL UNIVERSITY", "prov": "北京", "is985": True},
    {"cn": "中国农业大学", "en": "CHINA AGRICULTURAL UNIVERSITY", "prov": "北京", "is985": True},
    {"cn": "中央民族大学", "en": "MINZU UNIVERSITY OF CHINA", "prov": "北京", "is985": True},
    {"cn": "复旦大学", "en": "FUDAN UNIVERSITY", "prov": "上海", "is985": True},
    {"cn": "同济大学", "en": "TONGJI UNIVERSITY", "prov": "上海", "is985": True},
    {"cn": "上海交通大学", "en": "SHANGHAI JIAO TONG UNIVERSITY", "prov": "上海", "is985": True},
    {"cn": "华东师范大学", "en": "EAST CHINA NORMAL UNIVERSITY", "prov": "上海", "is985": True},
    {"cn": "南开大学", "en": "NANKAI UNIVERSITY", "prov": "天津", "is985": True},
    {"cn": "天津大学", "en": "TIANJIN UNIVERSITY", "prov": "天津", "is985": True},
    {"cn": "重庆大学", "en": "CHONGQING UNIVERSITY", "prov": "重庆", "is985": True},
    {"cn": "大连理工大学", "en": "DALIAN UNIVERSITY OF TECHNOLOGY", "prov": "辽宁", "is985": True},
    {"cn": "东北大学", "en": "NORTHEASTERN UNIVERSITY - CHINA", "prov": "辽宁", "is985": True},
    {"cn": "吉林大学", "en": "JILIN UNIVERSITY", "prov": "吉林", "is985": True},
    {"cn": "哈尔滨工业大学", "en": "HARBIN INSTITUTE OF TECHNOLOGY", "prov": "黑龙江", "is985": True},
    {"cn": "南京大学", "en": "NANJING UNIVERSITY", "prov": "江苏", "is985": True},
    {"cn": "东南大学", "en": "SOUTHEAST UNIVERSITY - CHINA", "prov": "江苏", "is985": True},
    {"cn": "浙江大学", "en": "ZHEJIANG UNIVERSITY", "prov": "浙江", "is985": True},
    {"cn": "中国科学技术大学", "en": "UNIVERSITY OF SCIENCE & TECHNOLOGY OF CHINA, CAS", "prov": "安徽", "is985": True},
    {"cn": "厦门大学", "en": "XIAMEN UNIVERSITY", "prov": "福建", "is985": True},
    {"cn": "山东大学", "en": "SHANDONG UNIVERSITY", "prov": "山东", "is985": True},
    {"cn": "中国海洋大学", "en": "OCEAN UNIVERSITY OF CHINA", "prov": "山东", "is985": True},
    {"cn": "武汉大学", "en": "WUHAN UNIVERSITY", "prov": "湖北", "is985": True},
    {"cn": "华中科技大学", "en": "HUAZHONG UNIVERSITY OF SCIENCE & TECHNOLOGY", "prov": "湖北", "is985": True},
    {"cn": "湖南大学", "en": "HUNAN UNIVERSITY", "prov": "湖南", "is985": True},
    {"cn": "中南大学", "en": "CENTRAL SOUTH UNIVERSITY", "prov": "湖南", "is985": True},
    {"cn": "国防科技大学", "en": "NATIONAL UNIVERSITY OF DEFENSE TECHNOLOGY - CHINA", "prov": "湖南", "is985": True},
    {"cn": "中山大学", "en": "SUN YAT SEN UNIVERSITY", "prov": "广东", "is985": True},
    {"cn": "华南理工大学", "en": "SOUTH CHINA UNIVERSITY OF TECHNOLOGY", "prov": "广东", "is985": True},
    {"cn": "四川大学", "en": "SICHUAN UNIVERSITY", "prov": "四川", "is985": True},
    {"cn": "电子科技大学", "en": "UNIVERSITY OF ELECTRONIC SCIENCE & TECHNOLOGY OF CHINA", "prov": "四川", "is985": True},
    {"cn": "西安交通大学", "en": "XI'AN JIAOTONG UNIVERSITY", "prov": "陕西", "is985": True},
    {"cn": "西北工业大学", "en": "NORTHWESTERN POLYTECHNICAL UNIVERSITY", "prov": "陕西", "is985": True},
    {"cn": "西北农林科技大学", "en": "NORTHWEST A&F UNIVERSITY - CHINA", "prov": "陕西", "is985": True},
    {"cn": "兰州大学", "en": "LANZHOU UNIVERSITY", "prov": "甘肃", "is985": True},
    # ---- 211 工程（非 985）----
    {"cn": "北京交通大学", "en": "BEIJING JIAOTONG UNIVERSITY", "prov": "北京", "is985": False},
    {"cn": "北京工业大学", "en": "BEIJING UNIVERSITY OF TECHNOLOGY", "prov": "北京", "is985": False},
    {"cn": "北京科技大学", "en": "UNIVERSITY OF SCIENCE & TECHNOLOGY BEIJING", "prov": "北京", "is985": False},
    {"cn": "北京化工大学", "en": "BEIJING UNIVERSITY OF CHEMICAL TECHNOLOGY", "prov": "北京", "is985": False},
    {"cn": "北京邮电大学", "en": "BEIJING UNIVERSITY OF POSTS & TELECOMMUNICATIONS", "prov": "北京", "is985": False},
    {"cn": "北京林业大学", "en": "BEIJING FORESTRY UNIVERSITY", "prov": "北京", "is985": False},
    {"cn": "北京中医药大学", "en": "BEIJING UNIVERSITY OF CHINESE MEDICINE", "prov": "北京", "is985": False},
    {"cn": "北京外国语大学", "en": "BEIJING FOREIGN STUDIES UNIVERSITY", "prov": "北京", "is985": False},
    {"cn": "中国传媒大学", "en": "COMMUNICATION UNIVERSITY OF CHINA", "prov": "北京", "is985": False},
    {"cn": "中央财经大学", "en": "CENTRAL UNIVERSITY OF FINANCE & ECONOMICS", "prov": "北京", "is985": False},
    {"cn": "对外经济贸易大学", "en": "UNIVERSITY OF INTERNATIONAL BUSINESS & ECONOMICS", "prov": "北京", "is985": False},
    {"cn": "中国政法大学", "en": "CHINA UNIVERSITY OF POLITICAL SCIENCE AND LAW", "prov": "北京", "is985": False},
    {"cn": "华北电力大学", "en": "NORTH CHINA ELECTRIC POWER UNIVERSITY", "prov": "北京", "is985": False},
    {"cn": "中国矿业大学", "en": "CHINA UNIVERSITY OF MINING & TECHNOLOGY", "prov": "江苏", "is985": False},
    {"cn": "中国石油大学", "en": "CHINA UNIVERSITY OF PETROLEUM", "prov": "山东", "is985": False},
    {"cn": "中国地质大学", "en": "CHINA UNIVERSITY OF GEOSCIENCES", "prov": "湖北", "is985": False},
    {"cn": "天津医科大学", "en": "TIANJIN MEDICAL UNIVERSITY", "prov": "天津", "is985": False},
    {"cn": "河北工业大学", "en": "HEBEI UNIVERSITY OF TECHNOLOGY", "prov": "河北", "is985": False},
    {"cn": "太原理工大学", "en": "TAIYUAN UNIVERSITY OF TECHNOLOGY", "prov": "山西", "is985": False},
    {"cn": "内蒙古大学", "en": "INNER MONGOLIA UNIVERSITY", "prov": "内蒙古", "is985": False},
    {"cn": "辽宁大学", "en": "LIAONING UNIVERSITY", "prov": "辽宁", "is985": False},
    {"cn": "大连海事大学", "en": "DALIAN MARITIME UNIVERSITY", "prov": "辽宁", "is985": False},
    {"cn": "延边大学", "en": "YANBIAN UNIVERSITY", "prov": "吉林", "is985": False},
    {"cn": "东北师范大学", "en": "NORTHEAST NORMAL UNIVERSITY - CHINA", "prov": "吉林", "is985": False},
    {"cn": "哈尔滨工程大学", "en": "HARBIN ENGINEERING UNIVERSITY", "prov": "黑龙江", "is985": False},
    {"cn": "东北农业大学", "en": "NORTHEAST AGRICULTURAL UNIVERSITY - CHINA", "prov": "黑龙江", "is985": False},
    {"cn": "东北林业大学", "en": "NORTHEAST FORESTRY UNIVERSITY - CHINA", "prov": "黑龙江", "is985": False},
    {"cn": "华东理工大学", "en": "EAST CHINA UNIVERSITY OF SCIENCE AND TECHNOLOGY", "prov": "上海", "is985": False},
    {"cn": "东华大学", "en": "DONGHUA UNIVERSITY", "prov": "上海", "is985": False},
    {"cn": "上海外国语大学", "en": "SHANGHAI INTERNATIONAL STUDIES UNIVERSITY", "prov": "上海", "is985": False},
    {"cn": "上海财经大学", "en": "SHANGHAI UNIVERSITY OF FINANCE & ECONOMICS", "prov": "上海", "is985": False},
    {"cn": "上海大学", "en": "SHANGHAI UNIVERSITY", "prov": "上海", "is985": False},
    {"cn": "海军军医大学", "en": "NAVAL MEDICAL UNIVERSITY", "prov": "上海", "is985": False},
    {"cn": "苏州大学", "en": "SOOCHOW UNIVERSITY - CHINA", "prov": "江苏", "is985": False},
    {"cn": "南京航空航天大学", "en": "NANJING UNIVERSITY OF AERONAUTICS & ASTRONAUTICS", "prov": "江苏", "is985": False},
    {"cn": "南京理工大学", "en": "NANJING UNIVERSITY OF SCIENCE & TECHNOLOGY", "prov": "江苏", "is985": False},
    {"cn": "河海大学", "en": "HOHAI UNIVERSITY", "prov": "江苏", "is985": False},
    {"cn": "江南大学", "en": "JIANGNAN UNIVERSITY", "prov": "江苏", "is985": False},
    {"cn": "南京农业大学", "en": "NANJING AGRICULTURAL UNIVERSITY", "prov": "江苏", "is985": False},
    {"cn": "中国药科大学", "en": "CHINA PHARMACEUTICAL UNIVERSITY", "prov": "江苏", "is985": False},
    {"cn": "南京师范大学", "en": "NANJING NORMAL UNIVERSITY", "prov": "江苏", "is985": False},
    {"cn": "合肥工业大学", "en": "HEFEI UNIVERSITY OF TECHNOLOGY", "prov": "安徽", "is985": False},
    {"cn": "安徽大学", "en": "ANHUI UNIVERSITY", "prov": "安徽", "is985": False},
    {"cn": "福州大学", "en": "FUZHOU UNIVERSITY", "prov": "福建", "is985": False},
    {"cn": "南昌大学", "en": "NANCHANG UNIVERSITY", "prov": "江西", "is985": False},
    {"cn": "郑州大学", "en": "ZHENGZHOU UNIVERSITY", "prov": "河南", "is985": False},
    {"cn": "武汉理工大学", "en": "WUHAN UNIVERSITY OF TECHNOLOGY", "prov": "湖北", "is985": False},
    {"cn": "华中师范大学", "en": "CENTRAL CHINA NORMAL UNIVERSITY", "prov": "湖北", "is985": False},
    {"cn": "中南财经政法大学", "en": "ZHONGNAN UNIVERSITY OF ECONOMICS & LAW", "prov": "湖北", "is985": False},
    {"cn": "华中农业大学", "en": "HUAZHONG AGRICULTURAL UNIVERSITY", "prov": "湖北", "is985": False},
    {"cn": "湖南师范大学", "en": "HUNAN NORMAL UNIVERSITY", "prov": "湖南", "is985": False},
    {"cn": "暨南大学", "en": "JINAN UNIVERSITY", "prov": "广东", "is985": False},
    {"cn": "华南师范大学", "en": "SOUTH CHINA NORMAL UNIVERSITY", "prov": "广东", "is985": False},
    {"cn": "广西大学", "en": "GUANGXI UNIVERSITY", "prov": "广西", "is985": False},
    {"cn": "海南大学", "en": "HAINAN UNIVERSITY", "prov": "海南", "is985": False},
    {"cn": "西南交通大学", "en": "SOUTHWEST JIAOTONG UNIVERSITY", "prov": "四川", "is985": False},
    {"cn": "西南财经大学", "en": "SOUTHWESTERN UNIVERSITY OF FINANCE & ECONOMICS - CHINA", "prov": "四川", "is985": False},
    {"cn": "四川农业大学", "en": "SICHUAN AGRICULTURAL UNIVERSITY", "prov": "四川", "is985": False},
    {"cn": "西南大学", "en": "SOUTHWEST UNIVERSITY - CHINA", "prov": "重庆", "is985": False},
    {"cn": "贵州大学", "en": "GUIZHOU UNIVERSITY", "prov": "贵州", "is985": False},
    {"cn": "云南大学", "en": "YUNNAN UNIVERSITY", "prov": "云南", "is985": False},
    {"cn": "西藏大学", "en": "XIZANG UNIVERSITY", "prov": "西藏", "is985": False},
    {"cn": "西北大学", "en": "NORTHWEST UNIVERSITY XI'AN", "prov": "陕西", "is985": False},
    {"cn": "西安电子科技大学", "en": "XIDIAN UNIVERSITY", "prov": "陕西", "is985": False},
    {"cn": "长安大学", "en": "CHANG'AN UNIVERSITY", "prov": "陕西", "is985": False},
    {"cn": "陕西师范大学", "en": "SHAANXI NORMAL UNIVERSITY", "prov": "陕西", "is985": False},
    {"cn": "空军军医大学", "en": "AIR FORCE MEDICAL UNIVERSITY", "prov": "陕西", "is985": False},
    {"cn": "青海大学", "en": "QINGHAI UNIVERSITY", "prov": "青海", "is985": False},
    {"cn": "宁夏大学", "en": "NINGXIA UNIVERSITY", "prov": "宁夏", "is985": False},
    {"cn": "新疆大学", "en": "XINJIANG UNIVERSITY", "prov": "新疆", "is985": False},
    {"cn": "石河子大学", "en": "SHIHEZI UNIVERSITY", "prov": "新疆", "is985": False},
]

#: 省内关键词：按机构名在 CHINA MAINLAND 里捞同省机构（与内置名单同省者取并集）。
#: 抓大放小：不带省/市名的名校（如 UESTC、东北师大）由内置名单兜底。
PROVINCE_TOKENS: dict[str, list[str]] = {
    "北京": ["BEIJING"], "上海": ["SHANGHAI"], "天津": ["TIANJIN"], "重庆": ["CHONGQING"],
    "河北": ["HEBEI"], "山西": ["SHANXI"], "内蒙古": ["INNER MONGOLIA"],
    "辽宁": ["LIAONING"], "吉林": ["JILIN"], "黑龙江": ["HEILONGJIANG"],
    "江苏": ["JIANGSU", "NANJING"], "浙江": ["ZHEJIANG", "HANGZHOU"], "安徽": ["ANHUI", "HEFEI"],
    "福建": ["FUJIAN", "FUZHOU", "XIAMEN"], "江西": ["JIANGXI"], "山东": ["SHANDONG"],
    "河南": ["HENAN", "ZHENGZHOU"], "湖北": ["HUBEI", "WUHAN"], "湖南": ["HUNAN", "CHANGSHA"],
    "广东": ["GUANGDONG", "CANTON"], "广西": ["GUANGXI"], "海南": ["HAINAN"],
    "四川": ["SICHUAN", "CHENGDU"], "贵州": ["GUIZHOU"], "云南": ["YUNNAN"],
    "西藏": ["XIZANG", "TIBET"], "陕西": ["SHAANXI", "XI'AN"], "甘肃": ["GANSU", "LANZHOU"],
    "青海": ["QINGHAI"], "宁夏": ["NINGXIA"], "新疆": ["XINJIANG"],
}


def find(cn: str) -> dict | None:
    """按中文名找校；找不到返回 None（不猜）。"""
    for s in SCHOOLS:
        if s["cn"] == cn:
            return s
    return None
