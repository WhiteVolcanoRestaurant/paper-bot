"""Run with python main.py. Importing this module never performs network calls."""
import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from paperbot.config import Config
from paperbot.arxiv import fetch_papers, keyword_filter
from paperbot.ai import summarize
from paperbot.feishu import send
from paperbot.state import State
from paperbot.zotero import Zotero
from paperbot.http import error_summary

log = logging.getLogger(__name__)


def run(config, state, papers, ai=summarize, zot=None, sender=send, day=None):
    day = day or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    failed = False
    # Retry accepted papers even after they disappear from the latest feed.
    queue = {pid: r['paper'] for pid, r in state.data['papers'].items()
             if 'ai' not in r or (r['ai']['relevant'] and (
                 (config.enable_feishu and r.get('feishu_status') != 'sent') or
                 (config.enable_zotero and (not r.get('zotero_key') or
                  (config.enable_ai_notes and not r.get('note_key'))))))}
    for paper in papers:
        record = state.data['papers'].get(paper['id'])
        if record and paper['version'] not in record['observed_versions']:
            record['observed_versions'].append(paper['version'])
            log.info('%s observed v%s; existing preview retained', paper['id'], paper['version'])
            state.save()
        queue.setdefault(paper['id'], paper)
    for pid, paper in queue.items():
        if not keyword_filter(paper['title'], paper['abstract']):
            continue
        if config.dry_run:
            log.info('DRY RUN candidate %s v%s (no AI or writes)', pid, paper['version'])
            continue
        record = state.data['papers'].get(pid)
        if (not record or 'ai' not in record) and config.enable_feishu and state.data['attempts'].get(day, 0) >= config.max_daily:
            continue
        if not record:
            record = {'paper': paper, 'observed_versions': [paper['version']]}
            state.data['papers'][pid] = record
            state.save()
        if 'ai' not in record:
            try:
                result = ai(record['paper'], config)
            except Exception as exc:
                log.error('AI failed for %s (%s); retryable, not rejected', pid, error_summary(exc))
                failed = True
                continue
            record.update(ai=result, model=config.ai_model, generated_at=day)
            state.save()
        if not record['ai']['relevant']:
            continue
        if config.enable_zotero:
            if not record.get('zotero_key'):
                try:
                    record['zotero_key'] = zot.ensure_paper(record['paper'])
                except Exception as exc:
                    log.error('Zotero failed for %s (%s); Feishu can continue', pid, error_summary(exc))
                    failed = True
                else:
                    state.save()
            if config.enable_ai_notes and record.get('zotero_key') and not record.get('note_key'):
                try:
                    record['note_key'] = zot.ensure_note(record['zotero_key'], record)
                except Exception as exc:
                    log.error('Zotero note failed for %s (%s); retryable', pid, error_summary(exc))
                    failed = True
                else:
                    state.save()
        if config.enable_feishu and record.get('feishu_status') != 'sent':
            count = state.data['attempts'].get(day, 0)
            if count >= config.max_daily:
                continue
            state.data['attempts'][day] = count + 1
            record['feishu_status'] = 'pending'
            record['feishu_attempt_date'] = day
            state.save()  # Durable reservation before sending.
            try:
                sender(record, config)
            except Exception as exc:
                log.error('Feishu failed/uncertain for %s (%s); retry next run', pid, error_summary(exc))
                failed = True
            else:
                record['feishu_status'] = 'sent'
                record['feishu_sent_date'] = day
                state.save()
    return int(failed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='arXiv read only; no AI or writes')
    parser.add_argument('--state', help='Enable local persistence at this path')
    parser.add_argument('--state-git', action='store_true', help='Checkpoint changes to bot-state checkout')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    phase = 'configuration'
    try:
        config = Config.from_env(args.dry_run)
        phase = 'persistent state'
        persistent = config.enable_persistence or args.state is not None or args.state_git
        with State(args.state or '.bot-state/state.json', dry_run=args.dry_run,
                   git=args.state_git, persistent=persistent) as state:
            if not persistent and not args.dry_run:
                log.info('Persistence disabled: no cross-run AI cache, Feishu deduplication or daily budget')
            if args.state_git:
                state.save()  # Verify state push permission before any service writes.
            zot = Zotero(config) if config.enable_zotero and not args.dry_run else None
            if not config.enable_feishu and not config.enable_zotero and not args.dry_run:
                log.info('Both destinations disabled; no service calls')
                return 0
            phase = 'arXiv fetch'
            papers = fetch_papers()
            phase = 'pipeline/state checkpoint'
            return run(config, state, papers, zot=zot)
    except Exception as exc:
        log.error('Run stopped during %s (%s)', phase, error_summary(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
