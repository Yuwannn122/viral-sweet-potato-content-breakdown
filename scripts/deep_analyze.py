"""
Phase 3.5: AI 深度分析
读取 Phase 3 产出的 MD 骨架和 Phase 2 的分析数据，
生成 AI 深度分析 prompt，输出增强版 MD 和 DOCX。

设计理念：
- 脚本本身不调用外部 AI API（用户可能没有 API key）
- 脚本做两件事：
  1. 生成一份结构化 AI Prompt（.md 文件），让宿主 AI 在对话中完成分析
  2. 基于分析数据做**确定性填充**——不需要 AI 推理就能补全的内容（统计规律、模式识别）

用法：
    python deep_analyze.py ./data/<博主名>_analysis.json "<博主名>" -o ./output
    python deep_analyze.py ./data/<博主名>_analysis.json "<博主名>" -o ./output --details ./data/<博主名>_notes_details.json
"""

import json
import os
import sys
import re
import argparse
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.common import safe_filename, parse_count
from utils.md_to_docx import md_to_docx


# ----------------------------------------------------------
# 情感分析词库
# ----------------------------------------------------------
SENTIMENT_LEXICON = {
    "strong_positive": [
        "太棒了", "绝了", "太好了", "厉害", "宝藏", "神仙", "爱了",
        "受用", "干货", "收藏了", "学到了", "感谢分享", "太详细了",
        "太实用了", "良心", "用心", "走心", "受益匪浅", "醍醐灌顶",
        "亲测有效", "看了很多遍", "怒赞", "疯狂点赞", "反复观看",
        "照着做了", "回来交作业", "自从关注你", "最喜欢的博主",
        "神了", "封神", "无敌", "天才", "救命", "救我狗命",
        "停不下来", "一口气看完", "熬夜看完", "跪了", "膜拜",
    ],
    "positive": [
        "不错", "有用", "实用", "推荐", "收藏", "点赞", "谢谢",
        "感谢", "种草", "学习", "厉害", "可以", "喜欢", "好用",
        "清晰", "详细", "细致", "专业", "靠谱", "有收获", "有帮助",
        "真不错", "学到了", "试一试", "试试", "可以试试", "参考",
        "很棒", "挺好的", "记下了", "码住", "马住", "已收藏",
        "学习了", "谢谢分享", "感谢分享", "支持", "好棒", "优秀",
        "值得", "nice", "赞", "棒", "好", "get", "get了",
        "很实用", "非常实用", "很详细", "非常详细", "讲得好",
        # 短正向（容易因表情符号或短文本被误判为中性）
        "好看", "好美", "好漂亮", "好可爱", "好帅", "好酷", "好喜欢",
        "想要", "好想要", "爱了爱了", "绝绝子", "yyds", "太美了",
        "太可爱了", "太厉害了", "真好看", "好厉害", "好喜欢呀",
        "好看死了", "可爱死了", "太会了", "太强了", "太牛了",
        "想要同款", "求链接", "求推荐", "被种草了", "下单了",
        "果断关注", "关注了", "已关注", "真棒", "棒棒哒",
        "学到了学到了", "太有用了", "好干货", "干货满满",
    ],
    "negative": [
        "一般", "一般般", "还行吧", "也就那样", "不过如此",
        "有点难", "太复杂", "看不懂", "不太行", "没什么用",
        "还好", "凑合", "勉强", "不太实用", "有点水",
    ],
    "strong_negative": [
        "没用", "骗人", "垃圾", "浪费时间", "不好用", "失望",
        "割韭菜", "广告", "软广", "不推荐", "智商税", "太差了",
        "完全没有用", "根本不行", "踩雷", "避雷", "不要买",
        "太失望了", "被骗了", "大坑", "千万别买", "别信",
        "误人子弟", "瞎说", "乱讲", "扯淡", "坑", "烂",
    ],
    "negation_words": [
        "不", "没", "没有", "不是", "并非", "不算",
    ],
    "intensifiers": [
        "很", "非常", "极其", "特别", "真的", "确实", "超级", "贼",
        "太", "好", "相当", "十分",
    ],
}


