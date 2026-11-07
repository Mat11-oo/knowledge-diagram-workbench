# -*- coding: utf-8 -*-
"""
统一提示词加载器

提示词文件位于 prompts/<category>/<name>_<lang>.txt。
场景包可以在自己的 prompts/ 目录下放同名文件来覆盖默认提示词：
传入 search_dirs 后，会先在这些目录中查找，找不到再回退到默认目录。
"""

import os
from typing import Iterable, List, Optional

# 默认提示词目录 (loader.py 就在 backend/prompts/ 下)
PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _candidate_files(category: str, name: str, langs: List[str]) -> List[str]:
    files = [os.path.join(category, f"{name}_{lang}.txt") for lang in langs]
    files.append(os.path.join(category, f"{name}.txt"))
    return files


def find_prompt_file(
    category: str,
    name: str,
    lang: str = 'zh',
    fallback_lang: str = 'zh',
    search_dirs: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """
    返回提示词文件路径；找不到时返回 None。

    查找顺序：每个 search_dirs（场景包覆盖）→ 默认 PROMPTS_DIR；
    每个目录内按 {name}_{lang} → {name}_{fallback_lang} → {name} 的顺序查找。
    """
    langs = [lang] if fallback_lang == lang else [lang, fallback_lang]
    for base in [*(search_dirs or []), PROMPTS_DIR]:
        for rel in _candidate_files(category, name, langs):
            path = os.path.join(base, rel)
            if os.path.exists(path):
                return path
    return None


def load_prompt_with_fallback(
    category: str,
    name: str,
    lang: str = 'zh',
    fallback_lang: str = 'zh',
    search_dirs: Optional[Iterable[str]] = None,
) -> str:
    """
    加载提示词，首选语言不存在时回退到 fallback_lang，再回退到不带语言后缀的版本。

    Args:
        category: 提示词分类 (script, character, setting, storyboard, reference, video, style ...)
        name: 提示词文件名 (不含语言后缀和扩展名)
        lang: 首选语言
        fallback_lang: 回退语言
        search_dirs: 优先查找的目录（场景包的 prompts/ 目录）
    """
    path = find_prompt_file(category, name, lang, fallback_lang, search_dirs)
    if not path:
        raise FileNotFoundError(f"Prompt not found: {category}/{name}_{lang}.txt or {category}/{name}.txt")
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()


def load_prompt(category: str, name: str, lang: str = 'zh', search_dirs: Optional[Iterable[str]] = None) -> str:
    """
    加载提示词文件，lang 版本不存在时回退到 _zh 版本。

    Example:
        prompt = load_prompt('script', 'generate_script', 'zh')
    """
    return load_prompt_with_fallback(category, name, lang, 'zh', search_dirs)


def format_prompt(template: str, **kwargs) -> str:
    """
    格式化提示词模板

    Example:
        prompt = format_prompt("Hello {name}, you are {age} years old", name="John", age=30)
    """
    return template.format(**kwargs)
