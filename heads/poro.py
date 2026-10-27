"""Poro AI: the School Head's recommendations in its own words, from a local language model.

What Poro recommends is decided by rules a person can check (heads/insights.py, school_decisions): which disciplines
stand on which level of the school's DepEd order, the step that fits each level, and the grade component to aim at.
Poro rewords each sentence, told what it must keep, so the recommendations read in a voice of their own. It runs on
the school's own computer through Ollama; 'poro' is qwen2.5 with Poro's persona (ml_engine/poro/Modelfile).

Nothing is shown unchecked. A reworded sentence is kept only when it carries the same numbers in the same order, says
"higher", "below" and the like the same way, keeps every name, period, level, grade component and DepEd order, names
the levels in the same order, brings in no new subject, cause or promise and no learner's name, and a second reading
by the model finds the same meaning. In tests the 3B model, writing freely from the facts, said an average dropped
when it rose and gave a group a weakest component the data did not, so it only rewords. The other sentences keep the
computed wording, and the School Head can switch between the two. Writing takes minutes on a laptop, so it happens
in one background worker: the page shows the computed text at once and swaps in Poro's sentences as they pass. They
stay cached until the grades change, because the token is built from the computed texts themselves.
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
TTL = 7 * 24 * 3600               # a reworded text is kept a week, or until its source changes (a new token)
RETRY_AFTER = 600                 # an unreachable model is tried again after 10 minutes
OLD_LEVELS = ('Beginning', 'Approaching Proficiency', 'Proficient', 'Advanced')     # DepEd Order No. 73, s. 2012
DRIFT = ('guarantee', 'definitely', 'surely', 'promise', 'as an ai', 'language model', 'expected to', 'is expected', 'will improve',
         'will rise', 'will increase', 'will drop', 'will decrease', 'due to', 'caused by', 'affected by', 'as a result of')
# words a rewrite may not bring in when the original did not use them: they change who or what it is about, or add a
# deadline ("this week" turned up in a rewrite of a sentence that set none)
REWORD_DRIFT = ('section', 'class', 'teacher', 'adviser', 'school head', 'parent', 'subject', 'majority', 'most of', 'half of',
                'every learner', 'each learner', 'all learners', 'unchanged', 'stable', 'steady', 'fail',
                'this week', 'next week', 'today', 'tomorrow', 'daily', 'every day', 'weekly', 'monthly')
CAUSAL = ('due to', 'caused by', 'affected by', 'as a result of')        # allowed only where the original names a cause
PRONOUNS = re.compile(r'\b(?:he|she|her|hers|his|him|himself|herself)\b', re.I)     # a discipline is not "her"
# up-or-down words: a rewrite must say "higher", "below" and the like in the same order as the original
UP = re.compile(r'\b(?:higher|above|rose|risen|rises?|increas\w*|gain\w*|climb\w*|grew|up(?= (?:from|by|on|\d)))\b', re.I)
DOWN = re.compile(r'\b(?:lower|below|under|beneath|fell|fallen|falls?|drop\w*|decreas\w*|declin\w*|dip\w*|slid|down(?= (?:from|by|on|\d)))\b', re.I)
# phrases that name each grade component, whatever the DepEd order calls it ("performance" alone is plain English)
COMPONENT_WORDS = {'ww': ('written work', 'written/oral', 'oral work'), 'pt': ('performance task', 'product/performance', 'product task'),
                   'qa': ('quarterly assessment', 'quarterly exam', 'summative test', 'term exam', 'examination')}
CITATION = re.compile(r'DepEd Order No\.?\s*\d+,?\s*s\.?\s*\d{4}', re.I)
REWORD_SCHEMA = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}
SAME_SCHEMA = {'type': 'object', 'properties': {'same': {'type': 'boolean'}}, 'required': ['same']}


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
# Texts to reword, and one background worker (Ollama runs one model at a time anyway)
# --------------------------------------------------------------------------------------------

def register(fields, *, keep=()):
    """Remember computed texts for Poro to reword, each the text of one page field ({'decision-0': '...'}), and return
    the token the page polls with. Only text the server wrote can be reworded, so the endpoint is no open AI proxy.
    keep: names (disciplines, subjects) a rewrite must carry unchanged."""
    rules = policy.current()
    payload = {'v': 4, 'fields': [[k, v] for k, v in fields.items()], 'keep': sorted({k for k in keep if k}),
               'levels': [lv['name'] for lv in rules['levels']]}
    token = hashlib.sha1(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()[:24]
    _cache().set(f'poro:src:{token}', payload, TTL)
    return token


def status(token):
    """{'state': 'writing'} until the texts are reworded (with the sentences written so far, if any), then the result:
    {'state': 'done', 'source': 'ai' | 'rules', 'fields', 'written', 'total', 'model'}. None for an unknown token."""
    if not _cache().get(f'poro:src:{token}'):
        return None
    done = _cache().get(f'poro:out:{token}')
    if done is not None:
        return dict(done, state='done')
    if not _conf().get('ENABLED', True):
        return {'state': 'done', 'source': 'rules', 'model': '', 'disabled': True}
    _submit(token)
    return dict(_cache().get(f'poro:part:{token}') or {}, state='writing')


def written(token):
    """The fields Poro has reworded and checked for a token ({'decision-0': '...'}), or {} while it is still writing
    or could not. Starts nothing (for downloads)."""
    done = _cache().get(f'poro:out:{token}') if token else None
    return (done or {}).get('fields') or {}


_jobs = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def _submit(token):
    global _worker
    if not _cache().add(f'poro:job:{token}', time.time(), 900):      # already waiting or being written
        return
    _jobs.put(token)
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name='poro-writer', daemon=True)
            _worker.start()


def _work():
    while True:
        token = _jobs.get()
        try:
            _write(token)
        except Exception as exc:
            logger.warning('Poro could not reword %s: %s', token, exc)
            _cache().set(f'poro:out:{token}', {'state': 'done', 'source': 'rules', 'model': '', 'unavailable': True}, RETRY_AFTER)
        finally:
            _cache().delete(f'poro:job:{token}')
            _jobs.task_done()


# --------------------------------------------------------------------------------------------
# Rewording, one sentence at a time (a small model asked for many at once lets them run into each other)
# --------------------------------------------------------------------------------------------

def _sentences(text):
    """A computed text cut into its sentences ("No. 8" and "85.0%" do not end one)."""
    return [s for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', ' '.join(text.split())) if s]


def _items(stored):
    """Every sentence of every field, with the field it belongs to."""
    items = []
    for field, text in stored['fields']:
        for sentence in _sentences(text):
            items.append({'id': str(len(items) + 1), 'field': field, 'text': sentence})
    return items


def _reword_prompt(item, check):
    keep = check.must_keep(item['text'])
    return ('Reword this sentence of advice for a School Head as one sentence, in your own natural, warm and clear words. '
            'Keep every phrase listed under KEEP exactly as written and in the same order. Do not add or leave out any fact, '
            'number, step or reason, and do not promise results. Call them learners. Do not write "I". Answer with {"text": ...}.\n\n'
            + ('KEEP: ' + ' | '.join(keep) + '\n' if keep else '') + 'TEXT: ' + item['text'])


class Checker:
    """Passes a reworded sentence only when it says what the computed one says (problem() lists every check)."""

    def __init__(self, stored):
        active = set(stored['levels'])
        others = {lv['name'] for rules in policy.POLICIES.values() for lv in rules['levels']} | set(OLD_LEVELS)
        self.levels = sorted(others - active, key=len, reverse=True)
        self.active = re.compile(r'\b(' + '|'.join(re.escape(n) for n in sorted(active, key=len, reverse=True)) + r')\b', re.I)
        names = set(stored.get('keep', []))
        # names a word may be a misspelling of (proper nouns only: "Grade" would catch the plain word "grades")
        self.words = {w for name in names for w in re.findall(r'[A-Z][a-z]{4,}', name) if w != 'Grade'}
        # what a rewrite must carry over whenever the original has it ("2.6 points away" once came back as "(2.6)", and
        # "where Mathematics is weakest" was dropped, which leaves the reason for the step out)
        self.keep = sorted(names | active | {name for _, name, _ in policy.components()}
                           | {'remediation', 'LAC', 'points away', 'points above', 'weakest'}, key=len, reverse=True)
        # the same, with DepEd orders, periods, numbers and up-or-down words, in one pattern for telling Poro what to keep
        self.keep_pattern = re.compile('|'.join(['(?:' + CITATION.pattern + ')', '(?:' + insights._PERIODS.pattern + ')']
                                                + [re.escape(k) for k in self.keep]
                                                + [r'\d+(?:\.\d+)?%?', UP.pattern, DOWN.pattern]), re.I)

    def must_keep(self, sentence):
        """What a rewrite of the sentence has to say as written, in order: DepEd orders, periods, names, levels, grade
        components, numbers and up-or-down words."""
        return [m.group(0) for m in self.keep_pattern.finditer(sentence)]

    def _misspelled(self, text):
        """A word one or two letters away from a name ("Arling" for "Araling"), and not itself a name ("Science" is one
        letter from "Sciences", but both are names)."""
        exact = {w.lower() for w in self.words}
        for word in re.findall(r'[A-Z][a-z]{4,}', text):
            if word.lower() in exact:
                continue
            for name in self.words:
                if word != name and word.lower() != name.lower() and abs(len(word) - len(name)) <= 2 and _distance(word.lower(), name.lower()) <= 2:
                    return True
        return False

    def _levels_in(self, text):
        return _runs(m.group(1).lower() for m in self.active.finditer(text))

    def problem(self, source, value):
        """Why a rewrite of one computed sentence cannot be shown, or None when it is faithful: the same numbers in the
        same order, the same up-or-down wording, every name, period, level, grade component and DepEd order kept, the
        levels in the same order, nothing new about who or what, no new cause or promise, no he or she."""
        if not isinstance(value, str) or not value.strip():
            return 'missing'
        text = _house_style(value)
        if _plain(text) == _plain(source):
            return 'the same words as the original'
        if not 0.6 * len(source) <= len(text) <= 1.6 * len(source):
            return f'length {len(text)} for {len(source)}'
        if re.search(r'https?://|[*#`]|\bI\b', text):
            return 'a link, markup or "I"'
        figures = lambda t: [n for n in insights._figures(t) if n != '1']      # "one class" is "a class"
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
        if added:
            return 'brought in ' + ', '.join(added)
        if PRONOUNS.search(text) and not PRONOUNS.search(source):
            return 'a "he" or "she"'
        if self._levels_in(text) != self._levels_in(source):
            return 'levels in another order'
        if _components(text) != _components(source):
            return 'other grade components'
        if self._misspelled(text):
            return 'a misspelled name'
        if any(re.search(r'\b' + re.escape(n) + r'\b', text) for n in self.levels):
            return 'a level name of another DepEd order'
        return None

    def reworded(self, source, value):
        """The rewrite when problem() finds nothing wrong with it."""
        if not source or self.problem(source, value):
            return None
        return _house_style(value)


def _write(token):
    stored = _cache().get(f'poro:src:{token}')
    if not stored:
        return
    started, check = time.time(), Checker(stored)
    items, written, raw, model = _items(stored), {}, [], ''
    for n, item in enumerate(items, start=1):
        for temperature in (0.7, 0.3):          # a rewrite that fails a check gets one calmer try
            data, model = ask(_reword_prompt(item, check), REWORD_SCHEMA, num_predict=24 + 3 * len(item['text'].split()),
                              temperature=temperature, timeout=_conf().get('WRITE_TIMEOUT', 600))
            text = check.reworded(item['text'], data.get('text'))
            same = _same_meaning(item['text'], text) if text else None
            raw.append({'id': item['id'], 'text': data.get('text'), 'temperature': temperature, 'same': same})
            if text and same:
                written[item['id']] = text
                break
        # the page shows each sentence as soon as it passes
        _cache().set(f'poro:part:{token}', dict(_assemble(items, written), done=n, model=model), 3600)
    _cache().set(f'poro:raw:{token}', {'items': raw}, 24 * 3600)      # the unchecked answers, for looking into rejections only
    result = dict(_assemble(items, written), model=model, seconds=round(time.time() - started))
    _cache().set(f'poro:out:{token}', result, TTL if result['written'] else 24 * 3600)
    _cache().delete(f'poro:part:{token}')


def _same_meaning(source, text):
    """The model as a second reader, after the rule checks: does the rewrite say exactly what the computed sentence
    says? It catches what rules cannot, such as who does what turned around or a step slipped in (7 of 9 known pairs
    in testing; its mistakes were mostly rejecting a good rewrite, which only keeps the computed wording)."""
    prompt = ('Compare sentence B with sentence A. Answer {"same": true} only if B says exactly what A says: the same facts, '
              'the same people doing the same things, nothing certain that A only forecasts, and nothing added or left out. '
              'Otherwise answer {"same": false}.\n\nA: ' + source + '\nB: ' + text)
    try:
        data, _ = ask(prompt, SAME_SCHEMA, num_predict=12, temperature=0, timeout=_conf().get('WRITE_TIMEOUT', 600))
    except Exception:                       # no second reading, no rewrite
        return False
    return data.get('same') is True


def _assemble(items, written):
    """The fields with every sentence Poro reworded (written: item id -> checked text) put back in place; the other
    sentences of a field keep their computed wording."""
    pieces, changed = {}, set()
    for item in items:
        pieces.setdefault(item['field'], []).append(written.get(item['id']) or item['text'])
        if item['id'] in written:
            changed.add(item['field'])
    fields = {field: ' '.join(texts) for field, texts in pieces.items() if field in changed}
    return {'source': 'ai' if written else 'rules', 'fields': fields, 'written': len(written), 'total': len(items)}


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


def _house_style(text):
    """DepEd's word for them: learners, not students."""
    return re.sub(r'\b([Ss])tudent(s?)\b', lambda m: ('L' if m.group(1) == 'S' else 'l') + 'earner' + m.group(2), ' '.join(text.split()))


def _plain(text):
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()