# ----------------------------------------------------------
# 内容赛道分类词库
# ----------------------------------------------------------
CONTENT_TRACKS = {
    "美妆护肤": {
        "keywords": ["化妆", "口红", "眼影", "粉底", "腮红", "遮瑕", "眉笔", "睫毛", "眼线",
                     "护肤", "面膜", "精华", "面霜", "防晒", "卸妆", "洁面", "水乳",
                     "美妆", "彩妆", "妆容", "素颜", "底妆", "定妆", "补妆", "试色",
                     "好皮肤", "痘痘", "敏感肌", "干皮", "油皮", "美白", "抗老", "变美"],
        "sub_tracks": {
            "口红试色": ["口红", "唇釉", "唇泥", "色号", "试色", "嘴巴", "嘴唇", "镜面", "哑光"],
            "底妆测评": ["粉底", "气垫", "遮瑕", "底妆", "妆效", "持妆", "脱妆", "暗沉", "卡粉"],
            "化妆教程": ["教程", "新手", "画法", "步骤", "技巧", "公式", "思路", "保姆级"],
            "护肤流程": ["护肤", "面膜", "精华", "routine", "早晚", "流程", "步骤", "养肤"],
            "素颜改造": ["素颜", "改造", "妆前妆后", "对比", "变脸", "换头", "反差"],
        },
    },
    "穿搭时尚": {
        "keywords": ["穿搭", "OOTD", "outfit", "衣服", "裤子", "裙子", "外套", "衬衫", "毛衣",
                     "西装", "风衣", "卫衣", "T恤", "背心", "吊带", "阔腿裤", "牛仔裤",
                     "通勤", "日常", "约会", "上班", "显瘦", "显高", "小个子", "梨形",
                     "配色", "叠穿", "一衣多穿", "胶囊衣橱", "风格", "时尚", "搭配"],
        "sub_tracks": {
            "通勤穿搭": ["通勤", "上班", "职场", "office", "正式", "优雅", "气质", "简约"],
            "小个子穿搭": ["小个子", "显高", "160", "155", "矮个子", "比例", "拉长"],
            "一衣多穿": ["一衣多穿", "重复", "胶囊", "百搭", "利用率", "10件", "基础款"],
            "配色灵感": ["配色", "颜色", "色系", "撞色", "同色", "莫兰迪", "奶油", "高级感"],
        },
    },
    "美食烹饪": {
        "keywords": ["美食", "做饭", "做菜", "食谱", "菜谱", "烘焙", "烤箱", "空气炸锅",
                     "早餐", "午餐", "晚餐", "家常菜", "下饭菜", "快手菜", "减脂餐",
                     "食材", "调味", "厨房", "料理", "烹饪", "好吃", "美味", "甜品",
                     "蛋糕", "面包", "饼干", "冰淇淋", "巧克力", "饮料", "咖啡", "奶茶"],
        "sub_tracks": {
            "家常菜教程": ["家常", "下饭", "快手", "简单", "食材", "做法", "步骤", "新手"],
            "烘焙甜品": ["烘焙", "烤箱", "蛋糕", "面包", "饼干", "甜品", "奶油", "发酵"],
            "减脂健康餐": ["减脂", "低卡", "健康", "营养", "代餐", "控糖", "轻食", "沙拉"],
            "探店测评": ["探店", "打卡", "测评", "推荐", "排队", "网红店", "值得", "踩雷"],
        },
    },
    "AI科技": {
        "keywords": ["AI", "人工智能", "ChatGPT", "GPT", "Claude", "大模型", "机器学习",
                     "深度学习", "算法", "编程", "代码", "Python", "程序员", "开发者",
                     "工具", "效率", "自动化", "prompt", "提示词", "Agent", "Copilot",
                     "产品经理", "互联网", "科技", "数码", "软件", "App", "SaaS"],
        "sub_tracks": {
            "AI工具推荐": ["工具", "推荐", "好用", "必备", "神器", "效率", "省钱", "免费"],
            "AI产品分析": ["产品", "分析", "趋势", "行业", "深度", "思考", "未来", "机会"],
            "编程技术": ["编程", "代码", "Python", "程序", "开发", "技术", "工程师"],
            "效率提升": ["效率", "自动化", "工作流", "生产力", "技巧", "方法", "节省"],
        },
    },
    "家居生活": {
        "keywords": ["家居", "装修", "房间", "卧室", "客厅", "厨房", "卫生间", "收纳",
                     "整理", "清洁", "布置", "改造", "租房", "搬家", "软装", "家具",
                     "香薰", "氛围感", "治愈", "日常", "独居", "合租", "roomtour"],
        "sub_tracks": {
            "房间改造": ["改造", "布置", "翻新", "前后", "对比", "变化", "before", "after"],
            "收纳整理": ["收纳", "整理", "清洁", "断舍离", "整齐", "空间", "利用"],
            "Room Tour": ["roomtour", "room tour", "参观", "room", "house tour", "看房"],
            "独居生活": ["独居", "日常", "一个人", "治愈", "安静", "宅家", "周末"],
        },
    },
    "母婴育儿": {
        "keywords": ["宝宝", "母婴", "育儿", "孕期", "待产", "新生儿", "月子", "母乳",
                     "奶粉", "辅食", "早教", "绘本", "玩具", "亲子", "遛娃", "带娃",
                     "妈妈", "产后", "恢复", "育儿嫂", "幼儿园", "入学", "启蒙"],
        "sub_tracks": {
            "孕期记录": ["孕期", "怀孕", "产检", "待产包", "胎动", "体重", "肚子"],
            "辅食教程": ["辅食", "食谱", "添加", "阶段", "泥", "手指食物", "过敏"],
            "母婴好物": ["好物", "推荐", "必备", "实用", "省钱", "平替", "智商税"],
            "育儿经验": ["育儿", "经验", "睡眠", "哭闹", "习惯", "情绪", "沟通"],
        },
    },
    "运动健身": {
        "keywords": ["健身", "运动", "减肥", "瘦身", "增肌", "瑜伽", "普拉提", "跑步",
                     "撸铁", "健身房", "居家运动", "减脂", "马甲线", "腹肌", "有氧",
                     "拉伸", "体态", "体重", "卡路里", "蛋白", "打卡", "帕梅拉"],
        "sub_tracks": {
            "居家健身": ["居家", "在家", "无器械", "自重", "小空间", "地毯", "客厅"],
            "减肥记录": ["减肥", "瘦了", "体重", "变化", "对比", "坚持", "掉秤"],
            "体态矫正": ["体态", "驼背", "圆肩", "骨盆", "矫正", "拉伸", "改善"],
        },
    },
    "旅行户外": {
        "keywords": ["旅行", "旅游", "攻略", "打卡", "拍照", "徒步", "露营", "自驾",
                     "酒店", "民宿", "机票", "签证", "景点", "攻略", "行程", "路线",
                     "特种兵", "周末游", "周边", "小众", "免费", "避雷", "必去"],
        "sub_tracks": {
            "旅行攻略": ["攻略", "行程", "路线", "交通", "住宿", "花费", "预算", "建议"],
            "拍照打卡": ["拍照", "出片", "机位", "打卡", "好看", "绝了", "值得"],
            "露营户外": ["露营", "帐篷", "户外", "徒步", "骑行", "登山", "野外"],
        },
    },
    "职场成长": {
        "keywords": ["职场", "工作", "面试", "简历", "跳槽", "薪资", "副业", "升职",
                     "转行", "实习", "校招", "社招", "大厂", "创业", "自由职业",
                     "远程工作", "外包", "接单", "个人品牌", "linkedin", "脉脉",
                     "读书分享", "认知", "思维", "方法论", "底层逻辑", "复盘",
                     "沟通技巧", "向上管理", "汇报", "绩效", "OKR", "KPI", "团队管理"],
        "sub_tracks": {
            "求职面试": ["面试", "简历", "offer", "跳槽", "薪资", "谈判", "经验", "入职"],
            "职场技能": ["沟通", "汇报", "管理", "绩效", "OKR", "复盘", "效率", "工具"],
            "副业自由职业": ["副业", "自由职业", "远程工作", "接单", "个人品牌", "外包"],
            "读书分享": ["读书", "书单", "阅读", "推荐", "好书", "笔记", "读后感", "认知"],
        },
    },
    "情感心理": {
        "keywords": ["情感", "恋爱", "分手", "暗恋", "相亲", "婚姻", "情侣", "约会",
                     "心理", "情绪", "焦虑", "内耗", "自我", "边界", "沟通", "关系",
                     "独处", "朋友", "社交", "边界感", "讨好", "人格", "原生家庭"],
        "sub_tracks": {
            "恋爱关系": ["恋爱", "男朋友", "女朋友", "情侣", "约会", "分手", "复合", "相亲"],
            "自我成长": ["自我", "成长", "爱自己", "独立", "内核", "稳定", "情绪价值", "原生家庭"],
            "人际关系": ["朋友", "社交", "同事", "边界", "沟通", "冲突", "讨好", "PUA"],
        },
    },
    "摄影拍照": {
        "keywords": ["摄影", "拍照", "相机", "镜头", "手机摄影", "写真", "约拍", "街拍",
                     "调色", "滤镜", "修图", "构图", "光线", "人像", "风景", "胶片",
                     "CCD", "富士", "索尼", "佳能", "理光", "徕卡", "单反", "微单",
                     "出片", "拍照姿势", "拍照技巧", "P图", "后期", "LR", "Lightroom"],
        "sub_tracks": {
            "手机摄影": ["手机摄影", "iPhone", "手机拍", "原相机", "人像模式", "live图"],
            "相机推荐": ["相机", "CCD", "富士", "索尼", "佳能", "理光", "推荐", "选购", "对比"],
            "拍照姿势": ["拍照姿势", "pose", "怎么拍", "上镜", "显瘦", "显腿长", "剪刀手"],
            "调色教程": ["调色", "滤镜", "预设", "参数", "修图", "LR", "后期", "调色教程"],
        },
    },
    "宠物动物": {
        "keywords": ["宠物", "猫", "猫咪", "猫猫", "小猫", "英短", "美短", "布偶", "暹罗",
                     "狗", "狗狗", "小狗", "金毛", "柯基", "柴犬", "泰迪", "比熊",
                     "养猫", "养狗", "铲屎官", "猫粮", "狗粮", "罐头", "猫砂", "驱虫",
                     "绝育", "疫苗", "领养", "救助", "流浪猫", "流浪狗", "异宠", "仓鼠",
                     "兔子", "鹦鹉", "乌龟", "鱼", "萌宠", "吸猫", "撸猫", "遛狗"],
        "sub_tracks": {
            "猫咪日常": ["猫", "猫咪", "猫猫", "小猫", "吸猫", "撸猫", "猫粮", "猫砂", "铲屎官"],
            "狗狗日常": ["狗", "狗狗", "小狗", "遛狗", "狗粮", "金毛", "柯基", "柴犬", "泰迪"],
            "宠物好物": ["猫粮", "狗粮", "罐头", "零食", "玩具", "猫砂", "猫抓板", "推荐"],
            "新手养宠": ["新手", "养猫", "养狗", "接猫", "准备", "清单", "注意事项", "避雷"],
        },
    },
    "手工DIY": {
        "keywords": ["手工", "DIY", "手作", "编织", "钩针", "棒针", "毛线", "刺绣", "十字绣",
                     "手账", "手帐", "拼贴", "胶带", "贴纸", "火漆", "印章", "手写信", "子弹笔记", "bujo",
                     "画画", "绘画", "水彩", "油画棒", "素描", "速写", "彩铅", "马克笔",
                     "黏土", "石塑", "热缩片", "串珠", "珠绣", "布艺", "缝纫", "扎染",
                     "滴胶", "奶油胶", "手机壳DIY", "流体熊", "石膏涂色", "香薰蜡烛DIY", "手工皂DIY",
                     "涂色", "填色", "解压手工", "沉浸式手工", "手工教程", "DIY教程"],
        "sub_tracks": {
            "手账拼贴": ["手账", "手帐", "拼贴", "胶带", "贴纸", "排版", "子弹笔记", "bujo"],
            "钩针编织": ["钩针", "编织", "毛线", "棒针", "围巾", "毛衣", "钩织", "祖母格"],
            "画画教程": ["画画", "绘画", "水彩", "油画棒", "素描", "彩铅", "教程", "步骤图"],
            "手工饰品": ["串珠", "耳环", "项链", "手链", "戒指", "DIY饰品", "热缩片", "滴胶"],
        },
    },
    "教育学习": {
        "keywords": ["考研", "考公", "考编", "考证", "上岸", "二战", "三战", "脱产备考",
                     "英语学习", "雅思", "托福", "GRE", "GMAT", "四六级", "背单词", "口语",
                     "网课", "自学", "笔记法", "学习法", "艾宾浩斯", "记忆曲线",
                     "高考", "中考", "专升本", "留学", "申请季", "offer", "文书", "推荐信",
                     "论文", "毕设", "答辩", "博士", "研究生", "大学生", "高中生", "中学生",
                     "自律打卡", "时间管理", "专注", "番茄钟", "forest", "Notion学习",
                     "考试经验", "复习计划", "错题本", "知识点", "刷题", "真题", "模拟考"],
        "sub_tracks": {
            "考研考公": ["考研", "考公", "考编", "上岸", "复习", "资料", "经验", "规划"],
            "英语学习": ["英语", "雅思", "托福", "单词", "口语", "听力", "阅读", "写作", "四六级"],
            "学习方法": ["学习", "方法", "记忆", "笔记", "效率", "自律", "时间管理", "专注"],
            "留学申请": ["留学", "申请", "offer", "文书", "推荐信", "选校", "签证", "出国"],
        },
    },
    "财经理财": {
        "keywords": ["理财", "存钱", "省钱", "赚钱", "攒钱", "存款", "月薪", "工资理财",
                     "基金", "股票", "投资", "定投", "ETF", "A股", "美股", "港股", "收益",
                     "保险", "信用卡", "房贷", "车贷", "公积金", "社保", "个税", "退税",
                     "记账", "预算", "消费降级", "极简生活", "断舍离", "被动收入", "财务自由",
                     "FIRE", "搞钱", "副业收入", "加薪", "年终奖", "365天存钱", "存钱打卡"],
        "sub_tracks": {
            "存钱省钱": ["存钱", "省钱", "节约", "消费降级", "记账", "预算", "省钱技巧"],
            "基金理财": ["基金", "理财", "定投", "收益", "投资", "资产配置", "风险"],
            "攒钱目标": ["攒钱", "存款", "目标", "10万", "100万", "买房", "财务自由", "FIRE"],
            "保险科普": ["保险", "重疾", "医疗险", "意外险", "寿险", "社保", "配置", "理赔"],
        },
    },
    "游戏电竞": {
        "keywords": ["游戏", "手游", "主机", "switch", "PS5", "Xbox", "steam", "电竞",
                     "王者荣耀", "原神", "崩铁", "和平精英", "蛋仔派对", "恋与深空",
                     "塞尔达", "动森", "模拟人生", "星露谷", "Minecraft", "我的世界",
                     "开黑", "上分", "赛季", "皮肤", "抽卡", "攻略", "实况", "解说"],
        "sub_tracks": {
            "手游推荐": ["手游", "手机游戏", "APP", "推荐", "好玩", "休闲", "少女", "治愈"],
            "Switch游戏": ["switch", "任天堂", "塞尔达", "动森", "马里奥", "NS", "主机游戏"],
            "热门网游": ["王者荣耀", "原神", "崩铁", "和平精英", "蛋仔", "上分", "攻略"],
            "游戏日常": ["实况", "游戏日常", "开黑", "通关", "成就", "收集", "记录"],
        },
    },
    "汽车出行": {
        "keywords": ["汽车", "买车", "提车", "SUV", "轿车", "新能源", "电车", "特斯拉", "比亚迪",
                     "蔚来", "理想", "小鹏", "小米汽车", "试驾", "4S店", "用车", "养车",
                     "油耗", "充电", "续航", "智能驾驶", "自驾游", "车评", "落地价"],
        "sub_tracks": {
            "买车攻略": ["买车", "选车", "对比", "落地价", "砍价", "避坑", "推荐", "新手买车"],
            "新能源车": ["新能源", "电车", "特斯拉", "比亚迪", "蔚来", "理想", "充电", "续航"],
            "用车体验": ["提车", "用车", "驾驶", "座舱", "智驾", "改车", "好物", "车载"],
            "自驾旅行": ["自驾", "自驾游", "roadtrip", "房车", "露营车", "长途", "路线"],
        },
    },
    "医美健康": {
        "keywords": ["医美", "整形", "双眼皮", "隆鼻", "瘦脸", "玻尿酸", "肉毒素", "水光针",
                     "热玛吉", "超声炮", "光子嫩肤", "皮秒", "脱毛", "祛痘", "祛斑",
                     "正畸", "牙套", "隐形矫正", "种植牙", "洗牙", "根管", "拔智齿",
                     "中医", "艾灸", "拔罐", "养生", "泡脚", "八段锦", "推拿", "正骨",
                     "脱发", "生发", "植发", "米诺地尔", "防脱", "洗发水", "头皮"],
        "sub_tracks": {
            "皮肤管理": ["祛痘", "祛斑", "光子", "皮秒", "水光", "嫩肤", "清洁", "项目"],
            "牙齿矫正": ["正畸", "牙套", "隐形矫正", "保持器", "拔牙", "经验", "费用"],
            "中医养生": ["中医", "养生", "艾灸", "泡脚", "八段锦", "体质", "调理", "食疗"],
            "防脱生发": ["脱发", "生发", "植发", "米诺地尔", "发际线", "掉发", "洗发水"],
        },
    },
    "婚礼": {
        "keywords": ["婚礼", "结婚", "备婚", "婚纱照", "领证", "订婚", "婚戒", "钻戒",
                     "三金", "五金", "彩礼", "嫁妆", "伴娘", "伴郎", "婚宴", "酒店",
                     "婚礼策划", "婚庆", "四大金刚", "婚纱", "秀禾", "龙凤褂", "敬酒服",
                     "喜糖", "请柬", "婚房", "堵门", "接亲", "first look", "蜜月"],
        "sub_tracks": {
            "备婚攻略": ["备婚", "准备", "流程", "清单", "时间线", "预算", "避坑", "推荐"],
            "婚纱照": ["婚纱照", "婚纱摄影", "风格", "pose", "旅拍", "室内", "室外", "选片"],
            "婚礼现场": ["婚礼", "现场", "布置", "仪式", "创意", "感人", "first look", "誓言"],
            "婚品推荐": ["婚戒", "钻戒", "三金", "婚纱", "喜糖", "请柬", "伴手礼", "好物"],
        },
    },
    "影视娱乐": {
        "keywords": ["电影", "电视剧", "追剧", "综艺", "韩剧", "日剧", "美剧", "国产剧",
                     "纪录片", "动漫", "番剧", "B站", "Netflix", "豆瓣", "片单",
                     "推荐", "剧荒", "影评", "观后感", "角色", "剧情", "演技", "名场面",
                     "偶像", "明星", "爱豆", "演唱会", "音乐节", "livehouse", "脱口秀"],
        "sub_tracks": {
            "追剧推荐": ["追剧", "剧荒", "推荐", "片单", "韩剧", "国产剧", "Netflix", "好看"],
            "电影分享": ["电影", "豆瓣", "高分", "影评", "观后感", "经典", "冷门", "推荐"],
            "综艺娱乐": ["综艺", "真人秀", "脱口秀", "选秀", "搞笑", "下饭", "名场面"],
            "音乐现场": ["演唱会", "音乐节", "livehouse", "乐队", "现场", "抢票", "前排"],
        },
    },
    "数码3C": {
        "keywords": ["手机", "iPhone", "华为", "小米", "OPPO", "vivo", "三星", "平板", "iPad",
                     "电脑", "笔记本", "MacBook", "thinkpad", "显示器", "键盘", "鼠标",
                     "耳机", "AirPods", "音箱", "手表", "手环", "充电宝", "数据线", "支架",
                     "桌面", "桌搭", "电竞房", "外设", "开箱", "评测", "性价比"],
        "sub_tracks": {
            "手机推荐": ["手机", "iPhone", "华为", "小米", "性价比", "选购", "推荐", "旗舰"],
            "桌搭分享": ["桌面", "桌搭", "电竞房", "工作台", "布置", "理线", "RGB", "氛围灯"],
            "数码开箱": ["开箱", "评测", "体验", "首发", "入手", "真香", "翻车", "对比"],
            "配件推荐": ["耳机", "键盘", "鼠标", "充电", "数据线", "支架", "保护壳", "好物"],
        },
    },
    "艺术设计": {
        "keywords": ["设计", "平面设计", "UI", "UX", "品牌", "logo", "海报", "排版", "字体",
                     "插画", "原画", "板绘", "procreate", "PS", "AI教程", "C4D", "Blender",
                     "配色", "审美", "灵感", "创意", "作品集", "接单", "自由职业", "乙方",
                     "看展", "美术馆", "画廊", "艺术展", "装置", "当代艺术", "国画", "书法"],
        "sub_tracks": {
            "插画绘画": ["插画", "板绘", "procreate", "原画", "厚涂", "平涂", "头像", "约稿"],
            "设计教程": ["设计", "教程", "PS", "AI", "排版", "配色", "字体", "海报", "logo"],
            "看展分享": ["看展", "展览", "美术馆", "画廊", "打卡", "拍照", "艺术", "装置"],
            "作品集": ["作品集", "portfolio", "展示", "创作", "过程", "灵感", "接单"],
        },
    },
    "音乐舞蹈": {
        "keywords": ["音乐", "钢琴", "吉他", "尤克里里", "小提琴", "古筝", "琵琶", "二胡",
                     "架子鼓", "贝斯", "声乐", "唱歌", "KTV", "cover", "翻唱", "编曲",
                     "原创音乐", "作曲", "乐理", "识谱", "练琴", "指弹", "弹唱",
                     "舞蹈", "爵士舞", "街舞", "芭蕾", "古典舞", "韩舞", "编舞", "翻跳",
                     "舞蹈教室", "基本功", "软开", "拉伸", "体能", "舞者日常"],
        "sub_tracks": {
            "乐器教程": ["钢琴", "吉他", "尤克里里", "教程", "零基础", "指法", "乐谱", "弹唱"],
            "声乐唱歌": ["唱歌", "声乐", "cover", "翻唱", "高音", "气息", "练声", "KTV"],
            "舞蹈日常": ["舞蹈", "翻跳", "编舞", "基本功", "上课", "舞室", "软开", "排练"],
            "音乐分享": ["歌单", "推荐", "治愈", "宝藏", "单曲循环", "BGM", "小众", "好听"],
        },
    },
    "绿植园艺": {
        "keywords": ["植物", "绿植", "多肉", "盆栽", "水培", "花盆", "花架", "阳台花园",
                     "种花", "养花", "月季", "绣球", "玫瑰", "向日葵", "郁金香", "鲜切花",
                     "种菜", "阳台种菜", "番茄", "草莓", "辣椒", "香草", "芽苗菜",
                     "花店", "花艺", "插花", "花束", "花材", "养护", "浇水", "施肥"],
        "sub_tracks": {
            "室内绿植": ["绿植", "盆栽", "室内", "净化", "好看", "好养", "推荐", "新手"],
            "阳台花园": ["阳台", "花园", "月季", "绣球", "种花", "改造", "开花", "爆盆"],
            "阳台种菜": ["种菜", "阳台种菜", "番茄", "草莓", "收获", "有机", "水培", "芽苗菜"],
            "鲜花插花": ["鲜花", "插花", "花束", "花材", "花瓶", "养护", "搭配", "花店"],
        },
    },
    "咖啡茶饮": {
        "keywords": ["咖啡", "咖啡机", "意式", "手冲", "美式", "拿铁", "dirty", "冷萃",
                     "咖啡豆", "磨豆机", "拉花", "奶泡", "星巴克", "瑞幸", "独立咖啡馆",
                     "茶", "茶叶", "茶具", "泡茶", "功夫茶", "白茶", "绿茶", "普洱", "乌龙",
                     "围炉煮茶", "茶系", "奶茶", "饮品", "自制饮品", "特调", "早C晚A"],
        "sub_tracks": {
            "家庭咖啡": ["咖啡机", "意式", "手冲", "咖啡豆", "拉花", "磨豆", "家庭", "角落"],
            "咖啡探店": ["咖啡馆", "探店", "打卡", "独立", "精品", "推荐", "好喝", "拍照"],
            "茶生活": ["茶", "茶叶", "茶具", "泡茶", "功夫茶", "茶席", "紫砂", "建盏"],
            "自制饮品": ["自制", "饮品", "特调", "奶茶", "果汁", "气泡水", "冰饮", "配方"],
        },
    },
    "香氛香水": {
        "keywords": ["香水", "香氛", "香薰", "香薰蜡烛", "精油", "扩香", "无火香薰", "车载香薰",
                     "小众香水", "沙龙香", "商业香", "木质调", "花香调", "柑橘调", "东方调",
                     "留香", "试香", "分装", "香水瓶", "香评", "本命香", "斩男香", "通勤香",
                     "身体乳", "沐浴露", "护手霜", "香氛洗护", "香薰机", "线香", "塔香"],
        "sub_tracks": {
            "香水测评": ["香水", "测评", "试香", "香评", "种草", "踩雷", "推荐", "本命香"],
            "小众香氛": ["小众", "沙龙香", "niche", "冷门", "特别", "高级", "不撞香"],
            "居家香薰": ["香薰", "蜡烛", "无火", "扩香", "精油", "线香", "房间", "氛围"],
            "香氛洗护": ["身体乳", "沐浴露", "护手霜", "洗发", "香味", "留香", "斩男", "好闻"],
        },
    },
    "包袋奢侈品": {
        "keywords": ["包包", "包袋", "大牌", "奢侈品", "LV", "Chanel", "爱马仕", "Hermes",
                     "Gucci", "Dior", "Celine", "Loewe", "Prada", "Fendi", "BV",
                     "买包", "开箱", "翻包", "whats in my bag", "通勤包", "托特包",
                     "腋下包", "链条包", "双肩包", "帆布包", "小众包", "轻奢", "中古"],
        "sub_tracks": {
            "大牌开箱": ["开箱", "LV", "Chanel", "爱马仕", "Dior", "入手", "专柜", "涨价"],
            "翻包分享": ["翻包", "whats in my bag", "日常", "通勤", "必备", "收纳", "爱用"],
            "包袋推荐": ["推荐", "通勤包", "小众", "千元", "百元", "轻奢", "质感", "好看"],
            "中古vintage": ["中古", "vintage", "二手", "老花", "保值", "淘包", "成色", "鉴定"],
        },
    },
    "二次元动漫": {
        "keywords": ["二次元", "动漫", "番剧", "新番", "cosplay", "cos", "漫展", "CP展",
                     "手办", "模型", "周边", "痛包", "谷子", "吧唧", "JK", "汉服", "Lolita",
                     "三坑", "同人", "乙女", "声优", "漫画", "轻小说", "热血", "治愈番"],
        "sub_tracks": {
            "动漫推荐": ["动漫", "番剧", "推荐", "新番", "好看", "治愈", "热血", "补番"],
            "Cosplay": ["cosplay", "cos", "漫展", "出片", "假发", "道具", "化妆", "正片"],
            "手办周边": ["手办", "模型", "周边", "谷子", "吧唧", "痛包", "收藏", "展示"],
            "三坑穿搭": ["JK", "汉服", "Lolita", "三坑", "格裙", "宋制", "明制", "cla系"],
        },
    },
    "星座玄学": {
        "keywords": ["星座", "十二星座", "白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
                     "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座", "星座运势",
                     "MBTI", "INFP", "INFJ", "ENFP", "INTJ", "INTP", "ENTP", "ISTJ",
                     "ESTJ", "ESFJ", "ISFP", "ESFP", "ENTJ", "ISFJ", "ESTP", "ISTP",
                     "16型人格", "MBTI测试", "人格类型", "E人", "I人", "P人", "J人",
                     "塔罗", "占星", "星盘", "紫微", "命运", "水逆", "八字", "星座配对",
                     "玄学", "灵性", "冥想", "正念", "能量", "水晶", "脉轮", "吸引力法则", "显化"],
        "sub_tracks": {
            "星座分析": ["星座", "十二星座", "性格", "分析", "运势", "配对", "本周", "本月"],
            "MBTI人格": ["MBTI", "INFP", "INFJ", "ENFP", "INTJ", "人格", "类型", "测试"],
            "塔罗占卜": ["塔罗", "占卜", "牌阵", "解读", "感情", "事业", "建议", "大众占卜"],
            "身心灵": ["冥想", "正念", "能量", "灵性", "水晶", "疗愈", "吸引力法则", "显化"],
        },
    },
}

