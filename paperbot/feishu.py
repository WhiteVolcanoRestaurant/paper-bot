import requests
from paperbot.ai import preview


def card(record):
    paper = record['paper']
    authors = '、'.join(paper.get('authors', [])) or '摘要未说明'
    return {'msg_type': 'interactive', 'card': {
        'header': {'title': {'content': '☁️ 边云与大模型协同前沿追踪', 'tag': 'plain_text'}, 'template': 'indigo'},
        'elements': [{'tag': 'markdown', 'content':
                      f"**标题**：[{paper['title']}]({paper['url']})\n\n**作者**：{authors}\n\n"
                      f"**AI提取核心**：\n{preview(record['ai'])}"},
                     {'tag': 'action', 'actions': [{'tag': 'button', 'text': {'content': '阅读原文', 'tag': 'plain_text'},
                                                   'url': paper['url'], 'type': 'primary'}]}]}}


def send(record, config):
    response = requests.post(config.webhook, json=card(record), timeout=(10, 30))
    response.raise_for_status()
    data = response.json()
    code = data.get('code', data.get('StatusCode'))
    if type(code) is not int or code != 0:
        raise ValueError('Feishu rejected message')
