"""Poro AI: the School Head's briefs, written by a local language model from each class's own data.

What a brief says is decided by rules a person can check (heads/insights.py): which findings, which next steps,
and one step up for every level in the class. Poro writes the words of every part: the headline, the summary,
each finding, each next step and the advice for each level, so every class reads in its own voice. It runs on the
school's own computer through Ollama; 'poro' is qwen2.5 with Poro's persona (ml_engine/poro/Modelfile).

Two styles (settings.PORO_AI['STYLE']):
- 'faithful' (the default): Poro rewrites every sentence of the computed brief in its own words, told what each one
  must keep. A sentence is kept only when it carries the same numbers in the same order, says "higher", "below" and
  the like the same way, keeps every name, period, level, grade component and DepEd order, and brings in no new
  subject such as sections, teachers or causes. On a laptop-sized model this is the safe choice: in tests the 3B
  model, writing freely, said an average dropped when it rose, called learners "sections" and gave a group a weakest
  component the data did not.
- 'free': Poro writes each part from the facts alone, under the checks below. For a larger model on a stronger
  computer.

Nothing is shown unchecked. In both styles no learner may be named (the plan lists them from the records), only the
level names of the school's DepEd order may appear, and nothing may guess at causes or promise results. In the free
style every number must also come from the class's data, the headline, summary and findings must say the average
moved the way it did, and each level's advice must aim at that group's weakest grade component and carry no numbers.
A part that fails keeps its computed wording. Writing takes minutes on a laptop, so it happens in one background
worker: the page shows the computed brief at once and swaps in Poro's parts when they are ready. They stay cached
until the grades change, because the token is built from the facts themselves. The dashboard's one-paragraph status
goes the same way.
"""
import hashlib
import json
import logging
import queue
import re
import threading
import time

from django.conf import settings
from django.core.cache import caches

from core import grading_policy as policy

from . import insights

logger = logging.getLogger(__name__)
TTL = 7 * 24 * 3600               # a written brief is kept a week, or until its facts change (a new token)
RETRY_AFTER = 600                 # an unreachable model is tried again after 10 minutes
OLD_LEVELS = ('Beginning', 'Approaching Proficiency', 'Proficient', 'Advanced')     # DepEd Order No. 73, s. 2012
DRIFT = ('guarantee', 'definitely', 'surely', 'promise', 'as an ai', 'language model', 'expected to', 'is expected', 'will improve',
         'will rise', 'will increase', 'will drop', 'will decrease', 'due to', 'caused by', 'affected by', 'as a result of')
# words a faithful rewrite may not bring in when the original did not use them: they change who or what it is about
REWORD_DRIFT = ('section', 'class', 'teacher', 'adviser', 'school head', 'parent', 'subject', 'majority', 'most of', 'half of',
                'every learner', 'all learners', 'maintain', 'remain', 'unchanged', 'stable', 'steady', 'improv', 'fail')
CAUSAL = ('due to', 'caused by', 'affected by', 'as a result of')        # allowed only where the original names a cause
PRONOUNS = re.compile(r'\b(?:he|she|her|hers|his|him|himself|herself)\b', re.I)     # a section is not "her"
FALLING = re.compile(r'\b(drops?|dropped|decreas\w*|declin\w*|dips?|dipped|fell|worsen\w*|slid|lower average|went down)\b', re.I)
RISING = re.compile(r'\b(rise|rises|rose|risen|increas\w*|improv\w*|gain\w*|climb\w*|went up|grew)\b', re.I)
# up-or-down words: a faithful rewrite must say "higher", "below" and the like in the same order as the original
UP = re.compile(r'\b(?:higher|above|rose|risen|rises?|increas\w*|gain\w*|climb\w*|grew|up(?= (?:from|by|on|\d)))\b', re.I)
DOWN = re.compile(r'\b(?:lower|below|under|beneath|fell|fallen|falls?|drop\w*|decreas\w*|declin\w*|dip\w*|slid|down(?= (?:from|by|on|\d)))\b', re.I)
# phrases that name each grade component, whatever the DepEd order calls it ("performance" alone is plain English)
COMPONENT_WORDS = {'ww': ('written work', 'written/oral', 'oral work'), 'pt': ('performance task', 'product/performance', 'product task'),
                   'qa': ('quarterly assessment', 'quarterly exam', 'summative test', 'term exam', 'examination')}