def classify_content_track(title, desc, tags):
    """
    基于标题、正文和标签，对内容进行赛道分类（大类 + 细分赛道）。

    使用 CONTENT_TRACKS 词库进行关键词匹配，返回最佳匹配结果。

    Args:
        title: str — 笔记标题
        desc: str — 笔记正文
        tags: list[str] — 标签列表

    Returns:
        dict — {
            "primary_track": str,       # 一级赛道（大类）
            "sub_track": str,           # 二级赛道（细分）
            "confidence": str,          # "高" / "中" / "低"
            "matched_keywords": [str],  # 命中的关键词
            "track_scores": {track: score},  # 各赛道得分
        }
    """
    text = (title or "") + " " + (desc or "") + " " + " ".join(tags or [])
    if not text.strip():
        return {
            "primary_track": "无法判断",
            "sub_track": "",
            "confidence": "低",
            "matched_keywords": [],
            "track_scores": {},
        }

    # 对每个大类赛道打分
    track_scores = {}
    track_matches = {}  # track → matched keywords

    for track, track_data in CONTENT_TRACKS.items():
        score = 0
        matched = []
        for kw in track_data["keywords"]:
            if kw in text:
                score += 1
                matched.append(kw)
        if score > 0:
            track_scores[track] = score
            track_matches[track] = matched

    if not track_scores:
        return {
            "primary_track": "综合/泛生活",
            "sub_track": "",
            "confidence": "低",
            "matched_keywords": [],
            "track_scores": {},
        }

    # 取最高分赛道
    best_track = max(track_scores, key=track_scores.get)
    best_score = track_scores[best_track]
    matched_keywords = track_matches.get(best_track, [])

    # 置信度
    if best_score >= 4:
        confidence = "高"
    elif best_score >= 2:
        confidence = "中"
    else:
        confidence = "低"

    # 细分赛道匹配
    sub_track = ""
    sub_tracks = CONTENT_TRACKS.get(best_track, {}).get("sub_tracks", {})
    sub_scores = {}
    for sub_name, sub_kws in sub_tracks.items():
        sub_score = sum(1 for kw in sub_kws if kw in text)
        if sub_score > 0:
            sub_scores[sub_name] = sub_score

    if sub_scores:
        sub_track = max(sub_scores, key=sub_scores.get)

    return {
        "primary_track": best_track,
        "sub_track": sub_track,
        "confidence": confidence,
        "matched_keywords": matched_keywords[:10],
        "track_scores": track_scores,
    }


# ----------------------------------------------------------
# 辅助分析函数（确定性分析，不需要 AI）
# ----------------------------------------------------------

def extract_title_patterns(titles):
    """从标题列表中提取常见模式"""
    patterns = {
        "数字型": r"\d+",
        "疑问型": r"[？?]|怎么|如何|为什么|什么",
        "感叹型": r"[！!]|绝了|太|真的|居然|竟然",
        "教程型": r"教程|手把手|保姆级|步骤|方法|攻略",
        "列表型": r"合集|盘点|推荐|必备|top|榜",
        "对比型": r"vs|对比|区别|差异|还是",
        "故事型": r"我|亲身|经历|踩坑|分享|心得",
        "悬念型": r"\.\.\.|…|竟然|没想到|万万|千万",
    }
    results = {}
    for pattern_name, regex in patterns.items():
        count = sum(1 for t in titles if re.search(regex, t, re.IGNORECASE))
        if count > 0:
            pct = round(count / len(titles) * 100, 1)
            examples = [t for t in titles if re.search(regex, t, re.IGNORECASE)][:3]
            results[pattern_name] = {"count": count, "pct": pct, "examples": examples}
    return results


def extract_emoji_patterns(descs):
    """从正文中提取 emoji 使用模式"""
    emoji_pattern = re.compile(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        r"\U00002702-\U000027B0\U0001F900-\U0001F9FF"
        r"\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
        r"\U00002600-\U000026FF]+"
    )
    emoji_counter = Counter()
    notes_with_emoji = 0
    for desc in descs:
        if not desc:
            continue
        emojis = emoji_pattern.findall(desc)
        if emojis:
            notes_with_emoji += 1
            for e in emojis:
                for char in e:
                    emoji_counter[char] += 1
    return {
        "notes_with_emoji": notes_with_emoji,
        "total_notes": len(descs),
        "emoji_usage_pct": round(notes_with_emoji / len(descs) * 100, 1) if descs else 0,
        "top_emojis": emoji_counter.most_common(10),
    }


def extract_cta_patterns(descs):
    """从正文中提取 CTA（行动号召）模式"""
    cta_patterns = {
        "关注引导": [r"关注", r"点个关注", r"记得关注"],
        "收藏引导": [r"收藏", r"先收藏", r"码住", r"mark"],
        "点赞引导": [r"点赞", r"双击", r"给个赞"],
        "评论引导": [r"评论", r"留言", r"告诉我", r"你们觉得", r"欢迎讨论"],
        "转发引导": [r"转发", r"分享给"],
        "私信引导": [r"私信", r"私我", r"后台回复", r"滴滴"],
    }
    results = {}
    for cta_type, regexes in cta_patterns.items():
        combined = "|".join(regexes)
        count = sum(1 for d in descs if d and re.search(combined, d))
        if count > 0:
            pct = round(count / len(descs) * 100, 1) if descs else 0
            results[cta_type] = {"count": count, "pct": pct}
    return results


def analyze_content_structure(descs):
    """分析正文结构模式"""
    results = {
        "avg_length": 0,
        "short_count": 0,  # <200字
        "medium_count": 0,  # 200-500字
        "long_count": 0,    # >500字
        "has_list_count": 0,  # 包含列表格式
        "has_number_heading": 0,  # 包含数字小标题
    }
    lengths = []
    for desc in descs:
        if not desc:
            continue
        length = len(desc)
        lengths.append(length)
        if length < 200:
            results["short_count"] += 1
        elif length < 500:
            results["medium_count"] += 1
        else:
            results["long_count"] += 1

        if re.search(r"^[\s]*[\-•●]\s", desc, re.MULTILINE):
            results["has_list_count"] += 1
        if re.search(r"[①②③④⑤⑥⑦⑧⑨⑩]|[1-9][.、]", desc):
            results["has_number_heading"] += 1

    results["avg_length"] = round(sum(lengths) / len(lengths)) if lengths else 0
    return results


def detect_posting_frequency(notes_with_time):
    """分析发布频率模式"""
    timestamps = sorted([n["time"] for n in notes_with_time if n.get("time", 0) > 0])
    if len(timestamps) < 2:
        return {"pattern": "数据不足", "avg_days_between": 0}

    # 计算相邻发布间隔
    from datetime import datetime as dt
    intervals = []
    for i in range(1, len(timestamps)):
        try:
            diff = (timestamps[i] - timestamps[i - 1])
            if isinstance(diff, (int, float)):
                # 假设是毫秒时间戳
                days = diff / (1000 * 86400)
            else:
                days = diff.total_seconds() / 86400
            if 0 < days < 365:  # 排除异常值
                intervals.append(days)
        except (TypeError, ValueError):
            continue

    if not intervals:
        return {"pattern": "无法计算", "avg_days_between": 0}

    avg_days = round(sum(intervals) / len(intervals), 1)
    if avg_days <= 1:
        pattern = "日更"
    elif avg_days <= 3:
        pattern = "高频（2-3天/条）"
    elif avg_days <= 7:
        pattern = "周更"
    elif avg_days <= 14:
        pattern = "双周更"
    else:
        pattern = f"低频（约{int(avg_days)}天/条）"

    return {"pattern": pattern, "avg_days_between": avg_days, "total_intervals": len(intervals)}


def extract_posting_heatmap(notes):
    """
    从笔记时间戳生成发布时间热力图数据。

    Args:
        notes: list[dict] — 分析后的笔记列表（来自 analysis.json），
               每条需包含 time (13-digit ms) 和 likes

    Returns:
        dict — {
            "hour_day_matrix": [[int * 7] * 7],   # 7行(time_slot) × 7列(day_of_week)
            "engagement_matrix": [[float * 7] * 7], # 7×7 平均赞数
            "day_names_cn": ["周一",...,"周日"],
            "time_slots": ["00-06时","06-08时","08-12时","12-14时","14-18时","18-21时","21-24时"],
            "total_notes_with_time": int,
            "optimal_windows": [{slot, day, avg_likes, count}],  # top 3
            "best_day": str,
            "best_hour_block": str,
            "best_day_avg_likes": float,
            "best_hour_avg_likes": float,
        }
    """
    from utils.common import ms_to_datetime

    # 初始化矩阵
    time_slots = ["00-06时", "06-08时", "08-12时", "12-14时", "14-18时", "18-21时", "21-24时"]
    day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    slot_bounds = [(0, 6), (6, 8), (8, 12), (12, 14), (14, 18), (18, 21), (21, 24)]

    hour_day_matrix = [[0] * 7 for _ in range(7)]
    engagement_accum = [[0.0] * 7 for _ in range(7)]

    valid_notes = 0

    for note in notes:
        ts = note.get("time", 0)
        dt = ms_to_datetime(ts)
        if dt is None:
            continue

        hour = dt.hour
        dow = dt.weekday()  # 0=Mon, 6=Sun
        likes = note.get("likes", 0)

        # 找到对应时段
        slot_idx = -1
        for idx, (lo, hi) in enumerate(slot_bounds):
            if lo <= hour < hi:
                slot_idx = idx
                break
        if slot_idx == -1:
            continue

        hour_day_matrix[slot_idx][dow] += 1
        engagement_accum[slot_idx][dow] += likes
        valid_notes += 1

    # 计算平均赞数矩阵
    engagement_matrix = [[0.0] * 7 for _ in range(7)]
    for s in range(7):
        for d in range(7):
            count = hour_day_matrix[s][d]
            if count > 0:
                engagement_matrix[s][d] = round(engagement_accum[s][d] / count, 1)

    # 找最佳发布窗口（按均赞，最少2条）
    all_windows = []
    for s in range(7):
        for d in range(7):
            count = hour_day_matrix[s][d]
            if count >= 2:
                all_windows.append({
                    "slot": time_slots[s],
                    "day": day_names[d],
                    "avg_likes": engagement_matrix[s][d],
                    "count": count,
                })

    all_windows.sort(key=lambda x: x["avg_likes"], reverse=True)
    optimal_windows = all_windows[:3]

    # 最佳天和最佳时段（按发布频次）
    day_totals = [sum(hour_day_matrix[s][d] for s in range(7)) for d in range(7)]
    slot_totals = [sum(hour_day_matrix[s]) for s in range(7)]

    best_day_idx = day_totals.index(max(day_totals)) if any(day_totals) else 0
    best_slot_idx = slot_totals.index(max(slot_totals)) if any(slot_totals) else 0

    # 最佳天和最佳时段的均赞
    best_day_likes = 0
    best_day_count = 0
    for s in range(7):
        if hour_day_matrix[s][best_day_idx] > 0:
            best_day_likes += engagement_accum[s][best_day_idx]
            best_day_count += hour_day_matrix[s][best_day_idx]
    best_day_avg_likes = round(best_day_likes / best_day_count, 1) if best_day_count else 0

    best_hour_likes = 0
    best_hour_count = 0
    for d in range(7):
        if hour_day_matrix[best_slot_idx][d] > 0:
            best_hour_likes += engagement_accum[best_slot_idx][d]
            best_hour_count += hour_day_matrix[best_slot_idx][d]
    best_hour_avg_likes = round(best_hour_likes / best_hour_count, 1) if best_hour_count else 0

    return {
        "hour_day_matrix": hour_day_matrix,
        "engagement_matrix": engagement_matrix,
        "day_names_cn": day_names,
        "time_slots": time_slots,
        "total_notes_with_time": valid_notes,
        "optimal_windows": optimal_windows,
        "best_day": day_names[best_day_idx] if any(day_totals) else "",
        "best_hour_block": time_slots[best_slot_idx] if any(slot_totals) else "",
        "best_day_avg_likes": best_day_avg_likes,
        "best_hour_avg_likes": best_hour_avg_likes,
    }


