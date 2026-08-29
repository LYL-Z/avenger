# -*- coding: utf-8 -*-
"""Avenger 工作室：备忘录、AI 接入（含流式）、编程练习、速查学习。仅标准库。"""
import json
import os
import re
import sqlite3
import ssl
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_NOTES_LOCK = threading.Lock()
_AI_LOCK = threading.Lock()

ALLOWED_AI_HOSTS = {
    "127.0.0.1", "localhost", "::1",
    "api.openai.com",
    "api.anthropic.com",
    "openrouter.ai",
    "api.deepseek.com",
    "api.siliconflow.cn",
    "dashscope.aliyuncs.com",
    "api.moonshot.cn",
    "api.groq.com",
    "api.mistral.ai",
    "generativelanguage.googleapis.com",
    "api.together.xyz",
    "api.cerebras.ai",
    "api.x.ai",
    "open.bigmodel.cn",
    "ark.cn-beijing.volces.com",
    "api.lingyiwanwu.com",
    "api.stepfun.com",
    "api.minimax.chat",
    "api.zhizengzeng.com",
}

# 全部为 OpenAI 兼容协议端点（本地 Ollama / LM Studio 亦兼容）
PRESET_PROVIDERS = [
    {"id": "ollama", "name": "Ollama 本地", "base_url": "http://127.0.0.1:11434/v1/chat/completions", "model": "llama3.2"},
    {"id": "lmstudio", "name": "LM Studio 本地", "base_url": "http://127.0.0.1:1234/v1/chat/completions", "model": "local-model"},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o-mini"},
    {"id": "anthropic", "name": "Claude (兼容网关)", "base_url": "https://api.anthropic.com/v1/chat/completions", "model": "claude-3-5-haiku-latest"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1/chat/completions", "model": "openai/gpt-4o-mini"},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"},
    {"id": "siliconflow", "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1/chat/completions", "model": "deepseek-ai/DeepSeek-V3"},
    {"id": "qwen", "name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "model": "qwen-plus"},
    {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4-flash"},
    {"id": "moonshot", "name": "Kimi / Moonshot", "base_url": "https://api.moonshot.cn/v1/chat/completions", "model": "moonshot-v1-8k"},
    {"id": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "model": "gemini-2.0-flash"},
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.1-8b-instant"},
    {"id": "xai", "name": "xAI Grok", "base_url": "https://api.x.ai/v1/chat/completions", "model": "grok-3-mini"},
    {"id": "cerebras", "name": "Cerebras", "base_url": "https://api.cerebras.ai/v1/chat/completions", "model": "llama3.1-8b"},
    {"id": "together", "name": "Together AI", "base_url": "https://api.together.xyz/v1/chat/completions", "model": "meta-llama/Llama-3-8b-chat-hf"},
    {"id": "mistral", "name": "Mistral", "base_url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
    {"id": "doubao", "name": "豆包 / 火山方舟", "base_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions", "model": "doubao-lite-32k"},
    {"id": "custom", "name": "自定义 OpenAI 兼容", "base_url": "", "model": ""},
]

AI_ROLES = [
    {"id": "default", "name": "默认助手", "prompt": "你是 Avenger 本地开发工作台内置的 AI 助手。回答简洁、准确，优先给可执行的命令或代码。"},
    {"id": "coder", "name": "代码专家", "prompt": "你是一位资深全栈工程师。回答以代码为中心，先给可直接运行的最小实现，再解释关键点；指出边界条件与常见坑。"},
    {"id": "arch", "name": "架构顾问", "prompt": "你是一位系统架构顾问。从权衡（trade-off）角度分析问题，给出 2-3 个方案、各自的适用场景与代价，最后给出推荐。"},
    {"id": "teacher", "name": "讲解老师", "prompt": "你是一位耐心的编程老师。用循序渐进的方式讲解概念，多用类比与小例子，最后给一道练习题帮助巩固。"},
    {"id": "interview", "name": "面试官", "prompt": "你是一位严格但友善的技术面试官。针对用户给出的答案追问复杂度、边界情况与优化空间，并按 1-5 分点评。"},
    {"id": "translator", "name": "中英互译", "prompt": "你是技术文档翻译。用户输入中文则译成地道英文，输入英文则译成流畅中文，保留代码与技术术语原文，不额外解释。"},
]

KATAS = [
    {
        "id": "fizzbuzz",
        "title": "FizzBuzz",
        "difficulty": "入门",
        "topic": "基础",
        "prompt": "返回 1..n 的列表：3 的倍数 'Fizz'，5 的倍数 'Buzz'，15 的倍数 'FizzBuzz'，其余为数字字符串。",
        "starter": "def fizz_buzz(n):\n    pass\n",
        "hidden": "assert fizz_buzz(5)==['1','2','Fizz','4','Buzz']\nassert fizz_buzz(15)[-1]=='FizzBuzz'\nassert fizz_buzz(1)==['1']\nprint('OK')\n",
    },
    {
        "id": "fib",
        "title": "斐波那契",
        "difficulty": "入门",
        "topic": "动态规划",
        "prompt": "返回第 n 个斐波那契数（f(0)=0, f(1)=1）。",
        "starter": "def fib(n):\n    pass\n",
        "hidden": "assert [fib(i) for i in range(8)]==[0,1,1,2,3,5,8,13]\nassert fib(20)==6765\nprint('OK')\n",
    },
    {
        "id": "two-sum",
        "title": "两数之和",
        "difficulty": "简单",
        "topic": "数组",
        "prompt": "给定整数列表 nums 与目标 target，返回两个相加等于 target 的下标。假设恰有一组解。",
        "starter": "def two_sum(nums, target):\n    # 返回 [i, j]\n    pass\n",
        "hidden": "assert two_sum([2,7,11,15], 9) in ([0,1],[1,0])\nassert two_sum([3,2,4], 6) in ([1,2],[2,1])\nassert two_sum([3,3], 6) in ([0,1],[1,0])\nprint('OK')\n",
    },
    {
        "id": "valid-parens",
        "title": "有效括号",
        "difficulty": "简单",
        "topic": "栈",
        "prompt": "判断字符串 s 是否由有效括号组成。仅包含 ()[]{}",
        "starter": "def is_valid(s):\n    pass\n",
        "hidden": "assert is_valid('()') is True\nassert is_valid('()[]{}') is True\nassert is_valid('(]') is False\nassert is_valid('([)]') is False\nassert is_valid('{[]}') is True\nprint('OK')\n",
    },
    {
        "id": "reverse-int",
        "title": "整数反转",
        "difficulty": "简单",
        "topic": "数学",
        "prompt": "将 32 位有符号整数 x 反转。溢出则返回 0。",
        "starter": "def reverse(x):\n    pass\n",
        "hidden": "assert reverse(123)==321\nassert reverse(-123)==-321\nassert reverse(120)==21\nassert reverse(0)==0\nprint('OK')\n",
    },
    {
        "id": "anagram",
        "title": "有效字母异位词",
        "difficulty": "简单",
        "topic": "哈希",
        "prompt": "判断 t 是否为 s 的字母异位词。",
        "starter": "def is_anagram(s, t):\n    pass\n",
        "hidden": "assert is_anagram('anagram','nagaram') is True\nassert is_anagram('rat','car') is False\nassert is_anagram('','') is True\nprint('OK')\n",
    },
    {
        "id": "binary-search",
        "title": "二分查找",
        "difficulty": "简单",
        "topic": "二分",
        "prompt": "在升序 nums 中找 target 的下标，不存在返回 -1。",
        "starter": "def search(nums, target):\n    pass\n",
        "hidden": "assert search([-1,0,3,5,9,12], 9)==4\nassert search([-1,0,3,5,9,12], 2)==-1\nassert search([5], 5)==0\nprint('OK')\n",
    },
    {
        "id": "climb-stairs",
        "title": "爬楼梯",
        "difficulty": "简单",
        "topic": "动态规划",
        "prompt": "一次 1 或 2 阶，爬 n 阶有多少种方法。",
        "starter": "def climb_stairs(n):\n    pass\n",
        "hidden": "assert climb_stairs(2)==2\nassert climb_stairs(3)==3\nassert climb_stairs(1)==1\nassert climb_stairs(5)==8\nprint('OK')\n",
    },
    {
        "id": "contains-dup",
        "title": "存在重复元素",
        "difficulty": "简单",
        "topic": "哈希",
        "prompt": "判断列表 nums 中是否存在重复值，存在返回 True。",
        "starter": "def contains_duplicate(nums):\n    pass\n",
        "hidden": "assert contains_duplicate([1,2,3,1]) is True\nassert contains_duplicate([1,2,3,4]) is False\nassert contains_duplicate([]) is False\nprint('OK')\n",
    },
    {
        "id": "move-zeroes",
        "title": "移动零",
        "difficulty": "简单",
        "topic": "双指针",
        "prompt": "将列表中所有 0 移到末尾，保持非零元素相对顺序。请就地修改并返回该列表。",
        "starter": "def move_zeroes(nums):\n    # 就地修改，返回 nums\n    pass\n",
        "hidden": "assert move_zeroes([0,1,0,3,12])==[1,3,12,0,0]\nassert move_zeroes([0])==[0]\nassert move_zeroes([1])==[1]\nprint('OK')\n",
    },
    {
        "id": "max-profit",
        "title": "买卖股票最佳时机",
        "difficulty": "简单",
        "topic": "贪心",
        "prompt": "prices[i] 是第 i 天股价。只买一次卖一次，求最大利润；无利润返回 0。",
        "starter": "def max_profit(prices):\n    pass\n",
        "hidden": "assert max_profit([7,1,5,3,6,4])==5\nassert max_profit([7,6,4,3,1])==0\nassert max_profit([2,4,1])==2\nprint('OK')\n",
    },
    {
        "id": "single-number",
        "title": "只出现一次的数字",
        "difficulty": "简单",
        "topic": "位运算",
        "prompt": "非空列表中只有一个元素出现一次，其余都出现两次，找出它。",
        "starter": "def single_number(nums):\n    pass\n",
        "hidden": "assert single_number([2,2,1])==1\nassert single_number([4,1,2,1,2])==4\nassert single_number([7])==7\nprint('OK')\n",
    },
    {
        "id": "missing-number",
        "title": "丢失的数字",
        "difficulty": "简单",
        "topic": "数学",
        "prompt": "列表含 [0..n] 中缺一个的 n 个数，找出缺的那个。",
        "starter": "def missing_number(nums):\n    pass\n",
        "hidden": "assert missing_number([3,0,1])==2\nassert missing_number([0,1])==2\nassert missing_number([9,6,4,2,3,5,7,0,1])==8\nprint('OK')\n",
    },
    {
        "id": "plus-one",
        "title": "加一",
        "difficulty": "简单",
        "topic": "数组",
        "prompt": "非负整数按位存入列表（最高位在前），给它加一，返回结果列表。",
        "starter": "def plus_one(digits):\n    pass\n",
        "hidden": "assert plus_one([1,2,3])==[1,2,4]\nassert plus_one([9])==[1,0]\nassert plus_one([9,9])==[1,0,0]\nprint('OK')\n",
    },
    {
        "id": "roman-to-int",
        "title": "罗马数字转整数",
        "difficulty": "简单",
        "topic": "哈希",
        "prompt": "把罗马数字字符串转成整数。I=1 V=5 X=10 L=50 C=100 D=500 M=1000，小值在大值左侧时做减法。",
        "starter": "def roman_to_int(s):\n    pass\n",
        "hidden": "assert roman_to_int('III')==3\nassert roman_to_int('IV')==4\nassert roman_to_int('IX')==9\nassert roman_to_int('LVIII')==58\nassert roman_to_int('MCMXCIV')==1994\nprint('OK')\n",
    },
    {
        "id": "is-palindrome",
        "title": "回文串判断",
        "difficulty": "简单",
        "topic": "双指针",
        "prompt": "判断字符串 s 是否为回文（忽略大小写与非字母数字）。",
        "starter": "def is_palindrome(s):\n    pass\n",
        "hidden": "assert is_palindrome('A man, a plan, a canal: Panama') is True\nassert is_palindrome('race a car') is False\nassert is_palindrome(' ') is True\nprint('OK')\n",
    },
    {
        "id": "power-of-three",
        "title": "3 的幂",
        "difficulty": "简单",
        "topic": "数学",
        "prompt": "判断整数 n 是否为 3 的幂。",
        "starter": "def is_power_of_three(n):\n    pass\n",
        "hidden": "assert is_power_of_three(27) is True\nassert is_power_of_three(0) is False\nassert is_power_of_three(9) is True\nassert is_power_of_three(45) is False\nprint('OK')\n",
    },
    {
        "id": "max-subarray",
        "title": "最大子数组和",
        "difficulty": "中等",
        "topic": "动态规划",
        "prompt": "求连续子数组的最大和（Kadane）。",
        "starter": "def max_sub_array(nums):\n    pass\n",
        "hidden": "assert max_sub_array([-2,1,-3,4,-1,2,1,-5,4])==6\nassert max_sub_array([1])==1\nassert max_sub_array([5,4,-1,7,8])==23\nprint('OK')\n",
    },
    {
        "id": "longest-unique",
        "title": "无重复最长子串",
        "difficulty": "中等",
        "topic": "滑动窗口",
        "prompt": "返回字符串 s 中不含重复字符的最长子串长度。",
        "starter": "def length_of_longest_substring(s):\n    pass\n",
        "hidden": "assert length_of_longest_substring('abcabcbb')==3\nassert length_of_longest_substring('bbbbb')==1\nassert length_of_longest_substring('pwwkew')==3\nassert length_of_longest_substring('')==0\nprint('OK')\n",
    },
    {
        "id": "merge-intervals",
        "title": "合并区间",
        "difficulty": "中等",
        "topic": "排序",
        "prompt": "合并重叠区间。输入 [[s,e],...] 返回合并后的列表。",
        "starter": "def merge(intervals):\n    pass\n",
        "hidden": "assert merge([[1,3],[2,6],[8,10],[15,18]])==[[1,6],[8,10],[15,18]]\nassert merge([[1,4],[4,5]])==[[1,5]]\nprint('OK')\n",
    },
    {
        "id": "group-anagrams",
        "title": "字母异位词分组",
        "difficulty": "中等",
        "topic": "哈希",
        "prompt": "把字母异位词分到同一组，返回分组列表（每元素为排序后的组，组内按字母序）。",
        "starter": "def group_anagrams(strs):\n    # 返回 [[...], [...]] 形式即可\n    pass\n",
        "hidden": "r=group_anagrams(['eat','tea','tan','ate','nat','bat'])\nassert sorted([sorted(g) for g in r])==sorted([sorted(g) for g in [['eat','tea','ate'],['tan','nat'],['bat']]])\nassert group_anagrams([''])==[['']]\nprint('OK')\n",
    },
    {
        "id": "product-except-self",
        "title": "除自身以外数组乘积",
        "difficulty": "中等",
        "topic": "前缀和",
        "prompt": "返回列表 answer，answer[i] 为 nums 中除 nums[i] 外所有元素乘积。不使用除法。",
        "starter": "def product_except_self(nums):\n    pass\n",
        "hidden": "assert product_except_self([1,2,3,4])==[24,12,8,6]\nassert product_except_self([-1,1,0,-3,3])==[0,0,9,0,0]\nprint('OK')\n",
    },
    {
        "id": "container-water",
        "title": "盛最多水的容器",
        "difficulty": "中等",
        "topic": "双指针",
        "prompt": "height[i] 为竖线高度，选两条线与 x 轴构成容器，求最大水量。",
        "starter": "def max_area(height):\n    pass\n",
        "hidden": "assert max_area([1,8,6,2,5,4,8,3,7])==49\nassert max_area([1,1])==1\nassert max_area([4,3,2,1,4])==16\nprint('OK')\n",
    },
    {
        "id": "coin-change",
        "title": "零钱兑换",
        "difficulty": "中等",
        "topic": "动态规划",
        "prompt": "给定硬币面额 coins 与金额 amount，求凑出 amount 的最少硬币数；凑不出返回 -1。",
        "starter": "def coin_change(coins, amount):\n    pass\n",
        "hidden": "assert coin_change([1,2,5],11)==3\nassert coin_change([2],3)==-1\nassert coin_change([1],0)==0\nassert coin_change([1,5,6,9],11)==2\nprint('OK')\n",
    },
    {
        "id": "min-stack",
        "title": "最小栈",
        "difficulty": "中等",
        "topic": "设计",
        "prompt": "实现 MinStack 类：push(x)、pop()、top()、get_min()，均 O(1)（get_min 可内部实现）。",
        "starter": "class MinStack:\n    def __init__(self):\n        pass\n    def push(self, x):\n        pass\n    def pop(self):\n        pass\n    def top(self):\n        pass\n    def get_min(self):\n        pass\n",
        "hidden": "s=MinStack()\ns.push(-2); s.push(0); s.push(-3)\nassert s.get_min()==-3\ns.pop()\nassert s.top()==0\nassert s.get_min()==-2\nprint('OK')\n",
    },
    {
        "id": "lru-cache",
        "title": "LRU 缓存",
        "difficulty": "困难",
        "topic": "设计",
        "prompt": "实现 LRUCache(capacity)：get(key) 不存在返回 -1；put(key,value) 超容量时淘汰最久未使用。",
        "starter": "class LRUCache:\n    def __init__(self, capacity):\n        pass\n    def get(self, key):\n        pass\n    def put(self, key, value):\n        pass\n",
        "hidden": "c=LRUCache(2)\nc.put(1,1); c.put(2,2)\nassert c.get(1)==1\nc.put(3,3)\nassert c.get(2)==-1\nc.put(3,4)\nassert c.get(1)==-1\nassert c.get(3)==4\nprint('OK')\n",
    },
]


def notes_db(base_dir):
    path = Path(base_dir) / "avenger_notes.db"
    conn = sqlite3.connect(str(path), timeout=8)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notes("
        "id TEXT PRIMARY KEY, title TEXT, body TEXT, tags TEXT, pinned INTEGER, updated TEXT)"
    )
    conn.commit()
    return conn


def notes_list(base_dir):
    with _NOTES_LOCK:
        conn = notes_db(base_dir)
        rows = conn.execute(
            "SELECT id,title,body,tags,pinned,updated FROM notes ORDER BY pinned DESC, updated DESC"
        ).fetchall()
        conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "title": r[1] or "", "body": r[2] or "",
            "tags": r[3] or "", "pinned": bool(r[4]), "updated": r[5] or "",
        })
    return out


def notes_save(base_dir, body):
    nid = (body.get("id") or "").strip() or uuid.uuid4().hex[:12]
    title = (body.get("title") or "无标题")[:200]
    text = (body.get("body") or "")[:100000]
    tags = (body.get("tags") or "")[:200]
    pinned = 1 if body.get("pinned") else 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _NOTES_LOCK:
        conn = notes_db(base_dir)
        conn.execute(
            "INSERT OR REPLACE INTO notes(id,title,body,tags,pinned,updated) VALUES(?,?,?,?,?,?)",
            (nid, title, text, tags, pinned, now),
        )
        conn.commit()
        conn.close()
    return {"ok": True, "id": nid, "updated": now}


def notes_delete(base_dir, nid):
    with _NOTES_LOCK:
        conn = notes_db(base_dir)
        conn.execute("DELETE FROM notes WHERE id=?", (nid,))
        conn.commit()
        conn.close()
    return {"ok": True}


def secrets_path(base_dir):
    return Path(base_dir) / "avenger_secrets.json"


def load_secrets(base_dir):
    p = secrets_path(base_dir)
    if not p.exists():
        return {"keys": {}, "active": "ollama", "custom_url": "", "custom_model": "", "models": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"keys": {}, "active": "ollama", "custom_url": "", "custom_model": "", "models": {}}


def save_secrets(base_dir, data):
    p = secrets_path(base_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def ai_public_config(base_dir):
    sec = load_secrets(base_dir)
    keys = sec.get("keys") or {}
    models = sec.get("models") or {}
    providers = []
    for p in PRESET_PROVIDERS:
        item = dict(p)
        if p["id"] == "custom":
            item["base_url"] = sec.get("custom_url") or ""
            item["model"] = sec.get("custom_model") or ""
        if p["id"] in models:
            item["model"] = models[p["id"]]
        item["has_key"] = bool(keys.get(p["id"]))
        providers.append(item)
    return {
        "providers": providers,
        "active": sec.get("active") or "ollama",
        "roles": AI_ROLES,
    }


def ai_save_config(base_dir, body):
    sec = load_secrets(base_dir)
    pid = (body.get("id") or "").strip()
    allowed_ids = {p["id"] for p in PRESET_PROVIDERS}
    if pid not in allowed_ids:
        return {"ok": False, "error": "未知供应商"}
    if "key" in body:
        key = (body.get("key") or "").strip()
        keys = sec.setdefault("keys", {})
        if key:
            keys[pid] = key
        elif body.get("clear"):
            keys.pop(pid, None)
    if "model" in body and body.get("model") is not None:
        sec.setdefault("models", {})[pid] = str(body.get("model") or "")[:120]
    if pid == "custom":
        if "base_url" in body:
            sec["custom_url"] = str(body.get("base_url") or "")[:400]
        if "model" in body:
            sec["custom_model"] = str(body.get("model") or "")[:120]
    if body.get("active"):
        sec["active"] = pid
    save_secrets(base_dir, sec)
    return {"ok": True, "config": ai_public_config(base_dir)}


def _host_allowed(hostname):
    h = (hostname or "").lower().rstrip(".")
    if h in ALLOWED_AI_HOSTS:
        return True
    for allowed in ALLOWED_AI_HOSTS:
        if "." in allowed and (h == allowed or h.endswith("." + allowed)):
            return True
    return False


def ai_url_allowed(url):
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    if host in ("127.0.0.1", "localhost", "::1"):
        return p.scheme in ("http", "https")
    if p.scheme != "https":
        return False
    return _host_allowed(host)


def _build_ai_request(base_dir, body):
    """公共校验 + 构造 (url, payload_bytes, headers, pid, model)。校验失败抛 ValueError。"""
    sec = load_secrets(base_dir)
    pid = (body.get("provider") or sec.get("active") or "ollama").strip()
    preset = next((p for p in PRESET_PROVIDERS if p["id"] == pid), None)
    if not preset:
        raise ValueError("未知供应商")
    url = preset["base_url"]
    model = (sec.get("models") or {}).get(pid) or preset["model"]
    if pid == "custom":
        url = (sec.get("custom_url") or body.get("base_url") or "").strip()
        model = (sec.get("custom_model") or body.get("model") or "").strip()
    if body.get("model"):
        model = str(body.get("model")).strip()[:120]
    if not url or not ai_url_allowed(url):
        raise ValueError("接口地址不被允许。仅本机或已登记的 HTTPS 供应商。")
    if not model:
        raise ValueError("请填写模型名")
    messages = body.get("messages") or []
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages 不能为空")
    clean = []
    system = str(body.get("system") or "")[:2000].strip()
    if system:
        clean.append({"role": "system", "content": system})
    for m in messages[-24:]:
        if not isinstance(m, dict):
            continue
        role = m.get("role") if m.get("role") in ("system", "user", "assistant") else "user"
        content = str(m.get("content") or "")[:12000]
        clean.append({"role": role, "content": content})
    if not clean:
        raise ValueError("没有有效消息")
    try:
        temperature = min(max(float(body.get("temperature") or 0.4), 0), 1.5)
    except (TypeError, ValueError):
        temperature = 0.4
    try:
        max_tokens = min(int(body.get("max_tokens") or 1024), 8192)
    except (TypeError, ValueError):
        max_tokens = 1024
    return url, model, clean, temperature, max_tokens, pid


def ai_chat(base_dir, body, log_op=None):
    try:
        url, model, clean, temperature, max_tokens, pid = _build_ai_request(base_dir, body)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    payload = json.dumps({
        "model": model,
        "messages": clean,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Avenger/4.0",
        "Accept": "application/json",
    }
    key = (load_secrets(base_dir).get("keys") or {}).get(pid) or (body.get("key") or "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    req = Request(url, data=payload, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    opener = build_opener(HTTPSHandler(context=ctx), _NoRedirect)
    try:
        with opener.open(req, timeout=90) as resp:
            raw = resp.read(2 * 1024 * 1024)
            data = json.loads(raw.decode("utf-8", "replace"))
    except HTTPError as e:
        err = e.read()[:800].decode("utf-8", "replace") if e.fp else str(e)
        return {"ok": False, "error": "供应商返回 %s: %s" % (e.code, err[:400])}
    except URLError as e:
        return {"ok": False, "error": "无法连接供应商：%s" % e.reason}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    text = ""
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except Exception:
        text = data.get("message", {}).get("content") or json.dumps(data, ensure_ascii=False)[:2000]
    if log_op:
        log_op("AI 对话 · %s · %s" % (pid, model))
    return {"ok": True, "content": text, "provider": pid, "model": model,
            "usage": (data.get("usage") or {}) if isinstance(data, dict) else {}}


def ai_chat_stream(base_dir, body, log_op=None):
    """生成器：逐段产出 AI 文本。协议错误直接抛 ValueError，网络错误 yield 错误说明。"""
    try:
        url, model, clean, temperature, max_tokens, pid = _build_ai_request(base_dir, body)
    except ValueError as e:
        raise ValueError(str(e))
    payload = json.dumps({
        "model": model,
        "messages": clean,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Avenger/4.0",
        "Accept": "text/event-stream",
    }
    key = (load_secrets(base_dir).get("keys") or {}).get(pid) or (body.get("key") or "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    req = Request(url, data=payload, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    opener = build_opener(HTTPSHandler(context=ctx), _NoRedirect)
    got_any = False
    try:
        with opener.open(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if line.startswith("event:") or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        obj = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("error"):
                        msg = obj["error"].get("message") if isinstance(obj["error"], dict) else str(obj["error"])
                        if not got_any:
                            raise ValueError("供应商流式错误: %s" % msg)
                        yield "\n[流中断] %s" % msg
                        return
                    piece = ""
                    try:
                        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                        piece = delta.get("content") or ""
                        if not piece:
                            piece = (obj.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                    except Exception:
                        piece = ""
                    if piece:
                        got_any = True
                        yield piece
                else:
                    # 某些供应商关闭流式时直接回 JSON
                    try:
                        obj = json.loads(line)
                        piece = (obj.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                        if piece:
                            got_any = True
                            yield piece
                            break
                    except json.JSONDecodeError:
                        continue
    except ValueError:
        raise
    except HTTPError as e:
        err = e.read()[:600].decode("utf-8", "replace") if e.fp else str(e)
        raise ValueError("供应商返回 %s: %s" % (e.code, err[:300]))
    except URLError as e:
        raise ValueError("无法连接供应商：%s" % e.reason)
    except Exception as e:
        if got_any:
            yield "\n[连接中断] %s" % str(e)[:200]
            return
        raise ValueError(str(e)[:300])
    if not got_any:
        raise ValueError("供应商未返回内容（检查模型名 / Key / 是否支持流式）")
    if log_op:
        log_op("AI 流式对话 · %s · %s" % (pid, model))


def ai_test(base_dir, body):
    """用一句 ping 验证接入配置，返回时延。"""
    t0 = time.time()
    r = ai_chat(base_dir, {
        "provider": body.get("provider"),
        "model": body.get("model"),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "temperature": 0,
    })
    ms = int((time.time() - t0) * 1000)
    if r.get("ok"):
        return {"ok": True, "latency_ms": ms, "reply": (r.get("content") or "")[:80]}
    return {"ok": False, "error": r.get("error"), "latency_ms": ms}


def kata_list():
    return [{k: v[k] for k in ("id", "title", "difficulty", "topic", "prompt", "starter")} for v in KATAS]


def kata_run(python_exe, kata_id, code):
    kata = next((k for k in KATAS if k["id"] == kata_id), None)
    if not kata:
        return {"ok": False, "error": "未知题目"}
    src = (code or "")[:40000]
    if "\x00" in src:
        return {"ok": False, "error": "非法代码"}
    blob = src + "\n\n" + kata["hidden"]
    fd, path = tempfile.mkstemp(suffix=".py", prefix="avenger_kata_")
    os.close(fd)
    try:
        Path(path).write_text(blob, encoding="utf-8")
        import subprocess
        exe = python_exe or "python"
        rc, out, err = 0, "", ""
        try:
            kw = {"capture_output": True, "text": True, "timeout": 8, "cwd": tempfile.gettempdir()}
            if os.name == "nt":
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            p = subprocess.run([exe, "-I", path], **kw)
            rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
        except subprocess.TimeoutExpired:
            return {"ok": False, "passed": False, "error": "超时（8 秒）", "stdout": "", "stderr": ""}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        passed = rc == 0 and "OK" in (out or "")
        return {
            "ok": True,
            "passed": passed,
            "returncode": rc,
            "stdout": out[-4000:],
            "stderr": err[-4000:],
        }
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


CHEATSHEETS = [
    {
        "id": "git",
        "title": "Git 速查",
        "body": "git status\ngit add -p\ngit commit -m \"msg\"\ngit log --oneline -12\ngit switch -c feature/x\ngit rebase -i HEAD~3\ngit stash -u\ngit restore --staged FILE\ngit diff --cached\ngit remote -v\ngit cherry-pick <sha>\ngit bisect start\ngit blame -L 10,20 FILE\ngit worktree add ../hotfix hotfix",
    },
    {
        "id": "pip",
        "title": "pip / venv 速查",
        "body": "python -m venv .venv\n.venv\\Scripts\\activate\npython -m pip install -U pip\npip install pkg==1.2.3\npip freeze > requirements.txt\npip install -r requirements.txt\npip cache dir\npip cache purge\npython -m pip uninstall pkg -y\npip list --outdated\npip show pkg\npip download -d wheels/ pkg",
    },
    {
        "id": "regex",
        "title": "正则速查",
        "body": ". 任意字符   \\d 数字   \\w 单词   \\s 空白\n^ $ 行首行尾   \\b 词边界\n* + ? {n,m} 量词\n(?: ) 非捕获   (?P<name> ) 命名组\n(?= ) 前瞻   (?<= ) 后顾\n[abc] 字符类   [^abc] 取反\nflag: i 忽略大小写  m 多行  s 点匹配换行",
    },
    {
        "id": "http",
        "title": "HTTP 状态码",
        "body": "200 OK  201 Created  204 No Content\n301/302 重定向  304 Not Modified\n400 坏请求  401 未认证  403 禁止  404 未找到  409 冲突  429 限流\n500 服务器错  502 网关  503 不可用  504 超时\nGET 安全幂等  POST 非幂等  PUT/DELETE 幂等  PATCH 部分更新",
    },
    {
        "id": "sql",
        "title": "SQL 速查",
        "body": "SELECT a, COUNT(*) FROM t WHERE x = 1 GROUP BY a HAVING COUNT(*) > 2 ORDER BY 2 DESC;\nJOIN ... ON  LEFT JOIN  UNION ALL\nINSERT INTO t(a,b) VALUES(1,2);\nUPDATE t SET a=1 WHERE id=?; DELETE FROM t WHERE id=?;\nCREATE INDEX idx_t_a ON t(a);\nEXPLAIN QUERY PLAN ...",
    },
    {
        "id": "sql-window",
        "title": "SQL 窗口函数",
        "body": "ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) -- 组内排名\nRANK() / DENSE_RANK() -- 有并列的排名\nSUM(amount) OVER (ORDER BY dt ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) -- 7日滑动和\nLAG(sales, 1) OVER (ORDER BY dt) -- 上一天的值\nFIRST_VALUE() / NTILE(4)",
    },
    {
        "id": "linux",
        "title": "常用命令",
        "body": "ls -la  cd  pwd  cat  less  rg/grep  find\nps  tasklist  netstat -ano  curl -I\nchmod  chown  tar -xzf  ssh  scp\npython -m http.server 8000\necho %PATH%   setx（谨慎）\ndu -sh *  df -h  watch -n1 nvidia-smi",
    },
    {
        "id": "pydebug",
        "title": "Python 调试",
        "body": "python -m pdb script.py\nbreakpoint()  # 3.7+\npython -X dev script.py\npython -m py_compile file.py\npython -m venv .venv --upgrade-deps\npython -c \"import sys; print(sys.executable)\"\npython -m timeit \"sum(range(100))\"\nimport dis; dis.func = None  # dis.dis(fn) 看字节码",
    },
    {
        "id": "httpie",
        "title": "curl 配方",
        "body": "curl -I https://example.com\ncurl -X POST http://127.0.0.1:8765/api/x -H \"Content-Type: application/json\" -d \"{}\"\ncurl -o out.bin URL\ncurl -w \"%{http_code} %{time_total}\\n\" -o NUL -s URL\ncurl -H \"Authorization: Bearer $TOKEN\" URL\ncurl --retry 3 --retry-delay 1 -sSL URL",
    },
    {
        "id": "docker",
        "title": "Docker 速查",
        "body": "docker ps -a\ndocker images\ndocker run -d --name web -p 8080:80 nginx\ndocker logs -f --tail 100 web\ndocker exec -it web sh\ndocker build -t app:dev .\ndocker compose up -d\ndocker system df\ndocker system prune -a（谨慎）\ndocker cp FILE web:/app/",
    },
    {
        "id": "powershell",
        "title": "PowerShell 速查",
        "body": "Get-Process | Sort-Object CPU -Desc | Select -First 10\nGet-NetTCPConnection -State Listen\nGet-ChildItem -Recurse -Filter *.py | Measure-Object\nGet-Content log.txt -Tail 50 -Wait\ne \"$env:USERNAME@$env:COMPUTERNAME\"\nGet-CimInstance Win32_Processor | Select Name,LoadPercentage\nSet-ExecutionPolicy -Scope CurrentUser RemoteSigned",
    },
    {
        "id": "py-idioms",
        "title": "Python 惯用法",
        "body": "a, b = b, a\nwith open(p, encoding='utf-8') as f: ...\n{x*2 for x in items if x > 0}\nfirst, *rest = seq\nfrom collections import Counter, defaultdict, deque\nfrom functools import lru_cache\n@contextlib.contextmanager\ndataclass(frozen=True, slots=True)\nmatch cmd:  # 3.10+\n    case 'go' | 'run': ...",
    },
    {
        "id": "asyncio",
        "title": "asyncio 速查",
        "body": "async def main(): await asyncio.sleep(1)\nasyncio.run(main())\nawait asyncio.gather(*tasks, return_exceptions=True)\nasync with asyncio.timeout(5): ...  # 3.11+\nasync for chunk in resp:\nasync with aiofiles.open(p) as f: ...  # 第三方\nsem = asyncio.Semaphore(8)  # 并发限流\nawait asyncio.to_thread(blocking_fn)  # 线程池跑同步",
    },
    {
        "id": "js-es6",
        "title": "JS / ES2023 速查",
        "body": "const {a, ...rest} = obj\narr.flatMap(x => [x, x*2])\n[...new Set(arr)]  # 去重\nstructuredClone(obj)\nPromise.allSettled([...])\narr.at(-1)  # 末位\nx ?? 'default';  a?.b?.c\nfor await (const c of stream) {}\nqueueMicrotask(fn)\nArray.from({length:5}, (_,i)=>i)",
    },
    {
        "id": "css-layout",
        "title": "CSS 布局速查",
        "body": "display:flex; gap:12px; align-items:center; justify-content:space-between\nflex:1 1 0; min-width:0  # 防溢出\ndisplay:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr))\ngrid-area / grid-template-areas\nposition:sticky; top:0\nbackdrop-filter:blur(20px) saturate(180%)\ncontainer-type:inline-size  # 容器查询\nclamp(14px, 2vw, 20px)",
    },
    {
        "id": "regex-cookbook",
        "title": "正则小抄本",
        "body": "IP: ((25[0-5]|2[0-4]\\d|1?\\d?\\d)\\.){3}(25[0-5]|2[0-4]\\d|1?\\d?\\d)\n邮箱: [\\w.+-]+@[\\w-]+\\.[\\w.]+\nURL: https?://[^\\s)\"']+\n中文: [\\u4e00-\\u9fa5]\n重复词: \\b(\\w+)\\s+\\1\\b  → 替换 $1\n千分位: (?<=\\d)(?=(\\d{3})+$) → ,\n空行: ^\\s*$\\n? → ''\n跨行匹配: re.findall(r'(?s)BEGIN(.*?)END', text)",
    },
    {
        "id": "vim",
        "title": "Vim 生存包",
        "body": "i a o  插入；Esc 回普通\n:w  :q  :wq  :q!\ndd yy p  行剪切/复制/粘贴\nu Ctrl-r  撤销/重做\ngg G 0 $ w b  移动\n/word n N  搜索\n:%s/old/new/g  全文替换\nvisual: v V Ctrl-v\nci( di\" yi[  文本对象\n:e!  放弃修改",
    },
    {
        "id": "node-npm",
        "title": "Node / npm 速查",
        "body": "node --watch app.js\nnpm init -y\nnpm i pkg / npm i -D pkg\nnpm run dev / npm test\nnpx create-vite@latest\nnpm outdated / npm update\nnpm ci  # 按 lock 精确安装\nnpm view pkg versions --json\nnode -e \"console.log(process.version)\"\npackage.json: \"type\":\"module\"",
    },
]