CITATION = re.compile(r'DepEd Order No\.?\s*\d+,?\s*s\.?\s*\d{4}', re.I)


def _conf():
    return getattr(settings, 'PORO_AI', {})


def _cache():
    return caches['default']


def models():
    """Poro's model first, then the base it is built on, then the small model, whichever Ollama has."""
    conf, out = _conf(), []
    for name in (conf.get('MODEL', 'poro'), conf.get('BASE_MODEL', 'qwen2.5:3b'), 'qwen2.5:1.5b'):
        if name and name not in out:
            out.append(name)
    return out


def ask(prompt, schema, *, num_predict, temperature, timeout):
    """(parsed JSON, model name) from the first of models() that Ollama has. Raises when Ollama cannot answer."""
    import requests

    url = _conf().get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/') + '/api/generate'
    missing = []
    for model in models():
        response = requests.post(url, timeout=timeout, json={
            'model': model, 'prompt': prompt, 'stream': False, 'format': schema,
            'options': {'temperature': temperature, 'num_predict': num_predict}})
        if response.status_code == 404:                      # not installed on this computer: try the next
            missing.append(model)
            continue
        response.raise_for_status()
        return json.loads(response.json().get('response') or '{}'), model
    raise RuntimeError('None of these models is installed in Ollama: ' + ', '.join(missing))


# --------------------------------------------------------------------------------------------
# One background worker (Ollama runs one model at a time anyway)
# --------------------------------------------------------------------------------------------

_jobs = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def _submit(kind, token):
    global _worker
    if not _cache().add(f'poro:job:{token}', time.time(), 900):      # already waiting or being written
        return
    _jobs.put((kind, token))
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name='poro-writer', daemon=True)
            _worker.start()


def _work():
    while True:
        kind, token = _jobs.get()
        try:
            (_write_brief if kind == 'brief' else _write_line)(token)
        except Exception as exc:
            logger.warning('Poro could not write %s %s: %s', kind, token, exc)
            _cache().set(f'poro:out:{token}', {'state': 'done', 'source': 'rules', 'model': '', 'unavailable': True}, RETRY_AFTER)
        finally:
            _cache().delete(f'poro:job:{token}')
            _jobs.task_done()


def _status(kind, token):
    """{'state': 'writing'} until the job is done (with the sentences written so far, if any), then its result; None
    for an unknown token."""
    if not _cache().get(f'poro:src:{token}'):
        return None
    done = _cache().get(f'poro:out:{token}')
    if done is not None:
        return dict(done, state='done')
    if not _conf().get('ENABLED', True):
        return {'state': 'done', 'source': 'rules', 'model': '', 'disabled': True}
    _submit(kind, token)
    return dict(_cache().get(f'poro:part:{token}') or {}, state='writing')


# --------------------------------------------------------------------------------------------
# The dashboard's status paragraph: reworded, every figure kept (insights.check_rewrite)
# --------------------------------------------------------------------------------------------

def line_status(token):
    return _status('line', token)