def extract_image_patterns(notes_details):
    """
    从 notes_details.json 的 imageList 数据中提取图片序列模式。

    利用 MCP 返回的真实图片元数据（宽/高/数量），将图文笔记的视觉分析
    从「文本推断」提升为「数据结论」。

    Args:
        notes_details: list[dict] — 原始笔记详情列表（来自 notes_details.json）
                       每条需包含 data.note.imageList[].width/height

    Returns:
        dict — {
            "total_notes_with_images": int,
            "image_posts_count": int,          # 图文笔记数
            "video_posts_count": int,           # 视频笔记数
            "image_posts_avg_images": float,    # 图文笔记平均图片数
            "image_posts_max_images": int,      # 图文笔记最多图片数
            "image_posts_min_images": int,      # 图文笔记最少图片数
            "layout_type": str,                 # 主导版面类型
            "aspect_ratios": {                  # 宽高比分布
                "portrait_pct": float,
                "square_pct": float,
                "landscape_pct": float,
            },
            "sequence_pattern": str,            # 图片序列模式
            "sequence_description": str,
            "per_note_image_counts": [int],     # 每条图文笔记的图片数
            "consistent_layout": bool,          # 是否固定版面
            "cover_aspect_analysis": str,        # 封面比例分析
        }
    """
    if not notes_details:
        return {
            "total_notes_with_images": 0,
            "image_posts_count": 0,
            "video_posts_count": 0,
            "image_posts_avg_images": 0,
            "image_posts_max_images": 0,
            "image_posts_min_images": 0,
            "layout_type": "数据不可用",
            "aspect_ratios": {"portrait_pct": 0, "square_pct": 0, "landscape_pct": 0},
            "sequence_pattern": "数据不可用",
            "sequence_description": "",
            "per_note_image_counts": [],
            "consistent_layout": False,
            "cover_aspect_analysis": "",
        }

    image_counts = []      # 每条图文笔记的图片数
    aspect_ratios = []     # 每条笔记首图的宽高比 (h/w)
    video_count = 0
    image_count = 0

    for item in notes_details:
        if "_error" in item:
            continue
        note_data = item.get("data", {}).get("note", item)
        note_type = note_data.get("type", "normal")
        img_list = note_data.get("imageList", [])

        if not img_list:
            continue

        if note_type == "video":
            video_count += 1
            # 视频仅有封面，不计入图片序列分析
            continue

        # 图文笔记
        image_count += 1
        count = len(img_list)
        image_counts.append(count)

        # 首图宽高比
        first = img_list[0]
        w = first.get("width", 0)
        h = first.get("height", 0)
        if w > 0 and h > 0:
            aspect_ratios.append(h / w)

    total_with_images = image_count + video_count

    if image_count == 0:
        return {
            "total_notes_with_images": total_with_images,
            "image_posts_count": 0,
            "video_posts_count": video_count,
            "image_posts_avg_images": 0,
            "image_posts_max_images": 0,
            "image_posts_min_images": 0,
            "layout_type": "无图文笔记（全视频账号）",
            "aspect_ratios": {"portrait_pct": 0, "square_pct": 0, "landscape_pct": 0},
            "sequence_pattern": "无图文笔记",
            "sequence_description": "该博主全部为视频笔记，无图片序列数据。",
            "per_note_image_counts": [],
            "consistent_layout": False,
            "cover_aspect_analysis": "",
        }

    # 图片数量统计
    avg_images = round(sum(image_counts) / len(image_counts), 1)
    max_images = max(image_counts)
    min_images = min(image_counts)

    # 图片序列模式判定
    if avg_images >= 9:
        seq_pattern = "合集/图鉴型"
        seq_desc = f"平均{avg_images}张/条，博主偏好大量图片堆叠，典型场景：封面→单品×N→总结，适合种草/盘点/图鉴类内容"
    elif avg_images >= 5:
        seq_pattern = "教程步骤型"
        seq_desc = f"平均{avg_images}张/条，每张图承载一个信息单元，典型场景：封面→步骤1→步骤2→...→结果→CTA"
    elif avg_images >= 2.5:
        seq_pattern = "三段式结构型"
        seq_desc = f"平均{avg_images}张/条，典型场景：封面吸引→信息主体（{avg_images-2:.0f}张）→收尾/CTA"
    else:
        seq_pattern = "单图/双图冲击型"
        seq_desc = f"平均{avg_images}张/条，靠少量高质量图片承载全部信息，典型场景：穿搭单pose、金句卡片、Before/After对比"

    # 比例分类
    portrait = sum(1 for r in aspect_ratios if r > 1.2)
    square = sum(1 for r in aspect_ratios if 0.9 <= r <= 1.2)
    landscape = sum(1 for r in aspect_ratios if r < 0.9)
    n_ratios = len(aspect_ratios) or 1

    portrait_pct = round(portrait / n_ratios * 100, 1)
    square_pct = round(square / n_ratios * 100, 1)
    landscape_pct = round(landscape / n_ratios * 100, 1)

    # 主导版面类型
    max_pct = max(portrait_pct, square_pct, landscape_pct)
    if max_pct == portrait_pct:
        layout_type = f"竖版主导（{portrait_pct}%）"
        cover_analysis = "竖版长图为主，适合人像/穿搭/OOTD/全身。在信息流中占据更大屏幕空间，视觉冲击力强。"
    elif max_pct == square_pct:
        layout_type = f"方图主导（{square_pct}%）"
        cover_analysis = "方图/近方图为主，适合产品图/截图/教程卡片/标题封面。信息密度可控，排版规整。"
    else:
        layout_type = f"横版主导（{landscape_pct}%）"
        cover_analysis = "横版图为主，适合场景/风景/桌面/全景。在小红书竖版信息流中占比较小，需靠内容本身吸引点击。"

    # 版面一致性
    consistent = max_pct >= 80
    if consistent:
        layout_type += " — 固定版面风格，视觉辨识度高"

    return {
        "total_notes_with_images": total_with_images,
        "image_posts_count": image_count,
        "video_posts_count": video_count,
        "image_posts_avg_images": avg_images,
        "image_posts_max_images": max_images,
        "image_posts_min_images": min_images,
        "layout_type": layout_type,
        "aspect_ratios": {
            "portrait_pct": portrait_pct,
            "square_pct": square_pct,
            "landscape_pct": landscape_pct,
        },
        "sequence_pattern": seq_pattern,
        "sequence_description": seq_desc,
        "per_note_image_counts": image_counts,
        "consistent_layout": consistent,
        "cover_aspect_analysis": cover_analysis,
    }


def find_growth_pattern(notes):
    """分析内容发展趋势（早期 vs 近期的主题变化）"""
    if len(notes) < 6:
        return None

    # 按时间排序（已按赞排序的数据需要重新按时间排）
    time_sorted = sorted([n for n in notes if n.get("time", 0) > 0], key=lambda x: x["time"])
    if len(time_sorted) < 6:
        return None

    # 分成前半和后半
    mid = len(time_sorted) // 2
    early = time_sorted[:mid]
    recent = time_sorted[mid:]

    early_cats = Counter(n.get("category", "其他") for n in early)
    recent_cats = Counter(n.get("category", "其他") for n in recent)

    # 找到增长和衰退的类别
    all_cats = set(list(early_cats.keys()) + list(recent_cats.keys()))
    changes = {}
    for cat in all_cats:
        e_pct = round(early_cats.get(cat, 0) / len(early) * 100, 1) if early else 0
        r_pct = round(recent_cats.get(cat, 0) / len(recent) * 100, 1) if recent else 0
        changes[cat] = {"early_pct": e_pct, "recent_pct": r_pct, "delta": round(r_pct - e_pct, 1)}

    return {
        "early_count": len(early),
        "recent_count": len(recent),
        "category_shifts": changes,
    }


def extract_comment_sentiment(full_notes):
    """
    对全量笔记的评论进行情感分析（关键词匹配法）。

    Args:
        full_notes: list[dict] — 原始笔记详情列表（来自 notes_details.json）
                    每条需包含 data.comments.list[].content

    Returns:
        dict — {
            "overall_score": float,          # 整体情感得分（-1到1，正=偏正向）
            "total_comments_analyzed": int,
            "per_note": [{note_title, positive_pct, neutral_pct, negative_pct,
                          comment_count, sentiment_label, top_keywords}],
            "positive_examples": [str],       # 代表性正向评论（3条）
            "negative_examples": [str],       # 代表性负向评论（3条）
        }
    """
    def _score_comment(text):
        """对单条评论打分。返回 (score, matched_keywords)"""
        if not text or len(text.strip()) < 3:
            return 0, []

        score = 0
        matched = []

        # 分词：按常见分隔切分（中文不需要精确分词，用滑窗匹配）
        for word in SENTIMENT_LEXICON["strong_positive"]:
            if word in text:
                score += 2
                matched.append(f"+2:{word}")
        for word in SENTIMENT_LEXICON["positive"]:
            if word in text:
                score += 1
                matched.append(f"+1:{word}")
        for word in SENTIMENT_LEXICON["strong_negative"]:
            if word in text:
                score -= 2
                matched.append(f"-2:{word}")
        for word in SENTIMENT_LEXICON["negative"]:
            if word in text:
                score -= 1
                matched.append(f"-1:{word}")

        # 否定词反转：检查关键词前3字是否有否定词
        for neg in SENTIMENT_LEXICON["negation_words"]:
            for kw in SENTIMENT_LEXICON["positive"] + SENTIMENT_LEXICON["strong_positive"]:
                idx = text.find(kw)
                if idx >= 0:
                    pre = text[max(0, idx-3):idx]
                    if neg in pre:
                        # 反转：把正向变负向
                        old = 2 if kw in SENTIMENT_LEXICON["strong_positive"] else 1
                        score -= old * 2  # 反转且加倍
                        matched.append(f"↺:{neg}+{kw}")
        for neg in SENTIMENT_LEXICON["negation_words"]:
            for kw in SENTIMENT_LEXICON["negative"] + SENTIMENT_LEXICON["strong_negative"]:
                idx = text.find(kw)
                if idx >= 0:
                    pre = text[max(0, idx-3):idx]
                    if neg in pre:
                        old = 2 if kw in SENTIMENT_LEXICON["strong_negative"] else 1
                        score += old * 2
                        matched.append(f"↺:{neg}+{kw}")

        # 加强词放大：检查关键词前2字是否有加强词
        for intens in SENTIMENT_LEXICON["intensifiers"]:
            for kw in (SENTIMENT_LEXICON["positive"] + SENTIMENT_LEXICON["strong_positive"]
                       + SENTIMENT_LEXICON["negative"] + SENTIMENT_LEXICON["strong_negative"]):
                idx = text.find(kw)
                if idx >= 0:
                    pre = text[max(0, idx-2):idx]
                    if intens in pre:
                        score = score * 1.5
                        matched.append(f"↑:{intens}+{kw}")
                        break

        return score, matched

    if not full_notes:
        return {
            "overall_score": None,
            "total_comments_analyzed": 0,
            "per_note": [],
            "positive_examples": [],
            "negative_examples": [],
        }

    all_scores = []
    per_note = []
    positive_examples = []
    negative_examples = []

    for note_data in full_notes:
        note = note_data.get("data", {}).get("note", note_data)
        note_title = note.get("title", note.get("displayTitle", "?"))[:40]
        comments = note_data.get("data", {}).get("comments", note_data.get("comments", {}))
        comment_list = comments.get("list", []) if isinstance(comments, dict) else []

        if not comment_list:
            per_note.append({
                "note_title": note_title,
                "positive_pct": 0,
                "neutral_pct": 0,
                "negative_pct": 0,
                "comment_count": 0,
                "sentiment_label": "无评论",
            })
            continue

        pos_count = 0
        neg_count = 0
        neu_count = 0

        for c in comment_list[:100]:  # 单条笔记最多分析100条评论
            content = c.get("content", "")
            score, matched = _score_comment(content)
            all_scores.append(score)

            if score > 0.5:
                pos_count += 1
                if len(positive_examples) < 3 and score >= 2:
                    positive_examples.append(content[:80])
            elif score < -0.5:
                neg_count += 1
                if len(negative_examples) < 3 and score <= -2:
                    negative_examples.append(content[:80])
            else:
                neu_count += 1

        total = pos_count + neg_count + neu_count
        per_note.append({
            "note_title": note_title,
            "positive_pct": round(pos_count / total * 100, 1) if total else 0,
            "neutral_pct": round(neu_count / total * 100, 1) if total else 0,
            "negative_pct": round(neg_count / total * 100, 1) if total else 0,
            "comment_count": total,
            "sentiment_label": (
                "正向为主" if pos_count > neg_count * 2 else
                "负向为主" if neg_count > pos_count * 2 else
                "中性/混合"
            ),
        })

    # 整体得分
    if all_scores:
        avg = sum(all_scores) / len(all_scores)
        # 归一化到 [-1, 1]，假设原始分数范围大致 [-4, 4]
        overall_score = round(max(-1.0, min(1.0, avg / 3.0)), 2)
    else:
        overall_score = 0

    return {
        "overall_score": overall_score,
        "total_comments_analyzed": len(all_scores),
        "per_note": per_note,
        "positive_examples": positive_examples,
        "negative_examples": negative_examples,
    }


# ----------------------------------------------------------
# 确定性内容填充（替换骨架中的占位符）
# ----------------------------------------------------------

