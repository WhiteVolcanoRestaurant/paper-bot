import logging
from html import escape
import requests
from paperbot.arxiv import parse_id
from paperbot.ai import FIELDS
from paperbot.http import read

log = logging.getLogger(__name__)
OWNER_TAG = 'paper-bot:ai-preview:v1'
OWNER_MARK = 'paper-bot managed AI preview; schema=1'


def item_identity(item):
    data = item.get('data', item)
    for field in ('extra', 'url', 'DOI', 'archiveLocation'):
        pid, _ = parse_id(data.get(field))
        if pid:
            return pid
    return None


def note_html(record):
    paper, result = record['paper'], record['ai']
    e = lambda value: escape(str(value), quote=True)
    parts = [f'<p>{OWNER_MARK}</p>', '<h1>AI 预览｜基于摘要</h1>', f'<h2>{e(paper["title"])}</h2>',
             f'<p>来源：arXiv:{e(paper["id"])}；版本：{e(paper["version"] or "未知")}；'
             f'<a href="{e(paper["url"])}">原文链接</a></p>',
             f'<p>生成日期：{e(record["generated_at"])}；模型：{e(record["model"])}</p>',
             '<p>阅读范围：仅标题与摘要。自动生成，未独立核实；个人判断请另建阅读记录。</p>']
    for field, label in FIELDS.items():
        parts.append(f'<h2>{e(label)}</h2><p>{e(result[field])}</p>')
    parts.extend([f'<h2>检索词</h2><p>{e("、".join(result["keywords"]))}</p>',
                  f'<h2>原文摘要</h2><p>{e(paper["abstract"])}</p>'])
    return '\n'.join(parts)


class Zotero:
    def __init__(self, config):
        self.base = f'https://api.zotero.org/users/{config.zotero_user}'
        self.headers = {'Zotero-API-Key': config.zotero_key, 'Zotero-API-Version': '3'}
        self.collection_name = config.collection
        self.collection_key = None

    def all(self, path):
        items, start = [], 0
        while True:
            response = read(self.base + path, service='Zotero', headers=self.headers, params={'format': 'json', 'limit': 100, 'start': start})
            page = response.json()
            if not isinstance(page, list):
                raise ValueError('Invalid Zotero listing')
            items.extend(page)
            if len(page) < 100:
                return items
            start += len(page)

    def create(self, path, data):
        response = requests.post(self.base + path, headers=self.headers, json=[data], timeout=(10, 30))
        response.raise_for_status()
        result = response.json()
        if result.get('failed') or '0' not in result.get('successful', {}):
            raise ValueError('Zotero write failed')
        return result['successful']['0']['key']

    def collection(self):
        if not self.collection_key:
            matches = [c for c in self.all('/collections') if c['data']['name'] == self.collection_name and not c['data'].get('parentCollection')]
            if len(matches) > 1:
                raise ValueError('Duplicate fixed collections')
            self.collection_key = matches[0]['key'] if matches else self.create('/collections', {'name': self.collection_name, 'parentCollection': False})
        return self.collection_key

    def ensure_paper(self, paper):
        matches = [item for item in self.all('/items/top') if item_identity(item) == paper['id']]
        if len(matches) > 1:
            log.error('Historical duplicate arXiv:%s: keys %s; no merge/delete', paper['id'], ','.join(i['key'] for i in matches))
            raise ValueError('Historical duplicate entries')
        collection = self.collection()
        if matches:
            item = matches[0]
            collections = item['data'].get('collections', [])
            if collection not in collections:
                response = requests.patch(self.base + '/items/' + item['key'],
                    headers={**self.headers, 'If-Unmodified-Since-Version': str(item['version'])},
                    json={'collections': collections + [collection]}, timeout=(10, 30))
                response.raise_for_status()
            return item['key']
        return self.create('/items', {
            'itemType': 'journalArticle', 'title': paper['title'], 'url': paper['url'],
            'abstractNote': paper['abstract'], 'creators': [{'creatorType': 'author', 'name': name} for name in paper.get('authors', [])],
            'extra': f'arXiv: {paper["id"]}\narXiv version: {paper["version"] or "unknown"}',
            'collections': [collection], 'tags': []})

    def ensure_note(self, parent, record):
        matches = [item for item in self.all(f'/items/{parent}/children')
                   if item['data'].get('itemType') == 'note'
                   and any(t.get('tag') == OWNER_TAG for t in item['data'].get('tags', []))
                   and OWNER_MARK in item['data'].get('note', '')]
        if len(matches) > 1:
            raise ValueError('Duplicate bot notes; manual review required')
        if matches:
            return matches[0]['key']
        return self.create('/items', {'itemType': 'note', 'parentItem': parent,
                           'note': note_html(record), 'tags': [{'tag': OWNER_TAG}], 'collections': []})
