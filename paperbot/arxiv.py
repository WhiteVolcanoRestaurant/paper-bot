import re
from paperbot.http import read

EDGE = ['edge computing', 'edge-cloud', 'cloud-edge', 'split computing', 'offloading', 'device-cloud', 'edge device']
MODEL = ['llm', 'large language model', 'slm', 'small language model', 'collaborative inference', 'speculative decoding', 'model routing', 'distillation']
IDENTITY = r'(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z.\-]+/\d{7})'


def parse_id(value):
    value = str(value or '').strip()
    match = re.fullmatch(rf'({IDENTITY})(?:v(\d+))?(?:\.pdf)?', value)
    if not match:
        match = re.search(rf'(?:arxiv\.org/(?:abs|pdf)/|arxiv:|arxiv\.)(?:\s*)({IDENTITY})(?:v(\d+))?(?=$|[\s?#]|\.pdf)', value, re.I)
    return (match[1].lower(), int(match[2]) if match[2] else None) if match else (None, None)


def keyword_filter(title, abstract):
    text = (title + ' ' + abstract).lower()
    return any(word in text for word in EDGE + MODEL)


def fetch_papers():
    import feedparser
    response = read('https://export.arxiv.org/api/query', service='arXiv',
                    headers={'User-Agent': 'paper-bot/1.0'}, params={
        'search_query': 'cat:cs.DC OR cat:cs.NI OR cat:cs.LG OR cat:cs.AI',
        'sortBy': 'submittedDate', 'sortOrder': 'descending', 'max_results': 200})
    feed = feedparser.parse(response.content)
    if feed.bozo or not feed.entries:
        raise ValueError('Invalid/empty arXiv feed')
    papers = []
    for entry in feed.entries:
        pid, version = parse_id(entry.get('id') or entry.get('link'))
        if pid:
            papers.append({'id': pid, 'version': version, 'title': ' '.join(entry.title.split()),
                           'abstract': ' '.join(entry.summary.split()),
                           'url': f'https://arxiv.org/abs/{pid}' + (f'v{version}' if version else ''),
                           'authors': [a.name for a in entry.get('authors', []) if a.get('name')]})
    return papers