def gen_enhanced_deep_analysis(nickname, stats, top10, category_stats, tag_freq,
                                title_patterns, comparison=None, notes=None, sentiment_info=None, image_info=None):
    """增强版博主深度拆解 — 11章完整结构，对齐产出物质量标杆"""
    lines = [
        f"# {nickname} — 博主深度拆解",
        f"\n> 数据采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]

    # === 一、账号概览 ===
    lines.append(f"\n## 一、账号概览")
    lines.append(f"\n### 基础数据")
    lines.append(f"| 指标 | 数据 |")
    lines.append(f"|------|------|")
    lines.append(f"| 笔记总数 | {stats['total']}条 |")
    lines.append(f"| 视频/图文 | {stats['video_count']}视频 / {stats['normal_count']}图文 |")

    # 图片序列信息（如有）
    img_count = 0
    if image_info and image_info.get("image_posts_count", 0) > 0:
        img_count = image_info["image_posts_count"]
        lines.append(f"| 图文平均图片数 | {image_info['image_posts_avg_images']}张/条（{image_info['sequence_pattern']}） |")
        lines.append(f"| 版面风格 | {image_info['layout_type']} |")

    lines.append(f"| 总赞 | {stats['total_likes']:,} |")
    lines.append(f"| 总收藏 | {stats['total_collects']:,} |")
    lines.append(f"| 总评论 | {stats['total_comments']:,} |")

    lines.append(f"\n### 关键指标")
    avg_likes = stats.get("avg_likes", 0)
    hit_threshold = avg_likes * 3 if avg_likes > 0 else 1
    hit_count = sum(1 for n in (notes or []) if n.get("likes", 0) >= hit_threshold)
    hit_rate = round(hit_count / max(stats["total"], 1) * 100, 1)
    super_threshold = avg_likes * 10 if avg_likes > 0 else 1
    super_count = sum(1 for n in (notes or []) if n.get("likes", 0) >= super_threshold)
    super_rate = round(super_count / max(stats["total"], 1) * 100, 1)
    total_likes = stats.get("total_likes", 1) or 1
    sl_ratio = round(stats.get("total_collects", 0) / total_likes, 2)

    lines.append(f"| 指标 | 数值 | 说明 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| 篇均赞 | {stats['avg_likes']:,} | — |")
    lines.append(f"| 篇均收藏 | {stats['avg_collects']:,} | — |")
    lines.append(f"| 篇均评论 | {stats['avg_comments']:,} | — |")
    lines.append(f"| 爆款率（>3x均赞） | {hit_rate}% | {hit_count}/{stats['total']}条 |")
    lines.append(f"| 超级爆款率（>10x均赞） | {super_rate}% | {super_count}/{stats['total']}条 |")
    lines.append(f"| 整体藏赞比 | {sl_ratio} | {'>0.6实用工具型' if sl_ratio>0.6 else ('0.3-0.6实用驱动' if sl_ratio>0.33 else ('0.2-0.3均衡型' if sl_ratio>0.2 else '<0.2情绪共鸣型'))} |")

    # 形式偏好
    if stats['video_count'] > 0 and stats['normal_count'] > 0 and notes:
        v_notes = [n for n in notes if n.get("type") == "video"]
        n_notes = [n for n in notes if n.get("type") != "video"]
        v_avg = sum(n["likes"] for n in v_notes) // len(v_notes) if v_notes else 0
        n_avg = sum(n["likes"] for n in n_notes) // len(n_notes) if n_notes else 0
        better = "视频" if v_avg > n_avg else "图文"
        ratio = round(v_avg/n_avg, 1) if n_avg and v_avg > n_avg else round(n_avg/v_avg, 1) if v_avg and n_avg > v_avg else 1
        lines.append(f"\n**形式偏好**：{better}均赞更高（{ratio}倍），内容重心应向 {better} 倾斜。")

    # === 二、博主人设拆解 ===
    lines.append(f"\n## 二、博主人设拆解 ★★★")
    lines.append(f"\n> *（AI 执行时填充）*")
    lines.append(f"\n### 人设三板斧")
    lines.append(f"- 人设支柱1：[AI 填充：基于内容风格的第一个核心人设标签]")
    lines.append(f"- 人设支柱2：[AI 填充：基于内容风格的第二个核心人设标签]")
    lines.append(f"- 人设支柱3：[AI 填充：基于内容风格的第三个核心人设标签]")
    lines.append(f"\n### 粉丝跟TA的本质原因")
    lines.append(f"- [AI 填充：学技能？获认同？找归属？情绪价值？]")
    lines.append(f"\n### 人设可持续性判断")
    lines.append(f"- [AI 填充：这个人设能否长期维持？依赖什么条件？]")

    # === 三、内容领域分布 ===
    lines.append(f"\n## 三、内容领域分布")
    lines.append(f"\n| 领域 | 数量 | 占比 | 均赞 | 代表作 |")
    lines.append(f"|------|------|------|------|--------|")
    for cat, cs in category_stats.items():
        lines.append(f"| {cat} | {cs['count']} | {cs['pct']}% | {cs['avg_likes']:,} | {cs['top_note'][:25]} |")
    if category_stats:
        sorted_cats = sorted(category_stats.items(), key=lambda x: x[1]["avg_likes"], reverse=True)
        best_cat = sorted_cats[0]
        most_cat = max(category_stats.items(), key=lambda x: x[1]["count"])
        lines.append(f"\n**核心发现**：")
        lines.append(f"- 产量最高：「{most_cat[0]}」{most_cat[1]['count']}条（{most_cat[1]['pct']}%）")
        lines.append(f"- 均赞最高：「{best_cat[0]}」均赞{best_cat[1]['avg_likes']:,}")
        if best_cat[0] != most_cat[0]:
            lines.append(f"- ⚡ **产量最高 ≠ 效果最好**。「{best_cat[0]}」受众反馈更强，增加该方向产量可能提升整体数据。")

    # === 四、高赞排行 TOP10 ===
    lines.append(f"\n## 四、高赞内容排行 TOP10")
    lines.append(f"\n| # | 标题 | 类型 | 赞 | 藏 | 评 |")
    lines.append(f"|---|------|------|-----|-----|-----|")
    for i, n in enumerate(top10[:10]):
        lines.append(f"| {i+1} | {n['title'][:30]} | {n['type']} | {n['likes_raw']} | {n['collects_raw']} | {n['comments_raw']} |")

    # === 五、TOP10 爆款逐条拆解 ★★★ ===
    lines.append(f"\n## 五、TOP10 爆款逐条拆解 ★★★")
    for i, n in enumerate(top10[:10]):
        is_top5 = i < 5
        lines.append(f"\n### {'🔥 ' if is_top5 else ''}{i+1}. {n['title']}")
        lines.append(f"- **类型**: {n['type']} | **赞**: {n['likes_raw']} | **藏**: {n['collects_raw']} | **评**: {n['comments_raw']}")
        if n.get("tags"):
            lines.append(f"- **标签**: {', '.join('#'+t for t in n['tags'][:5])}")

        # 标题策略
        title = n.get("title", "")
        traits = []
        if re.search(r"\d+", title): traits.append("数字吸引")
        if re.search(r"[？?]|怎么|如何", title): traits.append("疑问引发好奇")
        if re.search(r"[！!]|绝了|太|真的", title): traits.append("情绪化表达")
        if re.search(r"教程|手把手|保姆级", title): traits.append("实用价值承诺")
        if traits: lines.append(f"- **标题策略**: {' + '.join(traits)}")

        lines.append(f"- **内容摘要**: {(n.get('desc', '') or '')[:150]}")

        if is_top5:
            # TOP5 深度拆解
            lines.append(f"\n**爆款原因**：")
            lines.append(f"- [AI 填充：因果分析——为什么这条内容数据好？]")
            lines.append(f"- [AI 填充：时间窗口/身份共鸣/情绪表达/实用价值 等具体原因]")
            lines.append(f"\n**评论洞察**：")
            if n.get("comment_list"):
                for c in n["comment_list"][:3]:
                    prefix = "[作者] " if c.get("is_author") else ""
                    lines.append(f"  - {prefix}{c['user']}: {c['content'][:60]}")
                lines.append(f"\n  → [AI 填充：这些评论说明了什么？]")
            lines.append(f"\n**对你的启示**：")
            lines.append(f"- [AI 填充：这条爆款的方法如何转化为你的可执行动作？]")
        else:
            # TOP6-10 快速拆解
            lines.append(f"\n**核心公式**: [AI 填充：一句话总结] | **启示**: [AI 填充：一句话建议]")

    # === 六、内容模式分类 ===
    lines.append(f"\n## 六、内容模式分类 ★★★")
    # 策略类型判断
    top_cat = max(category_stats.items(), key=lambda x: x[1]["count"])[0] if category_stats else ""
    top_cat_pct = category_stats[top_cat]["pct"] if top_cat in category_stats else 0
    if top_cat_pct > 70:
        strategy = "极度垂直型"
        strategy_desc = f"超过70%内容集中在「{top_cat}」领域。利：该领域第一认知，粉丝精准；弊：受众天花板低，需注意内容疲劳。"
    elif len(category_stats) >= 3:
        strategy = "多元交叉型"
        strategy_desc = f"覆盖{len(category_stats)}个领域。利：交叉创造爆款，受众面广；弊：定位可能模糊。"
    else:
        strategy = "垂直为主"
        strategy_desc = f"以「{top_cat}」为主，少量拓展。属于健康的垂直策略。"
    lines.append(f"\n### 策略类型: {strategy}")
    lines.append(f"{strategy_desc}")

    # 内容形式分类
    lines.append(f"\n### 按内容形式分类")
    lines.append(f"\n| 模式 | 占比 | 数据表现 | 特征 | 典型案例 |")
    lines.append(f"|------|------|---------|------|---------|")
    for cat, cs in list(category_stats.items())[:6]:
        lines.append(f"| {cat} | {cs['pct']}% | 均赞{cs['avg_likes']:,} | [AI填充] | {cs.get('top_note','')[:20]} |")
    lines.append(f"\n> *（AI 执行时：每种模式 ~8行深度分析，含典型案例+3个特征+数据证明）*")

    # === 七、评论深度洞察 ===
    lines.append(f"\n## 七、评论深度洞察")

    if sentiment_info and sentiment_info.get("total_comments_analyzed", 0) > 0:
        overall = sentiment_info["overall_score"] or 0
        mood = "😊 整体偏正向" if overall > 0.3 else ("😟 整体偏负向" if overall < -0.3 else "😐 中性/混合")
        lines.append(f"\n**整体情感**: {overall:+.1f}/1.0 {mood}（{sentiment_info['total_comments_analyzed']}条评论）")

        # 情感分布
        lines.append(f"\n| 倾向 | 占比 | 说明 |")
        lines.append(f"|------|------|------|")
        total_pos = sum(n.get("positive_pct", 0) * n.get("comment_count", 0) for n in sentiment_info["per_note"])
        total_neg = sum(n.get("negative_pct", 0) * n.get("comment_count", 0) for n in sentiment_info["per_note"])
        total_neu = sum(n.get("neutral_pct", 0) * n.get("comment_count", 0) for n in sentiment_info["per_note"])
        total_all = total_pos + total_neg + total_neu or 1
        lines.append(f"| 正向 😊 | {round(total_pos/total_all*100,1)}% | 认可、感谢、好评 |")
        lines.append(f"| 中性 😐 | {round(total_neu/total_all*100,1)}% | 提问、中性讨论 |")
        lines.append(f"| 负向 😟 | {round(total_neg/total_all*100,1)}% | 批评、质疑 |")

        if sentiment_info.get("positive_examples"):
            lines.append(f"\n**正向评论样例**:")
            for ex in sentiment_info["positive_examples"][:3]:
                lines.append(f'- 「{ex}」')
        if sentiment_info.get("negative_examples"):
            lines.append(f"\n**需关注的负向评论**:")
            for ex in sentiment_info["negative_examples"][:3]:
                lines.append(f'- 「{ex}」')

    lines.append(f"\n### 用户最关心的5类问题")
    lines.append(f"\n| 问题类型 | 频次 | 典型评论 | 内容机会 |")
    lines.append(f"|----------|------|---------|---------|")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"\n> *（AI 执行时：基于评论区高频提问聚类，每类附内容机会）*")

    lines.append(f"\n### 评论区运营策略")
    lines.append(f"- [AI 填充：博主在评论区的回复风格和互动策略]")
    lines.append(f"- [AI 填充：是否有神回复/二次造梗/引导互动 等亮点]")

    # === 八、选题逻辑拆解 ===
    lines.append(f"\n## 八、选题逻辑拆解")
    lines.append(f"\n### 选题矩阵")
    lines.append(f"```")
    lines.append(f"高流量 ┌─────────────┬─────────────┐")
    lines.append(f"       │ [AI填充]    │ [AI填充]    │")
    lines.append(f"       │             │             │")
    lines.append(f"低流量 ├─────────────┼─────────────┤")
    lines.append(f"       │ [AI填充]    │ [AI填充]    │")
    lines.append(f"       └─────────────┴─────────────┘")
    lines.append(f"       低互动         高互动")
    lines.append(f"```")
    lines.append(f"\n### 选题节奏")
    lines.append(f"- [AI 填充：5个时间节点 × 对应内容类型的节奏建议]")
    lines.append(f"\n### 标签策略")
    lines.append(f"| 标签层级 | 作用 | 典型标签 |")
    lines.append(f"|----------|------|---------|")
    lines.append(f"| 固定标签 | 账号定位 | {', '.join(t for t,c in tag_freq[:3])} |")
    lines.append(f"| 流量标签 | 蹭热度 | [AI填充] |")
    lines.append(f"| 身份标签 | 人群识别 | [AI填充] |")

    # === 九、核心竞争优势 ===
    lines.append(f"\n## 九、核心竞争优势分析")
    lines.append(f"\n1. **[AI 填充：优势名称]** — [为什么是优势 + 数据支撑]")
    lines.append(f"2. **[AI 填充：优势名称]** — [为什么是优势 + 数据支撑]")
    lines.append(f"3. **[AI 填充：优势名称]** — [为什么是优势 + 数据支撑]")
    lines.append(f"4. **[AI 填充：优势名称]** — [为什么是优势 + 数据支撑]")
    lines.append(f"5. **[AI 填充：优势名称]** — [为什么是优势 + 数据支撑]")
    lines.append(f"6. **[AI 填充：优势名称]** — [为什么是优势 + 数据支撑]")

    # === 十、短板 ===
    lines.append(f"\n## 十、短板与改进方向")
    lines.append(f"\n| 短板 | 表现 | 评论区证据 | 改进方向 |")
    lines.append(f"|------|------|-----------|---------|")
    lines.append(f"| [AI填充] | [AI填充] | [AI填充] | [AI填充] |")
    lines.append(f"| [AI填充] | [AI填充] | [AI填充] | [AI填充] |")
    lines.append(f"| [AI填充] | [AI填充] | [AI填充] | [AI填充] |")

    # === 十一、对自己的启示（有 comparison 时增强） ===
    if comparison:
        lines.append(f"\n## 十一、对你的启示 ★★★")
        ss = comparison["self_stats"]; ts = comparison["target_stats"]
        lines.append(f"\n### 你 vs {nickname}")
        lines.append(f"\n| 维度 | {nickname} | 你 | 差距 | 评价 |")
        lines.append(f"|------|----------|-----|------|------|")
        for key, label in [("total","笔记数"),("avg_likes","均赞"),("avg_collects","均收藏"),("avg_comments","均评论")]:
            diff = ts[key] - ss[key]
            eval_str = "✅ 你领先" if diff < 0 else ("⚠️ 需追赶" if diff > 0 else "平手")
            lines.append(f"| {label} | {ts[key]:,} | {ss[key]:,} | {diff:+,} | {eval_str} |")
        lines.append(f"\n### 具体可执行建议")
        lines.append(f"1. **[AI 填充：具体行动标题]** — [2-3行展开 + 具体操作步骤]")
        lines.append(f"2. **[AI 填充：具体行动标题]** — [2-3行展开 + 具体操作步骤]")
        lines.append(f"3. **[AI 填充：具体行动标题]** — [2-3行展开 + 具体操作步骤]")
        lines.append(f"4. **[AI 填充：具体行动标题]** — [2-3行展开 + 具体操作步骤]")
        lines.append(f"5. **[AI 填充：具体行动标题]** — [2-3行展开 + 具体操作步骤]")
        lines.append(f"6. **[AI 填充：具体行动标题]** — [2-3行展开 + 具体操作步骤]")
    else:
        lines.append(f"\n## 十一、数据附录")
        lines.append(f"\n| 笔记 # | 标题 | 类型 | 赞 | 藏 | 评 | 领域 |")
        lines.append(f"|--------|------|------|-----|-----|-----|------|")
        for i, n in enumerate((notes or [])[:50]):
            lines.append(f"| {i+1} | {n['title'][:25]} | {n.get('type','?')} | {n['likes_raw']} | {n['collects_raw']} | {n['comments_raw']} | {n.get('category','?')} |")

    return "\n".join(lines)


