import os
from dataclasses import dataclass


def flag(name, default):
    value = os.getenv(name, str(default)).lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ValueError(f'Invalid boolean: {name}')
    return value in {'true', '1'}


@dataclass
class Config:
    enable_feishu: bool = True
    enable_zotero: bool = True
    enable_ai_notes: bool = False
    enable_persistence: bool = False
    dry_run: bool = False
    zotero_key: str = ''
    zotero_user: str = ''
    collection: str = '自动收录'
    webhook: str = ''
    ai_key: str = ''
    ai_model: str = 'deepseek-chat'
    max_daily: int = 3

    @classmethod
    def from_env(cls, dry_run=False):
        config = cls(
            enable_feishu=flag('ENABLE_FEISHU', True),
            enable_zotero=flag('ENABLE_ZOTERO', True),
            enable_ai_notes=flag('ENABLE_AI_NOTES', False), dry_run=dry_run,
            enable_persistence=flag('ENABLE_PERSISTENCE', False),
            zotero_key=os.getenv('ZOTERO_API_KEY', ''), zotero_user=os.getenv('ZOTERO_USER_ID', ''),
            collection=os.getenv('ZOTERO_COLLECTION', '自动收录'),
            webhook=os.getenv('FEISHU_WEBHOOK', ''), ai_key=os.getenv('DEEPSEEK_API_KEY', ''),
            ai_model=os.getenv('AI_MODEL', 'deepseek-chat'),
            max_daily=int(os.getenv('MAX_DAILY_PUSH', '3')))
        if config.max_daily < 1 or not config.collection.strip():
            raise ValueError('Invalid limit or collection')
        if not dry_run:
            required = []
            if config.enable_feishu:
                required.append(config.webhook)
            if config.enable_zotero:
                required.extend([config.zotero_key, config.zotero_user])
            if config.enable_feishu or config.enable_zotero:
                required.append(config.ai_key)
            if any(not value for value in required):
                raise ValueError('Missing enabled-service credentials')
        return config