def _write_line(token):
    stored = _cache().get(f'poro:src:{token}')
    source, keep = (stored, []) if isinstance(stored, str) else (stored['text'], stored['keep'])
    sentences = max(2, min(4, source.count('. ') + 1))
    prompt = ('Rewrite this status for the School Head in your own words, clearly and briefly. Keep every number exactly as '
              'written and with the same meaning. Do not add any fact, number or advice. Use at most '
              f'{sentences} sentences.' + (' Keep these words exactly as written: ' + '; '.join(keep) + '.' if keep else '')
              + '\n\nSTATUS: ' + source)
    schema = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}
    result = {'text': source, 'source': 'rules', 'model': ''}
    for temperature in (0.6, 0.3):                         # a changed figure throws the wording away; one more try
        data, model = ask(prompt, schema, num_predict=220, temperature=temperature, timeout=_conf().get('WRITE_TIMEOUT', 600))
        text = ' '.join(str(data.get('text', '')).split())
        if insights.check_rewrite(source, text, keep):
            result = {'text': text, 'source': 'ai', 'model': model}
            break
    _cache().set(f'poro:out:{token}', result, TTL if result['source'] == 'ai' else 24 * 3600)


# --------------------------------------------------------------------------------------------
# The section brief: every part written from the class's facts
# --------------------------------------------------------------------------------------------

BRIEF_SCHEMA = {
    'type': 'object',
    'properties': {
        'headline': {'type': 'string'},
        'summary': {'type': 'string'},
        'findings': {'type': 'array', 'items': {'type': 'object', 'properties': {'title': {'type': 'string'}, 'detail': {'type': 'string'}},
                                                'required': ['title', 'detail']}},
        'actions': {'type': 'array', 'items': {'type': 'object', 'properties': {'title': {'type': 'string'}, 'why': {'type': 'string'}},
                                               'required': ['title', 'why']}},
        'levels': {'type': 'array', 'items': {'type': 'object', 'properties': {'level': {'type': 'string'}, 'advice': {'type': 'string'}},
                                              'required': ['level', 'advice']}},
    },
    'required': ['headline', 'summary', 'findings', 'actions', 'levels'],
}


def register_brief(brief, facts, learner_names):
    """Remember a computed brief with the facts Poro may use; returns the token the page polls with."""
    rules = policy.current()
    parts = {
        'headline': brief['headline'], 'summary': brief['summary'],
        'findings': [{'about': f['title'], 'facts': f['detail']} for f in brief['findings']],
        'actions': [{'about': a['title'], 'facts': a['why'], 'who': a['who'], 'when': a['when']} for a in brief['actions']],
        'levels': [{'key': s['level']['key'], 'level': s['level']['name'], 'learners': s['count'],
                    'weak_key': s['weak']['key'] if s['weak'] and s['target'] else None,
                    'next_level': s['target']['name'] if s['target'] else None,
                    'points_needed': f'{s["gap"][0]} to {s["gap"][1]}' if s['gap'] else None,
                    'weakest': (f'{s["weak"]["label"]}: {s["weak"]["average"]}% for this group against {s["weak"]["class"]}% '
                                'for the class') if s['weak'] else None,
                    'when': s['when'], 'plan': s['how']} for s in brief['plan']],
    }
    delta = brief['delta']
    facts = dict(facts, passing_mark='75 (a grade below 75 is not passing)',
                 levels_of_this_school={lv['name']: lv['range'] for lv in rules['levels']})
    payload = {'v': 2, 'facts': facts, 'parts': parts, 'names': sorted({n for n in learner_names if n}),
               'levels': [lv['name'] for lv in rules['levels']], 'level_mins': [lv['min'] for lv in rules['levels']],
               'trend': None if delta is None or abs(delta) < 0.05 else ('up' if delta > 0 else 'down')}
    token = hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:24]
    _cache().set(f'poro:src:{token}', payload, TTL)
    return token


def brief_status(token):
    return _status('brief', token)