def gen_enhanced_content_formula(nickname, top10, category_stats, title_patterns,
                                  emoji_info, cta_info, structure_info, image_info=None):
    """增强版内容公式总结 — 9章完整结构，对齐产出物质量标杆"""
    lines = [
        f"# {nickname} — 内容公式总结",
        f"\n> 从全量笔记中提取的可复用内容公式 | 采集时间: {datetime.now().strftime('%Y-%m-%d')}",
    ]

    # === 一、标题公式（11种） ===
    lines.append(f"\n## 一、标题公式（按效果排序）★★★")
    if title_patterns:
        sorted_pats = sorted(title_patterns.items(), key=lambda x: x[1]["count"], reverse=True)
        for i, (pname, pdata) in enumerate(sorted_pats):
            flame = "🔥" if i < 3 else ""
            lines.append(f"\n### {i+1}. {flame} {pname}型（{pdata['count']}条，占{pdata['pct']}%）")
            lines.append(f"- **格式模板**: [AI 填充：用 [变量] 表示可替换部分]")
            lines.append(f"- **案例**:")
            for ex in pdata["examples"][:3]:
                lines.append(f"  - 「{ex}」")
            lines.append(f"- **核心逻辑**: [AI 填充：一句话解释为什么有效]")
            lines.append(f"- **适用场景**: [AI 填充：什么时候用]")
            lines.append(f"- **你的改编示例**: [AI 填充：3个针对你定位的改编标题]")
    else:
        lines.append(f"\n标题数据不足。")

    lines.append(f"\n## 二、开头公式（6种）")
    lines.append(f"\n| 开头类型 | 格式模板 | 典型案例 | 适用场景 |")
    lines.append(f"|----------|---------|---------|---------|")
    for i, ot in enumerate(["痛点切入型","结果前置型","悬念型","共情型","反常识型","利益承诺型"]):
        lines.append(f"| {ot} | [AI填充] | — | — |")

    # === 三、内容结构模板 ===
    lines.append(f"\n## 三、内容结构模板（5种，有星级推荐）")
    if structure_info:
        lines.append(f"\n**正文特征**: 均{structure_info['avg_length']}字, 列表{structure_info['has_list_count']}条, 数字标题{structure_info['has_number_heading']}条")
    lines.append(f"\n| 模板 | 星级 | 结构分配 | 适用场景 |")
    lines.append(f"|------|------|---------|---------|")
    for tmpl, stars in [("教程型", "⭐⭐⭐"),("清单型", "⭐⭐⭐"),("故事型", "⭐⭐"),("对比型", "⭐⭐"),("合集型", "⭐")]:
        lines.append(f"| {tmpl} | {stars} | [AI填充: 百分比分配] | [AI填充] |")

    # === 四、CTA公式 ===
    lines.append(f"\n## 四、CTA 公式")
    if cta_info:
        lines.append(f"\n| CTA 类型 | 使用率 | 适用场景 | 效果评估 |")
        lines.append(f"|----------|--------|---------|---------|")
        for cta_type, data in sorted(cta_info.items(), key=lambda x: x[1]["count"], reverse=True):
            lines.append(f"| {cta_type} | {data['pct']}% | [AI填充] | [AI填充] |")
        top_cta = max(cta_info.items(), key=lambda x: x[1]["count"])
        lines.append(f"\n**CTA策略**: 最常用「{top_cta[0]}」（{top_cta[1]['pct']}%）")
    else:
        lines.append(f"\n内容驱动互动型——靠内容质量自然吸引互动。")

    # === 五、视觉/制作公式 ===
    lines.append(f"\n## 五、视觉 / 制作公式")
    if emoji_info:
        lines.append(f"- Emoji使用率: {emoji_info['emoji_usage_pct']}%")
        if emoji_info.get("top_emojis"):
            lines.append(f"- 高频: {' '.join(e[0] for e in emoji_info['top_emojis'][:5])}")
    if image_info and image_info.get("image_posts_count", 0) > 0:
        lines.append(f"- 图片序列: {image_info['sequence_pattern']}（均{image_info['image_posts_avg_images']}张/条）")
        lines.append(f"- 版面: {image_info['layout_type']}")
    lines.append(f"\n| 视觉维度 | 公式 | 说明 |")
    lines.append(f"|----------|------|------|")
    lines.append(f"| 封面公式 | [AI填充] | — |")
    lines.append(f"| 排版节奏 | [AI填充] | — |")
    lines.append(f"| 配色风格 | [AI填充] | — |")

    # === 六、标签公式 ===
    lines.append(f"\n## 六、标签公式")
    lines.append(f"```")
    lines.append(f"固定标签: [AI 填充]（每条都带，账号定位核心词）")
    lines.append(f"  ├── 身份标签: [AI 填充]（让用户知道你是谁）")
    lines.append(f"  ├── 工具标签: [AI 填充]（提高搜索曝光）")
    lines.append(f"  ├── 流量标签: [AI 填充]（蹭热点/趋势）")
    lines.append(f"  └── 活动标签: [AI 填充]（参与官方活动）")
    lines.append(f"```")

    # === 七、排版/文案风格 ===
    lines.append(f"\n## 七、排版 / 文案风格公式")
    lines.append(f"\n| 风格维度 | 特征 | 可借鉴点 |")
    lines.append(f"|----------|------|---------|")
    lines.append(f"| 语气 | [AI填充] | — |")
    lines.append(f"| 段落节奏 | [AI填充] | — |")
    lines.append(f"| 标点习惯 | [AI填充] | — |")

    # === 八、发布时间公式 ===
    lines.append(f"\n## 八、发布时间公式")
    lines.append(f"\n| 时间段 | 适合内容类型 | 原因 |")
    lines.append(f"|--------|------------|------|")
    lines.append(f"| [AI填充] | — | — |")
    lines.append(f"| [AI填充] | — | — |")
    lines.append(f"| [AI填充] | — | — |")

    # === 九、一句话总结 ===
    lines.append(f"\n## 九、一句话总结 ★★★")
    lines.append(f"\n### {nickname} 的内容公式")
    lines.append(f"```")
    lines.append(f"{nickname}的成功 = [AI填充: 标题公式] × [AI填充: 内容结构] × [AI填充: CTA策略] × [AI填充: 视觉风格]")
    lines.append(f"```")
    lines.append(f"\n### 翻译成你的版本")
    lines.append(f"```")
    lines.append(f"你的成功 = [AI 填充: 替换为你的定位和资源]")
    lines.append(f"```")

    return "\n".join(lines)


def gen_enhanced_topic_library(nickname, top10, category_stats, tag_freq, notes=None):
    """增强版选题素材库 — 6章完整结构，对齐产出物质量标杆"""
    lines = [
        f"# {nickname} — 选题素材库",
        f"\n> 基于 {nickname} 全量笔记提炼的可执行选题 | 采集时间: {datetime.now().strftime('%Y-%m-%d')}",
    ]

    # === 一、已验证的爆款选题 ===
    lines.append(f"\n## 一、已验证的爆款选题")
    lines.append(f"\n| # | 选题 | 赞数 | 领域 | 借鉴方向 |")
    lines.append(f"|---|------|------|------|---------|")
    for i, n in enumerate(top10[:10]):
        lines.append(f"| {i+1} | {n['title'][:30]} | {n['likes_raw']} | {n.get('category', '其他')} | [AI填充] |")

    # === 二、各领域选题库 ===
    lines.append(f"\n## 二、对标做过的高赞选题（按优先级）")
    avg_likes_all = sum(cs["avg_likes"] for cs in category_stats.values()) / max(len(category_stats), 1)
    lines.append(f"\n### 🔴 A级 · 极高优先级（高于均值 {avg_likes_all:,.0f} 赞）")
    for cat, cs in sorted(category_stats.items(), key=lambda x: x[1]["avg_likes"], reverse=True):
        if cs["avg_likes"] > avg_likes_all * 1.5:
            lines.append(f"- **{cat}**: 「{cs['top_note'][:30]}」({cs['avg_likes']:,}赞) → [AI 填充: 改编方向]")
    lines.append(f"\n### 🟡 B级 · 高优先级")
    for cat, cs in sorted(category_stats.items(), key=lambda x: x[1]["avg_likes"], reverse=True):
        if avg_likes_all <= cs["avg_likes"] <= avg_likes_all * 1.5:
            lines.append(f"- **{cat}**: 「{cs['top_note'][:30]}」({cs['avg_likes']:,}赞) → [AI 填充: 改编方向]")
    lines.append(f"\n### 🟢 C级 · 可选选题")
    for cat, cs in sorted(category_stats.items(), key=lambda x: x[1]["avg_likes"], reverse=True):
        if cs["avg_likes"] < avg_likes_all:
            lines.append(f"- **{cat}**: 「{cs['top_note'][:30]}」({cs['avg_likes']:,}赞) → [AI 填充]")

    # === 三、差异化赛道 ===
    lines.append(f"\n## 三、对标没做但你可以做的差异化选题 ★★★")
    lines.append(f"\n> *（AI 执行时：基于 CONTENT_TRACKS 29赛道分类，找对标未覆盖但你的定位能切入的方向）*")
    lines.append(f"\n| 差异化赛道 | 建议选题 | 估计潜力 | 理由 |")
    lines.append(f"|-----------|---------|---------|------|")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — |")

    # === 四、优先级 × 创作难度矩阵 ===
    lines.append(f"\n## 四、选题优先级 × 创作难度矩阵")
    lines.append(f"\n| 选题方向 | 效果优先级 | 创作难度 | 建议路径 |")
    lines.append(f"|----------|-----------|---------|---------|")
    sorted_cats = sorted(category_stats.items(), key=lambda x: x[1]["avg_likes"], reverse=True)
    for i, (cat, cs) in enumerate(sorted_cats[:8]):
        priority = "🔴" if cs["avg_likes"] > avg_likes_all*1.3 else ("🟡" if cs["avg_likes"] >= avg_likes_all else "🟢")
        difficulty = "🟢入门" if cs["count"] >= 5 else ("🟡进阶" if cs["count"] >= 2 else "🔴高阶")
        lines.append(f"| {cat} | {priority} | {difficulty} | {'从这里开始' if priority=='🔴' and difficulty=='🟢入门' else '数据积累后尝试'} |")
    lines.append(f"\n**建议路径**: 先从🔴高优先级+🟢入门难度的选题开始，快速产出 → 验证 → 逐步挑战高难度。")

    # === 五、系列IP建议 ===
    lines.append(f"\n## 五、系列 IP 建议")
    lines.append(f"\n| 系列名 | 定位 | 集数建议 | 发布频率 | 理由 |")
    lines.append(f"|--------|------|---------|---------|------|")
    lines.append(f"| [AI填充] | — | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — | — |")
    lines.append(f"\n**节奏规划**: 每5集一个主题阶段，前3集建立认知，后2集深化印象。")

    # === 六、素材积累提醒 ===
    lines.append(f"\n## 六、素材积累提醒")
    lines.append(f"\n### 日常记录清单")
    lines.append(f"- [ ] 每天刷对标博主新笔记 → 记录选题方向和评论区高频问题")
    lines.append(f"- [ ] 每周整理一次收藏夹 → 分类标注可改编选题")
    lines.append(f"- [ ] 每月回顾一次自己的数据 → 找出你的爆款模式")
    lines.append(f"- [ ] 关注 {', '.join(t for t,c in tag_freq[:3])} 等核心标签下的新内容")
    lines.append(f"- [ ] 保存用户评论中的提问 → 这些都是选题灵感")
    lines.append(f"- [ ] 记录热点事件 → 第一时间产出相关内容")
    lines.append(f"\n### 内容日历建议")
    lines.append(f"- 周一/周三/周五: 发布主力内容（教程/攻略/分享）")
    lines.append(f"- 周末: 发布轻量内容（日常/vlog/互动）")
    lines.append(f"\n### 热点追踪")
    lines.append(f"- 小红书搜索框 → 查看热搜词")
    lines.append(f"- 对标博主的评论区 → 看用户在讨论什么")
    lines.append(f"- 同赛道 TOP 博主的最近爆款 → 分析热点方向")

    # 标签参考
    lines.append(f"\n## 附录：热门标签参考")
    lines.append(f"\n| 标签 | 使用次数 |")
    lines.append(f"|------|---------|")
    for tag, count in tag_freq[:15]:
        lines.append(f"| #{tag} | {count} |")

    return "\n".join(lines)


def gen_enhanced_structured_analysis(nickname, stats, notes, category_stats, tag_freq,
                                      frequency_info, growth_info, sentiment_info=None, heatmap_info=None, image_info=None):
    """增强版全量笔记结构化分析 — 8章完整结构，对齐产出物质量标杆"""
    lines = [
        f"# {nickname} — 全量笔记结构化分析",
        f"\n> {stats['total']}条笔记的完整数据视角 | 采集时间: {datetime.now().strftime('%Y-%m-%d')}",
    ]

    # === 一、数据总览 ===
    lines.append(f"\n## 一、数据总览")
    lines.append(f"\n### 核心数据")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 总笔记 | {stats['total']} |")
    lines.append(f"| 视频/图文 | {stats['video_count']}/{stats['normal_count']} |")
    lines.append(f"| 总赞 | {stats['total_likes']:,} |")
    lines.append(f"| 总收藏 | {stats['total_collects']:,} |")
    lines.append(f"| 总评论 | {stats['total_comments']:,} |")
    lines.append(f"| 均赞 | {stats['avg_likes']:,} |")
    lines.append(f"| 均收藏 | {stats['avg_collects']:,} |")
    lines.append(f"| 均评论 | {stats['avg_comments']:,} |")

    if frequency_info and frequency_info.get("pattern") != "数据不足":
        lines.append(f"\n### 发布节奏")
        lines.append(f"- **频率**: {frequency_info['pattern']}（平均{frequency_info['avg_days_between']}天/条）")
        lines.append(f"- **判定**: [AI 填充：属于日更型/周更型/低频型，对流量稳定性的影响]")

    # 图片序列
    if image_info and image_info.get("image_posts_count", 0) > 0:
        ir = image_info.get("aspect_ratios", {})
        lines.append(f"\n### 视觉风格 ✅ 数据结论")
        lines.append(f"- 图片序列: {image_info['sequence_pattern']}（均{image_info['image_posts_avg_images']}张/条）")
        lines.append(f"- 版面: {image_info['layout_type']}")
        lines.append(f"- 比例分布: 竖版{ir.get('portrait_pct',0)}% / 方图{ir.get('square_pct',0)}% / 横版{ir.get('landscape_pct',0)}%")
        if image_info.get("consistent_layout"):
            lines.append(f"- ✅ 固定版面风格，视觉辨识度高")

    # === 二、内容领域全景图 ===
    lines.append(f"\n## 二、内容领域全景图")
    lines.append(f"\n### 2.1 领域分布")
    lines.append(f"\n| 领域 | 笔记数 | 占比 | 篇均赞 | 篇均收藏 |")
    lines.append(f"|------|--------|------|--------|---------|")
    for cat, cs in category_stats.items():
        lines.append(f"| {cat} | {cs['count']} | {cs['pct']}% | {cs['avg_likes']:,} | — |")

    # 策略类型判断
    top_cat = max(category_stats.items(), key=lambda x: x[1]["count"])[0] if category_stats else ""
    top_cat_pct = category_stats[top_cat]["pct"] if top_cat in category_stats else 0
    lines.append(f"\n### 2.2 策略类型: {'极度垂直型' if top_cat_pct>70 else ('多元交叉型' if len(category_stats)>=3 else '垂直为主')}")
    lines.append(f"- [AI 填充：该策略的利弊分析，对用户账号的参考意义]")
    lines.append(f"\n### 2.3 领域交叉矩阵 ★★★")
    lines.append(f"> *交叉是爆款的底层逻辑*")
    lines.append(f"\n| 交叉组合 | 笔记数 | 均赞 | 是否爆款密区 |")
    lines.append(f"|----------|--------|------|------------|")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"| [AI填充] | — | — | — |")
    lines.append(f"\n**核心发现**: [AI 填充：哪两个领域的交叉最容易出爆款？]")

    # === 三、发展趋势分析 ===
    lines.append(f"\n## 三、发展趋势分析")
    if growth_info and stats['total'] >= 6:
        lines.append(f"\n将{stats['total']}条笔记按时间切半（前{growth_info['early_count']}条 vs 后{growth_info['recent_count']}条）：\n")
        lines.append(f"| 领域 | 早期占比 | 近期占比 | 变化 |")
        lines.append(f"|------|---------|---------|------|")
        for cat, change in sorted(growth_info["category_shifts"].items(), key=lambda x: abs(x[1]["delta"]), reverse=True):
            arrow = "📈" if change["delta"] > 5 else ("📉" if change["delta"] < -5 else "➡️")
            lines.append(f"| {cat} | {change['early_pct']}% | {change['recent_pct']}% | {arrow} {change['delta']:+.1f}% |")
        growing = [c for c, d in growth_info["category_shifts"].items() if d["delta"] > 10]
        declining = [c for c, d in growth_info["category_shifts"].items() if d["delta"] < -10]
        if growing:
            lines.append(f"\n📈 **增长方向**: 「{'、'.join(growing)}」占比上升，博主正在向此方向转型。")
        if declining:
            lines.append(f"\n📉 **收缩方向**: 「{'、'.join(declining)}」占比下降。")
    else:
        lines.append(f"\n笔记不足6条或缺少时间数据，跳过趋势分析。")

    # === 四、爆款公式深度拆解 ★★★ ===
    lines.append(f"\n## 四、爆款公式深度拆解 ★★★")
    if notes:
        avg_likes = stats["avg_likes"]
        hits = [n for n in notes if n.get("likes", 0) > avg_likes * 3]
        super_hits = [n for n in notes if n.get("likes", 0) > avg_likes * 10]

        lines.append(f"\n### 4.1 爆款总览")
        lines.append(f"- 爆款标准: >{avg_likes*3:,.0f}赞（3×均赞）")
        lines.append(f"- 爆款: {len(hits)}条（{round(len(hits)/max(len(notes),1)*100,1)}%）")
        if super_hits:
            lines.append(f"- 超级爆款: {len(super_hits)}条（>10×均赞）")

        if hits:
            hit_cats = Counter(n.get("category", "其他") for n in hits)
            lines.append(f"- 爆款集中领域: 「{hit_cats.most_common(1)[0][0] if hit_cats else '?'}」")
            lines.append(f"\n### 4.2 超高赞公式（>{avg_likes*10:,.0f}赞）")
            lines.append(f"- [AI 填充：解剖最高赞笔记的每个要素 + 权重百分比]")
            lines.append(f"\n### 4.3 爆款公式（>{avg_likes*3:,.0f}赞）")
            lines.append(f"- [AI 填充：提取爆款共性 → 一句话公式]")
            lines.append(f"\n### 4.4 低于均值内容共性（避坑指南）")
            low_notes = [n for n in notes if n.get("likes", 0) < avg_likes * 0.5][:5]
            if low_notes:
                lines.append(f"\n| 低赞笔记 | 赞数 | 可能原因 |")
                lines.append(f"|----------|------|---------|")
                for ln in low_notes:
                    lines.append(f"| {ln['title'][:25]} | {ln['likes_raw']} | [AI填充] |")
                lines.append(f"\n**避坑清单**: [AI 填充：失败模式的共同特征]")

    # === 五、互动数据结构化分析 ===
    lines.append(f"\n## 五、互动数据结构化分析")
    lines.append(f"\n### 5.1 藏赞比分析")
    if notes:
        total_likes = stats.get("total_likes", 1) or 1
        slr = round(stats.get("total_collects", 0) / total_likes, 2)
        lines.append(f"- 整体藏赞比: **{slr}** — {'>0.6 实用工具型，收藏远超点赞，用户将内容视为工具反复查阅' if slr>0.6 else ('0.3-0.6 实用驱动型，收藏显著高于点赞' if slr>0.33 else ('0.2-0.3 均衡型' if slr>0.2 else '<0.2 情绪共鸣型，点赞为主收藏为辅'))}")
        lines.append(f"- 核心洞察: *教程收藏不点赞，观点点赞不收藏*")
        lines.append(f"\n| 藏赞比区间 | 类型 | 笔记数 | 典型特征 |")
        lines.append(f"|-----------|------|--------|---------|")
        for threshold, label in [(0.6, ">0.8 强实用型"), (0.33, "0.3-0.8 均衡型"), (0, "<0.3 情绪型")]:
            count = sum(1 for n in notes if n.get("collects", 0) / max(n.get("likes", 0), 1) > threshold) if threshold > 0 else len(notes)
            lines.append(f"| {label} | — | — | [AI填充] |")

    lines.append(f"\n### 5.2 评论深度分析")
    if sentiment_info and sentiment_info.get("total_comments_analyzed", 0) > 0:
        overall = sentiment_info["overall_score"] or 0
        lines.append(f"- 整体情感: {overall:+.1f}/1.0")
        lines.append(f"- 分析评论: {sentiment_info['total_comments_analyzed']}条")
    lines.append(f"- [AI 填充：高赞评论类型分布 + 作者回复策略分析]")

    # === 六、标签生态分析 ===
    lines.append(f"\n## 六、标签生态分析")
    lines.append(f"\n| 标签 | 频次 | 作用 | 建议 |")
    lines.append(f"|------|------|------|------|")
    for tag, count in tag_freq[:10]:
        lines.append(f"| #{tag} | {count} | [AI填充] | [AI填充] |")
    lines.append(f"\n### 用户标签矩阵建议")
    lines.append(f"```")
    lines.append(f"固定标签: [AI 填充：账号定位标签，每条都用]")
    lines.append(f"  ├── 身份标签: [AI 填充：人群识别]")
    lines.append(f"  ├── 工具标签: [AI 填充：提升搜索]")
    lines.append(f"  ├── 流量标签: [AI 填充：蹭热点]")
    lines.append(f"  └── 活动标签: [AI 填充：参与活动]")
    lines.append(f"```")

    # === 七、竞争格局与机会窗口 ===
    lines.append(f"\n## 七、竞争格局与机会窗口")
    lines.append(f"\n### 同赛道竞争者")
    lines.append(f"\n| 竞争者 | 粉丝量级 | 差异化特征 | 可借鉴点 |")
    lines.append(f"|--------|---------|-----------|---------|")
    lines.append(f"| [AI 填充：基于 CONTENT_TRACKS 赛道分类找到的同赛道博主] | — | — | — |")
    lines.append(f"\n### 用户差异化机会")
    lines.append(f"- 🔴 [AI 填充：竞争烈度高但值得做的方向]")
    lines.append(f"- 🟡 [AI 填充：中等竞争，有差异化空间]")
    lines.append(f"- 🟢 [AI 填充：蓝海方向，快速抢占]")
    lines.append(f"\n### 应避开的赛道")
    lines.append(f"- [AI 填充：红海/不适合用户定位的方向]")

    # === 八、核心结论 ★★★ ===
    lines.append(f"\n## 八、核心结论 ★★★")
    lines.append(f"\n### {nickname} 的底层公式")
    lines.append(f"```")
    lines.append(f"成功 = [AI填充: 身份标签] × [AI填充: 内容形式] × [AI填充: 标题策略] × [AI填充: 发布节奏] × [AI填充: 独特优势]")
    lines.append(f"```")
    lines.append(f"\n### 用户的行动公式")
    lines.append(f"```")
    lines.append(f"你的成功 = [AI填充: 翻译版，每个要素对应替换]")
    lines.append(f"```")
    lines.append(f"\n### 最重要的3件事")
    lines.append(f"1. **[AI 填充]**: [今天就可以开始的行动]")
    lines.append(f"2. **[AI 填充]**: [本周内完成的行动]")
    lines.append(f"3. **[AI 填充]**: [本月内的战略调整]")

    # 全量笔记附录
    lines.append(f"\n---")
    lines.append(f"\n## 附录：全量笔记列表")
    lines.append(f"\n| # | 标题 | 类型 | 赞 | 藏 | 评 | 领域 |")
    lines.append(f"|---|------|------|-----|-----|-----|------|")
    for i, n in enumerate(notes[:100]):
        lines.append(
            f"| {i+1} | {n['title'][:25]} | {n.get('type', '?')} | "
            f"{n.get('likes_raw', '?')} | {n.get('collects_raw', '?')} | {n.get('comments_raw', '?')} | {n.get('category', '?')} |"
        )

    # 热力图（如有）
    if heatmap_info and heatmap_info.get("total_notes_with_time", 0) > 0:
        lines.append(f"\n---")
        lines.append(f"\n## 附录：发布时间热力图")
        lines.append(f"\n共 {heatmap_info['total_notes_with_time']} 条笔记有时间数据。")
        lines.append(f"\n**最佳发布**: {heatmap_info.get('best_day', '?')} {heatmap_info.get('best_hour_block', '?')}")
        optimal = heatmap_info.get("optimal_windows", [])
        if optimal:
            lines.append(f"\n**最佳窗口 TOP3**:")
            for i, w in enumerate(optimal[:3]):
                lines.append(f"{i+1}. **{w['day']} {w['slot']}** — 均赞 {w['avg_likes']:,.0f}，{w['count']}条")

        lines.append(f"\n### 频次热力图")
        lines.append(f"\n| 时段\\\\星期 | {' | '.join(heatmap_info['day_names_cn'])} |")
        lines.append(f"|{'------|' * 8}")
        matrix = heatmap_info["hour_day_matrix"]
        time_slots = heatmap_info["time_slots"]
        for s in range(7):
            cells = []
            for d in range(7):
                val = matrix[s][d]
                cells.append(f"{val}██" if val>=6 else (f"{val}▓▓" if val>=4 else (f"{val}▓" if val>=2 else (f"{val}░" if val==1 else "·"))))
            lines.append(f"| {time_slots[s]} | {' | '.join(cells)} |")
        lines.append(f"\n> 图例：██密集(≥6) ▓▓较多(4-5) ▓中等(2-3) ░稀疏(1) ·空(0)")

    return "\n".join(lines)

    # ★ 新增：内容赛道分布
    if notes:
        track_counter = {}
        for n in notes[:100]:
            title = n.get("title", "")
            # desc 可能不在 analysis notes 中，用 title + tags
            tags = n.get("tags", [])
            track = classify_content_track(title, "", tags)
            primary = track.get("primary_track", "其他")
            track_counter[primary] = track_counter.get(primary, 0) + 1
        if track_counter:
            lines.append(f"\n## 内容赛道分布 ✅ 数据结论")
            lines.append(f"\n| 赛道 | 笔记数 | 占比 |")
            lines.append(f"|------|--------|------|")
            total_classified = sum(track_counter.values())
            for track_name, count in sorted(track_counter.items(), key=lambda x: x[1], reverse=True):
                pct = round(count / total_classified * 100, 1) if total_classified else 0
                lines.append(f"| {track_name} | {count} | {pct}% |")
            top_track = max(track_counter, key=track_counter.get)
            lines.append(f"\n**主导赛道**：{top_track}（{track_counter[top_track]}条/{total_classified}条）")

    # ★ 新增：视觉风格与图片序列分析
    if image_info and image_info.get("image_posts_count", 0) > 0:
        ir = image_info.get("aspect_ratios", {})
        lines.append(f"\n## 视觉风格与图片序列 ✅ 数据结论")
        lines.append(f"\n> 基于 MCP 返回的 imageList 真实元数据（非文本推断）")
        lines.append(f"\n| 指标 | 数值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 图文笔记数 | {image_info['image_posts_count']} |")
        lines.append(f"| 视频笔记数 | {image_info.get('video_posts_count', 0)} |")
        lines.append(f"| 平均图片数 | {image_info['image_posts_avg_images']}张/条 |")
        lines.append(f"| 图片数范围 | {image_info['image_posts_min_images']}～{image_info['image_posts_max_images']}张 |")
        lines.append(f"| 图片序列模式 | **{image_info['sequence_pattern']}** |")
        lines.append(f"\n**序列解读**：{image_info.get('sequence_description', '')}")
        lines.append(f"\n### 版面比例分布")
        lines.append(f"\n| 类型 | 占比 | 说明 |")
        lines.append(f"|------|------|------|")
        lines.append(f"| 竖版（h/w > 1.2） | {ir.get('portrait_pct', 0)}% | 适合人像/穿搭/全身/OOTD |")
        lines.append(f"| 方图（0.9～1.2） | {ir.get('square_pct', 0)}% | 适合产品/截图/教程卡片 |")
        lines.append(f"| 横版（h/w < 0.9） | {ir.get('landscape_pct', 0)}% | 适合场景/风景/桌面/全景 |")
        lines.append(f"\n**版面类型**：{image_info['layout_type']}")
        lines.append(f"\n**封面比例分析**：{image_info.get('cover_aspect_analysis', '')}")
        if image_info.get("consistent_layout"):
            lines.append(f"\n✅ 该博主采用**固定版面风格**，>80%笔记使用同一比例类型，视觉辨识度高，已形成视觉心锚。")
        else:
            lines.append(f"\n💡 该博主为**混合版面**，根据内容灵活选择图片比例，不拘泥于单一视觉风格。")
    elif image_info and image_info.get("video_posts_count", 0) > 0 and image_info.get("image_posts_count", 0) == 0:
        lines.append(f"\n## 视觉风格与图片序列 ✅ 数据结论")
        lines.append(f"\n> 该博主为**全视频账号**（{image_info['video_posts_count']}条视频），无图文笔记。图片序列分析不适用。")

    lines.append(f"\n## 二、内容领域分布")
    lines.append(f"\n| 领域 | 数量 | 占比 | 均赞 |")
    lines.append(f"|------|------|------|------|")
    for cat, cs in category_stats.items():
        lines.append(f"| {cat} | {cs['count']} | {cs['pct']}% | {cs['avg_likes']:,} |")

    # 全量笔记列表
    lines.append(f"\n## 三、全量笔记列表")
    lines.append(f"\n| # | 标题 | 类型 | 赞 | 藏 | 评 | 领域 |")
    lines.append(f"|---|------|------|-----|-----|-----|------|")
    for i, n in enumerate(notes[:100]):
        lines.append(
            f"| {i+1} | {n['title'][:25]} | {n.get('type', 'normal')} | "
            f"{n.get('likes_raw', '?')} | {n.get('collects_raw', '?')} | {n.get('comments_raw', '?')} | {n.get('category', '其他')} |"
        )

    # 发展趋势
    lines.append(f"\n## 四、发展趋势分析")
    if growth_info:
        lines.append(f"\n将{stats['total']}条笔记按时间分为前半（{growth_info['early_count']}条）和后半（{growth_info['recent_count']}条）：\n")
        lines.append(f"| 领域 | 早期占比 | 近期占比 | 变化 |")
        lines.append(f"|------|---------|---------|------|")
        for cat, change in sorted(growth_info["category_shifts"].items(), key=lambda x: abs(x[1]["delta"]), reverse=True):
            arrow = "📈" if change["delta"] > 5 else ("📉" if change["delta"] < -5 else "➡️")
            lines.append(f"| {cat} | {change['early_pct']}% | {change['recent_pct']}% | {arrow} {change['delta']:+.1f}% |")

        # 找显著变化
        growing = [c for c, d in growth_info["category_shifts"].items() if d["delta"] > 10]
        declining = [c for c, d in growth_info["category_shifts"].items() if d["delta"] < -10]
        if growing:
            lines.append(f"\n**内容转型趋势**：近期「{'、'.join(growing)}」占比明显增加，说明博主正在向这个方向转型。")
        if declining:
            lines.append(f"\n**内容收缩方向**：「{'、'.join(declining)}」占比下降，博主可能在这些领域遇到了瓶颈或主动收缩。")
    else:
        lines.append(f"\n笔记数量不足或缺少时间数据，无法分析发展趋势。")

    # 爆款分析
    lines.append(f"\n## 五、爆款规律总结")
    if notes:
        avg_likes = stats["avg_likes"]
        hits = [n for n in notes if n.get("likes", 0) > avg_likes * 3]
        lines.append(f"\n定义爆款：赞数超过均值3倍（>{avg_likes * 3:,}赞）的笔记。\n")
        lines.append(f"- **爆款数量**：{len(hits)}条（占总数{round(len(hits)/len(notes)*100, 1) if notes else 0}%）")
        if hits:
            hit_cats = Counter(n.get("category", "其他") for n in hits)
            top_hit_cat = hit_cats.most_common(1)[0] if hit_cats else ("其他", 0)
            lines.append(f"- **爆款集中领域**：「{top_hit_cat[0]}」（{top_hit_cat[1]}条爆款）")
            hit_types = Counter(n.get("type", "normal") for n in hits)
            lines.append(f"- **爆款形式**：{', '.join(f'{t}({c}条)' for t, c in hit_types.most_common())}")

    # ---- 评论区情感趋势 ----
    if sentiment_info and sentiment_info.get("total_comments_analyzed", 0) > 0:
        lines.append(f"\n## 六、评论区情感趋势")
        overall = sentiment_info["overall_score"] or 0
        lines.append(f"\n**整体情感得分**: {overall:+.1f}/1.0（-1=极度负面, +1=极度正面）")
        lines.append(f"**分析评论总数**: {sentiment_info['total_comments_analyzed']}条")

        # 按情感标签统计笔记数
        label_counts = Counter(n.get("sentiment_label", "无评论") for n in sentiment_info["per_note"])
        lines.append(f"\n| 情感倾向 | 笔记数 |")
        lines.append(f"|----------|--------|")
        for label in ["正向为主", "中性/混合", "负向为主", "无评论"]:
            count = label_counts.get(label, 0)
            if count > 0:
                emoji = {"正向为主":"😊","中性/混合":"😐","负向为主":"😟","无评论":"📭"}.get(label, "")
                lines.append(f"| {emoji} {label} | {count} |")

        # 找情感极端笔记
        high_pos = [n for n in sentiment_info["per_note"] if n["positive_pct"] >= 80 and n["comment_count"] >= 3]
        high_neg = [n for n in sentiment_info["per_note"] if n["negative_pct"] >= 30 and n["comment_count"] >= 3]
        if high_pos:
            lines.append(f"\n**高好评笔记**（正向评论≥80%）: " + ", ".join(n["note_title"][:15] for n in high_pos[:3]))
        if high_neg:
            lines.append(f"\n**高争议笔记**（负向评论≥30%）: " + ", ".join(n["note_title"][:15] for n in high_neg[:3]))

    # ---- 发布时间热力图 ----
    if heatmap_info and heatmap_info.get("total_notes_with_time", 0) > 0:
        section_num = "七" if (sentiment_info and sentiment_info.get("total_comments_analyzed", 0) > 0) else "六"
        lines.append(f"\n## {section_num}、发布时间分析")
        lines.append(f"\n共 {heatmap_info['total_notes_with_time']} 条笔记有有效发布时间。")
        lines.append(f"\n**最常发布**: {heatmap_info.get('best_day', '?')}的{heatmap_info.get('best_hour_block', '?')}")

        # 频次热力图
        lines.append(f"\n### 发布频次热力图")
        lines.append(f"\n| 时段\\\\星期 | {' | '.join(heatmap_info['day_names_cn'])} |")
        lines.append(f"|{'------|' * 8}")
        matrix = heatmap_info["hour_day_matrix"]
        time_slots = heatmap_info["time_slots"]
        for s in range(7):
            cells = []
            for d in range(7):
                val = matrix[s][d]
                if val >= 6:
                    cells.append(f"{val}██")
                elif val >= 4:
                    cells.append(f"{val}▓▓")
                elif val >= 2:
                    cells.append(f"{val}▓")
                elif val == 1:
                    cells.append(f"{val}░")
                else:
                    cells.append("·")
            lines.append(f"| {time_slots[s]} | {' | '.join(cells)} |")

        lines.append(f"\n> 图例：██密集(≥6) ▓▓较多(4-5) ▓中等(2-3) ░稀疏(1) ·空(0)")

        # 平均赞数热力图
        lines.append(f"\n### 各时段平均互动表现")
        lines.append(f"\n| 时段\\\\星期 | {' | '.join(heatmap_info['day_names_cn'])} |")
        lines.append(f"|{'------|' * 8}")
        eng_matrix = heatmap_info["engagement_matrix"]
        for s in range(7):
            cells = []
            for d in range(7):
                val = eng_matrix[s][d]
                if val > 0:
                    cells.append(f"{val:,.0f}")
                else:
                    cells.append("-")
            lines.append(f"| {time_slots[s]} | {' | '.join(cells)} |")

        # 最佳发布窗口
        optimal = heatmap_info.get("optimal_windows", [])
        if optimal:
            lines.append(f"\n**最佳发布窗口**（按均赞排序，最少2条）：\n")
            for i, w in enumerate(optimal):
                lines.append(f"{i+1}. **{w['day']} {w['slot']}** — 均赞 {w['avg_likes']:,.0f}，发布 {w['count']}条")

        # 核心发现
        lines.append(f"\n**核心发现**：")
        lines.append(f"- 该博主最常发布时间是 **{heatmap_info.get('best_day', '?')}** 的 **{heatmap_info.get('best_hour_block', '?')}**")
        if heatmap_info.get("best_day_avg_likes", 0) > 0:
            lines.append(f"- {heatmap_info['best_day']} 平均赞数 {heatmap_info['best_day_avg_likes']:,.0f}")
        if heatmap_info.get("best_hour_avg_likes", 0) > 0:
            lines.append(f"- {heatmap_info['best_hour_block']} 平均赞数 {heatmap_info['best_hour_avg_likes']:,.0f}")

    return "\n".join(lines)