def _brief_prompt(stored):
    facts, parts = stored['facts'], stored['parts']
    dump = lambda value: json.dumps(value, ensure_ascii=False)
    lines = [
        'Write the School Head\'s brief about one class from the facts below. Use only these numbers and names, exactly as '
        'written. Write the subject and section names exactly as given. Never name a learner. Say only what the facts say: '
        'do not guess causes or predict anything beyond the forecast given. Call them learners, not students.',
        'FACTS: ' + dump(facts),
        'Answer with one JSON object:',
        '- "headline": one sentence of at most 25 words, the most important thing about this class right now.',
        '- "summary": two or three sentences: where the class stands, what changed since the last period, and where it is heading.',
    ]
    if parts['findings']:
        lines += ['- "findings": one object per finding below, in the same order, each with "title" (at most 10 words) and '
                  '"detail" (one or two sentences: what it means and why it matters).',
                  'FINDINGS: ' + dump([{k: f[k] for k in ('about', 'facts')} for f in parts['findings']])]
    else:
        lines.append('- "findings": an empty list.')
    if parts['actions']:
        lines += ['- "actions": one object per next step below, in the same order, each with "title" (an instruction of at '
                  'most 12 words) and "why" (one sentence).',
                  'NEXT STEPS: ' + dump([{k: a[k] for k in ('about', 'facts', 'who', 'when')} for a in parts['actions']])]
    else:
        lines.append('- "actions": an empty list.')
    if parts['levels']:
        lines += ['- "levels": one object per level group below, in the same order, each with "level" (the level name exactly '
                  'as given) and "advice" (one or two sentences without numbers: one concrete classroom step that moves these '
                  'learners up one level, aimed at their weakest component when it is given and at no other component).',
                  'LEVEL GROUPS: ' + dump([{k: v for k, v in s.items() if k in ('level', 'learners', 'next_level', 'points_needed',
                                                                               'weakest', 'when') and v is not None}
                                           for s in parts['levels']])]
    else:
        lines.append('- "levels": an empty list.')
    return '\n'.join(lines)


REWORD_SCHEMA = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}
# words that give advice: a rewrite of a sentence that gave none may not bring any in ("it's crucial to provide...")
ADVICE = ('should', 'must', 'need to', 'needs to', 'crucial', 'important', 'essential', 'recommend', 'suggest', 'ensure',
          'provide', 'offer', 'consider', 'encourage', "let's", 'let us', 'we can', 'make sure')
ADVISING = ('action-', 'level-')          # fields whose sentences are advice already: next steps and level plans