# ----------------------------------------------------------
# AI Prompt 生成
# ----------------------------------------------------------

def gen_ai_prompt(nickname, analysis_data, notes_details=None):
    """生成 AI 深度分析 Prompt 文件"""
    stats = analysis_data["stats"]
    top10 = analysis_data["top10"]

    lines = [
        f"# AI 深度分析任务 — {nickname}",
        f"\n> 本文件由 deep_analyze.py 自动生成，供宿主 AI（WorkBuddy / Claude Code）参考",
        f"> 脚本已完成确定性分析（数据统计、模式匹配），以下是需要 AI 推理能力补充的部分",
        f"\n---",
        f"\n## 📋 AI 需要补充的内容",
        f"\n### 1. 博主深度拆解 — TOP10 逐条深度拆解",
        f"\n请基于以下 TOP10 笔记数据，为每条笔记写 2-3 句话的深度拆解，分析：",
        f"- 这条笔记为什么能成为爆款？",
        f"- 标题/内容/评论区有什么可复制的技巧？",
        f"- 对我（初期创作者）有什么可借鉴的？",
        f"\nTOP10 数据：\n",
    ]

    for i, n in enumerate(top10[:10]):
        lines.append(f"**{i+1}. {n['title']}**")
        lines.append(f"- 赞:{n['likes_raw']} 藏:{n['collects_raw']} 评:{n['comments_raw']} 类型:{n['type']}")
        desc = (n.get("desc", "") or "")[:200]
        if desc:
            lines.append(f"- 正文摘要: {desc}...")
        if n.get("comment_list"):
            lines.append(f"- 热评: {'; '.join(c['content'][:40] for c in n['comment_list'][:3])}")
        lines.append("")

    lines.extend([
        f"\n### 2. 内容公式总结 — 具体公式提炼",
        f"\n请基于标题模式和内容数据，提炼出 3-5 个具体的**可直接套用的标题公式**。",
        f'格式示例：「数字 + 痛点 + 解决方案」→ "3个方法让你XX"',
        f"\n### 3. 选题素材库 — 改编方向",
        f"\n请为 TOP10 每条选题提供一个**针对初期创作者**的改编方向。",
        f"重点考虑：创作难度低、不需要大量粉丝基础、能展示真实体验。",
        f"\n### 4. 全量结构化分析 — 竞争格局与机会",
        f"\n请基于该博主的内容领域分布，分析：",
        f"- 这个赛道的竞争态势",
        f"- 新人切入的机会点",
        f"- 建议的差异化方向",
    ])

    return "\n".join(lines)


# ----------------------------------------------------------
# 主函数
# ----------------------------------------------------------

def deep_analyze(analysis_path, nickname, output_dir, notes_details_path=None):
    """
    执行确定性深度分析，生成增强版文档 + AI Prompt。
    
    Returns:
        dict — { "docs": [...], "prompt_path": str }
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(analysis_path, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    stats = analysis["stats"]
    top10 = analysis["top10"]
    category_stats = analysis["category_stats"]
    tag_freq = analysis["tag_freq"]
    comparison = analysis.get("comparison")
    notes = analysis.get("notes", [])

    # 加载原始详情（如有）用于更深入分析
    full_notes = None
    if notes_details_path and os.path.exists(notes_details_path):
        with open(notes_details_path, "r", encoding="utf-8") as f:
            raw_details = json.load(f)
        full_notes = []
        for item in raw_details:
            if "_error" in item:
                continue
            note = item.get("data", {}).get("note", item)
            full_notes.append(note)

    # ---- 确定性分析 ----
    titles = [n["title"] for n in (notes or top10) if n.get("title")]
    descs = []
    if full_notes:
        descs = [n.get("desc", "") for n in full_notes]
    elif top10:
        descs = [n.get("desc", "") for n in top10]

    title_patterns = extract_title_patterns(titles) if titles else {}
    emoji_info = extract_emoji_patterns(descs) if descs else {}
    cta_info = extract_cta_patterns(descs) if descs else {}
    structure_info = analyze_content_structure(descs) if descs else {}
    frequency_info = detect_posting_frequency(notes) if notes else {}
    growth_info = find_growth_pattern(notes) if notes else None

    # ---- 新增：评论区情感分析 + 发布时间热力图 + 图片序列分析 ----
    sentiment_info = extract_comment_sentiment(raw_details) if raw_details else {}
    heatmap_info = extract_posting_heatmap(notes) if notes else {}
    image_info = extract_image_patterns(raw_details) if raw_details else {}

    safe_name = safe_filename(nickname)

    # ---- 生成增强版文档 ----
    docs = {
        "博主深度拆解": gen_enhanced_deep_analysis(
            nickname, stats, top10, category_stats, tag_freq,
            title_patterns, comparison, notes, sentiment_info, image_info
        ),
        "内容公式总结": gen_enhanced_content_formula(
            nickname, top10, category_stats, title_patterns,
            emoji_info, cta_info, structure_info, image_info
        ),
        "选题素材库": gen_enhanced_topic_library(
            nickname, top10, category_stats, tag_freq, notes
        ),
        "全量笔记结构化分析": gen_enhanced_structured_analysis(
            nickname, stats, notes or top10, category_stats, tag_freq,
            frequency_info, growth_info, sentiment_info, heatmap_info, image_info
        ),
    }

    # 过程文件目录
    process_dir = os.path.join(output_dir, "_过程文件", "原始素材")
    os.makedirs(process_dir, exist_ok=True)

    results = []
    for doc_type, md_content in docs.items():
        md_name = f"{safe_name}_{doc_type}.md"
        docx_name = f"{safe_name}_{doc_type}.docx"

        # MD → 过程文件
        md_path = os.path.join(process_dir, md_name)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        # DOCX → 根目录
        docx_path = os.path.join(output_dir, docx_name)
        try:
            md_to_docx(md_path, docx_path)
            size_kb = os.path.getsize(docx_path) / 1024
            print(f"  ✅ {docx_name} ({size_kb:.0f}KB)")
            results.append({"name": docx_name, "path": docx_path, "size_kb": size_kb, "ok": True})
        except Exception as e:
            print(f"  ❌ {docx_name}: {e}")
            results.append({"name": docx_name, "path": docx_path, "ok": False, "error": str(e)})

    # ---- 生成 AI Prompt ----
    prompt_content = gen_ai_prompt(nickname, analysis)
    prompt_path = os.path.join(process_dir, f"{safe_name}_AI深度分析Prompt.md")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt_content)
    print(f"  📋 AI Prompt: {prompt_path}")

    return {"docs": results, "prompt_path": prompt_path}


# ----------------------------------------------------------
# CLI
# ----------------------------------------------------------
if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Phase 3.5: AI 深度分析（增强版文档生成）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python deep_analyze.py ./data/analysis.json "蔡不菜"
  python deep_analyze.py ./data/analysis.json "蔡不菜" -o ./output
  python deep_analyze.py ./data/analysis.json "蔡不菜" -o ./output --details ./data/notes_details.json
        """,
    )
    parser.add_argument("analysis_path", help="分析数据JSON路径（Phase 2 输出）")
    parser.add_argument("nickname", help="博主昵称")
    parser.add_argument("-o", "--output", default=".", help="输出目录")
    parser.add_argument("--details", help="原始详情JSON路径（可选，提供更深入分析）")
    args = parser.parse_args()

    print(f"\n🔍 Phase 3.5: AI 深度分析 — {args.nickname}")
    print("=" * 50)
    print("  执行确定性分析（标题模式/CTA/Emoji/发布频率/发展趋势）...")
    print("  生成增强版文档（用数据洞察替换占位符）...")
    print()

    result = deep_analyze(args.analysis_path, args.nickname, args.output, args.details)

    ok = sum(1 for r in result["docs"] if r["ok"])
    print(f"\n完成: {ok}/{len(result['docs'])} 份增强版文档生成成功")
    print(f"\n💡 提示: 查看 {result['prompt_path']} 获取 AI 可补充的深度分析任务")