def _sentences(text):
    """A computed part cut into its sentences ("No. 8" and "85.0%" do not end one)."""
    return [s for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', ' '.join(text.split())) if s]


def _items(stored):
    """The brief as the pieces Poro rewrites one by one: every sentence of every part, each with the page field it
    belongs to (the data-poro keys of the section page)."""
    parts = stored['parts']
    fields = [('headline', parts['headline']), ('summary', parts['summary'])]
    for i, f in enumerate(parts['findings']):
        fields += [(f'finding-{i}-title', f['about']), (f'finding-{i}-detail', f['facts'])]
    for i, a in enumerate(parts['actions']):
        fields += [(f'action-{i}-title', a['about']), (f'action-{i}-why', a['facts'])]
    fields += [(f'level-{s["key"]}', s['plan']) for s in parts['levels']]
    group = {f'level-{s["key"]}': s['level'] for s in parts['levels']}     # whose plan it is, which the sentence leaves out
    items = []
    for field, text in fields:
        for sentence in _sentences(text):
            items.append({'id': str(len(items) + 1), 'field': field, 'text': sentence, 'short': field.endswith('-title'),
                          'group': group.get(field)})
    return items


def _reword_prompt(item, check):
    """One sentence (or title) at a time: a small model asked for many at once lets them run into each other."""
    keep = check.must_keep(item['text'])
    what = (f'a title of a School Head\'s class brief as a short title of at most {len(item["text"].split()) + 3} words'
            if item['short'] else 'a sentence of a School Head\'s class brief as one sentence')
    return (f'Reword {what}, in your own natural, warm and clear words. Keep every phrase listed under KEEP exactly as '
            'written and in the same order. Do not add any fact, number, reason, advice or opinion, and do not leave anything '
            'out. Call them learners. Do not write "I". Answer with {"text": ...}.\n\n'
            + (f'FOR: the learners at {item["group"]}; this is their plan.\n' if item.get('group') else '')
            + ('KEEP: ' + ' | '.join(keep) + '\n' if keep else '') + 'TEXT: ' + item['text'])


def _numbers(value, out):
    """Every number written anywhere in the facts."""
    if isinstance(value, dict):
        for v in value.values():
            _numbers(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers(v, out)
    elif isinstance(value, bool) or value is None:
        return out
    elif isinstance(value, (int, float)):
        out.add(float(value))
    elif isinstance(value, str):
        out.update(float(n) for n in re.findall(r'\d+(?:\.\d+)?', value))
    return out


class Checker:
    """Passes a written part only when its numbers, names and level names all come from the class's facts."""

    def __init__(self, stored):
        self.allowed = _numbers(stored['facts'], set()) | _numbers(stored['parts'], set()) | {float(insights.PASSING)} \
            | {float(m) for m in stored['level_mins']}
        staff = ' '.join(str(stored['facts'].get(k) or '') for k in ('teacher', 'adviser'))
        surnames = {n.split(',')[0].strip() for n in stored['names']}
        self.names = sorted(n for n in surnames if len(n) >= 3 and n not in staff)
        active = set(stored['levels'])
        others = {lv['name'] for rules in policy.POLICIES.values() for lv in rules['levels']} | set(OLD_LEVELS)
        self.levels = sorted(others - active, key=len, reverse=True)
        self.active = re.compile(r'\b(' + '|'.join(re.escape(n) for n in sorted(active, key=len, reverse=True)) + r')\b', re.I)
        self.trend = stored.get('trend')
        facts = stored['facts']
        cited = ' '.join(str(facts.get(k) or '') for k in ('deped_rules',)) + ' ' + ' '.join(
            str(a.get('facts', '')) for a in stored['parts']['actions'])
        self.citations = {c.lower() for c in CITATION.findall(cited)}
        # names a word may be a misspelling of (proper nouns only: "Grade" would catch the plain word "grades")
        self.words = {w for k in ('subject', 'teacher', 'adviser') for w in re.findall(r'[A-Z][a-z]{4,}', str(facts.get(k) or ''))} | \
            {w for w in re.findall(r'[A-Z][a-z]{4,}', str(facts.get('class') or '')) if w != 'Grade'}
        # what a faithful rewrite must carry over whenever the original has it
        section = re.sub(r'^Grade\s*\d+\s*', '', str(facts.get('class') or '')).strip()
        self.keep = sorted({str(facts.get(k)) for k in ('subject', 'teacher', 'adviser') if facts.get(k)} | {section} | active
                           | {name for _, name, _ in policy.components()} | {'remediation', 'forecast'} - {''}, key=len, reverse=True)
        # the same, with DepEd orders, periods, numbers and up-or-down words, in one pattern for telling Poro what to keep
        self.keep_pattern = re.compile('|'.join(['(?:' + CITATION.pattern + ')', '(?:' + insights._PERIODS.pattern + ')']
                                                + [re.escape(k) for k in self.keep]
                                                + [r'\d+(?:\.\d+)?%?', UP.pattern, DOWN.pattern]), re.I)

    def must_keep(self, sentence):
        """What a rewrite of the sentence has to say as written, in order: DepEd orders, periods, names, levels, grade
        components, numbers and up-or-down words."""
        return [m.group(0) for m in self.keep_pattern.finditer(sentence)]

    def _misspelled(self, text):
        """A word one or two letters away from a name in the facts ("Arling" for "Araling")."""
        for word in re.findall(r'[A-Z][a-z]{4,}', text):
            for name in self.words:
                if word != name and word.lower() != name.lower() and abs(len(word) - len(name)) <= 2 and _distance(word.lower(), name.lower()) <= 2:
                    return True
        return False

    def _cited(self, text):
        """The text without citations of the DepEd orders the facts name; None when it cites any other order."""
        for c in CITATION.findall(text):
            if c.lower() not in self.citations:
                return None
        return CITATION.sub(' ', text)

    def _number_ok(self, text):
        for n in insights._figures(text):
            value = float(n)
            if not any(abs(value - a) < 0.051 or (value == int(value) and value == round(a)) for a in self.allowed):
                return False
        return True

    def _levels_in(self, text):
        return _runs(m.group(1).lower() for m in self.active.finditer(text))

    def problem(self, source, value, *, short=False, advice=False, group=None):
        """Why a rewrite of one computed sentence cannot be shown, or None when it is faithful: the same numbers in the
        same order, the same up-or-down wording, every name, period, level, grade component and DepEd order kept, the
        levels in the same order, nothing new about who or what, no advice where the sentence gave none (advice=True
        for next steps and level plans), no learner named. A level plan may name its own group (group)."""
        if not isinstance(value, str) or not value.strip():
            return 'missing'
        text = _house_style(value)
        if _plain(text) == _plain(source):
            return 'the same words as the original'
        low, high = (0.5, 2.2) if short else (0.6, 1.6)
        if not low * len(source) <= len(text) <= high * len(source):
            return f'length {len(text)} for {len(source)}'
        if re.search(r'https?://|[*#`]|\bI\b', text):
            return 'a link, markup or "I"'
        figures = lambda t: [n for n in insights._figures(t) if n != '1']      # "one weak assessment" is "a weak assessment"
        if figures(text) != figures(source):
            return f'numbers {figures(text)} for {figures(source)}'
        if _polarity(text) != _polarity(source):
            return f'up/down wording {_polarity(text)} for {_polarity(source)}'
        src, new = source.lower(), text.lower()
        lost = [k for k in self.keep if k.lower() in src and k.lower() not in new] + \
            [c for c in CITATION.findall(source) if c.lower() not in new] + \
            [p for p in insights._PERIODS.findall(source) if ' '.join(p.lower().split()) not in ' '.join(new.split())]
        if lost:
            return 'left out ' + ', '.join(lost)
        added = [w for w in REWORD_DRIFT + DRIFT if w in new and w not in src and not (w in CAUSAL and 'cause' in src)]
        if not advice and not any(w in src for w in ADVICE):
            added += [w for w in ADVICE if re.search(r'\b' + re.escape(w) + r'\b', new)]
        if added:
            return 'brought in ' + ', '.join(added)
        if PRONOUNS.search(text) and not PRONOUNS.search(source):
            return 'a "he" or "she"'
        if _runs(x for x in self._levels_in(text) if x != (group or '').lower()) != self._levels_in(source):
            return 'levels in another order'
        if _components(text) != _components(source):
            return 'other grade components'
        if self._misspelled(text):
            return 'a misspelled name'
        if any(re.search(r'\b' + re.escape(n) + r'\b', text) for n in self.names):
            return 'a learner named'
        if any(re.search(r'\b' + re.escape(n) + r'\b', text) for n in self.levels):
            return 'a level name of another DepEd order'
        return None

    def reworded(self, source, value, *, short=False, advice=False, group=None):
        """The rewrite when problem() finds nothing wrong with it."""
        if not source or self.problem(source, value, short=short, advice=advice, group=group):
            return None
        return _house_style(value)

    def text(self, value, low, high, *, numbers=True, direction=False, component=None):
        """The text when it passes; numbers=False allows none, direction checks the average's change, component the
        one grade component a level's advice may name."""
        if not isinstance(value, str):
            return None
        text = ' '.join(value.split())
        lowered = text.lower()
        if not low <= len(text) <= high or re.search(r'https?://|[*#`]|\bI\b|\bI\'m\b', text):
            return None
        if any(word in lowered for word in DRIFT) or self._misspelled(text):
            return None
        plain = self._cited(text)
        if plain is None or (not self._number_ok(plain) if numbers else insights._figures(plain)):
            return None
        if direction and ((self.trend == 'up' and FALLING.search(text)) or (self.trend == 'down' and RISING.search(text))):
            return None
        if component:                                   # a group's advice never points at another component
            mentions = {key for key, words in COMPONENT_WORDS.items() if any(w in lowered for w in words)}
            if mentions - {component}:
                return None
        if any(re.search(r'\b' + re.escape(name) + r'\b', text) for name in self.names):
            return None
        if any(re.search(r'\b' + re.escape(name) + r'\b', text) for name in self.levels):
            return None
        return text


def _write_brief(token):
    stored = _cache().get(f'poro:src:{token}')
    if not stored:
        return
    started, check, parts = time.time(), Checker(stored), stored['parts']
    if _conf().get('STYLE', 'faithful') != 'free':
        items, written, raw, model = _items(stored), {}, [], ''
        for n, item in enumerate(items, start=1):
            advice = item['field'].startswith(ADVISING)
            for temperature in (0.7, 0.3):          # a rewrite that fails a check gets one calmer try
                data, model = ask(_reword_prompt(item, check), REWORD_SCHEMA, num_predict=24 + 3 * len(item['text'].split()),
                                  temperature=temperature, timeout=_conf().get('WRITE_TIMEOUT', 600))
                text = check.reworded(item['text'], data.get('text'), short=item['short'], advice=advice, group=item['group'])
                same = _same_meaning(item['text'], text, group=item['group']) if text else None
                raw.append({'id': item['id'], 'text': data.get('text'), 'temperature': temperature, 'same': same})
                if text and same:
                    written[item['id']] = text
                    break
            # the page shows each sentence as soon as it passes
            _cache().set(f'poro:part:{token}', dict(_faithful(items, written), done=n, model=model), 3600)
        _cache().set(f'poro:raw:{token}', {'items': raw}, 24 * 3600)      # the unchecked answers, for looking into rejections only
        result = dict(_faithful(items, written), model=model, seconds=round(time.time() - started), style='faithful')
        _cache().set(f'poro:out:{token}', result, TTL if result['written'] else 24 * 3600)
        _cache().delete(f'poro:part:{token}')
        return
    data, model = ask(_brief_prompt(stored), BRIEF_SCHEMA, num_predict=1300, temperature=0.5, timeout=_conf().get('WRITE_TIMEOUT', 600))
    _cache().set(f'poro:raw:{token}', data, 24 * 3600)
    out = {'headline': check.text(data.get('headline'), 30, 240, direction=True),
           'summary': check.text(data.get('summary'), 60, 700, direction=True), 'findings': [], 'actions': [], 'levels': {}}
    written = data.get('findings') if isinstance(data.get('findings'), list) else []
    for i, _ in enumerate(parts['findings']):
        item = written[i] if i < len(written) and isinstance(written[i], dict) else {}
        title, detail = check.text(item.get('title'), 8, 110, direction=True), check.text(item.get('detail'), 30, 420, direction=True)
        out['findings'].append({'title': title, 'detail': detail} if title and detail else None)
    written = data.get('actions') if isinstance(data.get('actions'), list) else []
    for i, _ in enumerate(parts['actions']):
        item = written[i] if i < len(written) and isinstance(written[i], dict) else {}
        title, why = check.text(item.get('title'), 8, 120), check.text(item.get('why'), 25, 320)
        out['actions'].append({'title': title, 'why': why} if title and why else None)
    written = data.get('levels') if isinstance(data.get('levels'), list) else []
    by_name = {str(item.get('level', '')).strip().lower(): item for item in written if isinstance(item, dict)}
    for i, step in enumerate(parts['levels']):
        item = by_name.get(step['level'].lower()) or (written[i] if i < len(written) and isinstance(written[i], dict) else {})
        out['levels'][step['key']] = check.text(item.get('advice'), 30, 420, numbers=False, component=step.get('weak_key'))
    total = 2 + len(parts['findings']) + len(parts['actions']) + len(parts['levels'])
    done = sum(1 for v in (out['headline'], out['summary']) if v) + sum(1 for v in out['findings'] + out['actions'] if v) \
        + sum(1 for v in out['levels'].values() if v)
    fields = {k: out[k] for k in ('headline', 'summary') if out[k]}
    for kind, key in (('findings', ('title', 'detail')), ('actions', ('title', 'why'))):
        for i, written in enumerate(out[kind]):
            fields.update({f'{kind[:-1]}-{i}-{k}': written[k] for k in key} if written else {})
    fields.update({f'level-{k}': v for k, v in out['levels'].items() if v})
    result = {'source': 'ai' if done else 'rules', 'model': model, 'fields': fields, 'written': done, 'total': total,
              'unit': 'parts', 'style': 'free', 'seconds': round(time.time() - started)}
    _cache().set(f'poro:out:{token}', result, TTL if done else 24 * 3600)


def _runs(items):
    """The items with repeats in a row taken as one: ['-', '-', '+'] is ['-', '+']."""
    out = []
    for item in items:
        if not out or out[-1] != item:
            out.append(item)
    return out


def _polarity(text):
    """The up-or-down words of a text in order, as '+' and '-'."""
    marks = sorted([(m.start(), '+') for m in UP.finditer(text)] + [(m.start(), '-') for m in DOWN.finditer(text)])
    return _runs(sign for _, sign in marks)


def _components(text):
    lowered = text.lower()
    return {key for key, words in COMPONENT_WORDS.items() if any(w in lowered for w in words)}


def _distance(a, b):
    """Edit distance between two short words."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, start=1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


SAME_SCHEMA = {'type': 'object', 'properties': {'same': {'type': 'boolean'}}, 'required': ['same']}


def _same_meaning(source, text, group=None):
    """The model as a second reader, after the rule checks: does the rewrite say exactly what the computed sentence
    says? It catches what rules cannot, such as who tutors whom turned around or advice slipped in (7 of 9 known
    pairs in testing; its mistakes were mostly rejecting a good rewrite, which only keeps the computed wording)."""
    prompt = ('Compare sentence B with sentence A. Answer {"same": true} only if B says exactly what A says: the same facts, '
              'the same people doing the same things, nothing certain that A only forecasts, and nothing added or left out. '
              'Otherwise answer {"same": false}.\n\n' + (f'Both are the plan for the learners at {group}.\n' if group else '')
              + 'A: ' + source + '\nB: ' + text)
    try:
        data, _ = ask(prompt, SAME_SCHEMA, num_predict=12, temperature=0, timeout=_conf().get('WRITE_TIMEOUT', 600))
    except Exception:                       # no second reading, no rewrite
        return False
    return data.get('same') is True


def _faithful(items, written):
    """The fields with every sentence Poro rewrote (written: item id -> checked text) put back in place; the other
    sentences of a field keep their computed wording."""
    pieces, changed = {}, set()
    for item in items:
        pieces.setdefault(item['field'], []).append(written.get(item['id']) or item['text'])
        if item['id'] in written:
            changed.add(item['field'])
    fields = {field: ' '.join(texts) for field, texts in pieces.items() if field in changed}
    return {'source': 'ai' if written else 'rules', 'fields': fields, 'written': len(written), 'total': len(items),
            'unit': 'sentences'}


def _house_style(text):
    """DepEd's word for them: learners, not students."""
    return re.sub(r'\b([Ss])tudent(s?)\b', lambda m: ('L' if m.group(1) == 'S' else 'l') + 'earner' + m.group(2), ' '.join(text.split()))


def _plain(text):
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()
