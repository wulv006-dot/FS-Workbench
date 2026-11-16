"""Ark (Volcano Engine) chat brain for FC27 small talk. Import is offline-safe."""

import asyncio
import json
import os
import re
from zoneinfo import ZoneInfo

import aiohttp

ARK_BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-v4-1-flash-economy-261017'
MAX_INPUT_CHARS = 1200
MAX_OUTPUT_CHARS = 400
MAX_CONTEXT_TURNS = 10
MAX_FALLBACKS = 3

SYSTEM_PROMPT = (
    'You are FC, an openly identified AI chat buddy in the FC27 gaming community. '
    'Always reply in English, whatever language the player writes in. '
    'Sound like a friendly club regular, not a help desk: warm, upbeat, a bit cheeky. '
    'Keep it short, normally one or two sentences and under 200 characters. '
    'Banter is welcome: joke back, play along with silly nonsense, hype their pulls and '
    'sympathise with bad pack luck. Never insult anyone and never turn mean. '
    'When they ask about the game, squads, SBC, packs, evolutions or events, give a real opinion '
    'or one concrete tip instead of a canned answer. '
    'For real football matches, use only facts supplied in the current conversation '
    'by a verified public match bot. If a score, lineup or live event is not supplied, ask the player to '
    'check the linked match card instead of guessing. Never claim you watched match footage. '
    'Hard lines: never quote prices and never confirm or promise orders, discounts or rewards. '
    'For product prices, point players to the FC Assistant price cards in the FC27 channels; '
    'tapping a card gives a private live quote. For order questions, first point players to '
    'the Check my order button in the FC27 VIP Support channel. If the lookup cannot resolve '
    'their issue, or they need changes or refunds, direct them to Support Ticket or staff. '
    'Never ask for an order number, email or account details in public chat. '
    'No medical, legal, political or financial advice. '
    'If you do not know something, admit it with a bit of humour instead of inventing facts.'
)


class ChatBrainError(Exception):
    pass


def _scrub(text, limit):
    text = re.sub(r'<@[!&]?[0-9]+>', '', text or '')
    text = re.sub(r'<#[0-9]+>', '', text)
    text = re.sub(r'<a?:[A-Za-z0-9_]+:[0-9]+>', '', text)
    text = re.sub(r'https?://\S+', '[link]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit]


def build_messages(user_name, text, history=()):
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    for role, content in list(history)[-MAX_CONTEXT_TURNS:]:
        if role in ('user', 'assistant') and content:
            messages.append({'role': role, 'content': _scrub(content, MAX_INPUT_CHARS)})
    messages.append({'role': 'user', 'content': '{}: {}'.format(user_name, _scrub(text, MAX_INPUT_CHARS))})
    return messages


def _validate_provider(config, label):
    """Validate one provider block. Both Ark and DeepSeek share this shape."""
    if not isinstance(config, dict):
        raise ValueError('Invalid chat {} config.'.format(label))
    if not isinstance(config.get('api_key_env', 'ARK_API_KEY'), str):
        raise ValueError('Invalid chat {} api_key_env.'.format(label))
    model = config.get('model', DEFAULT_MODEL)
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Invalid chat {} model.'.format(label))
    if not isinstance(config.get('base_url', ARK_BASE_URL), str):
        raise ValueError('Invalid chat {} base_url.'.format(label))
    timeout = config.get('timeout_seconds', 12)
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 60:
        raise ValueError('Invalid chat {} timeout.'.format(label))
    temperature = config.get('temperature', 0.8)
    if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError('Invalid chat {} temperature.'.format(label))
    max_tokens = config.get('max_tokens', 120)
    if not isinstance(max_tokens, int) or not 16 <= max_tokens <= 512:
        raise ValueError('Invalid chat {} max_tokens.'.format(label))
    return config


def validate_chat_config(config):
    _validate_provider(config, 'primary')
    fallbacks = config.get('fallbacks', ())
    if not isinstance(fallbacks, (list, tuple)):
        raise ValueError('Invalid chat fallbacks.')
    if len(fallbacks) > MAX_FALLBACKS:
        raise ValueError('Too many chat fallbacks.')
    for item in fallbacks:
        _validate_provider(item, 'fallback')
    return config


class _Provider:
    """One OpenAI-compatible endpoint. Key is read from the environment only."""

    def __init__(self, config, label):
        self.label = label
        self.api_key_env = config.get('api_key_env', 'ARK_API_KEY')
        self.api_key = os.environ.get(self.api_key_env, '')
        self.model = config.get('model', DEFAULT_MODEL)
        self.base_url = config.get('base_url', ARK_BASE_URL).rstrip('/')
        self.timeout = float(config.get('timeout_seconds', 12))
        self.temperature = float(config.get('temperature', 0.8))
        self.max_tokens = int(config.get('max_tokens', 120))
        self.disable_thinking = bool(config.get('disable_thinking', True))

    @property
    def ready(self):
        return bool(self.api_key)

    def payload(self, messages):
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
        }
        if self.disable_thinking:
            payload['thinking'] = {'type': 'disabled'}
        return payload


class ChatBrain:
    def __init__(self, config):
        validate_chat_config(config)
        self.providers = [_Provider(config, 'primary')]
        for index, item in enumerate(config.get('fallbacks', ()), start=1):
            self.providers.append(_Provider(item, 'fallback{}'.format(index)))

    @property
    def ready(self):
        return any(provider.ready for provider in self.providers)

    @property
    def api_key(self):
        return self.providers[0].api_key

    @property
    def model(self):
        return self.providers[0].model

    @property
    def base_url(self):
        return self.providers[0].base_url

    async def _ask(self, provider, messages):
        headers = {'Authorization': 'Bearer ' + provider.api_key, 'Content-Type': 'application/json'}
        timeout = aiohttp.ClientTimeout(total=provider.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    provider.base_url + '/chat/completions',
                    json=provider.payload(messages),
                    headers=headers,
                ) as response:
                    body = await response.text()
                    status = response.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ChatBrainError('network {}'.format(type(exc).__name__))
        if status != 200:
            raise ChatBrainError('http {}'.format(status))
        try:
            data = json.loads(body)
            content = data['choices'][0]['message']['content']
        except (ValueError, KeyError, IndexError, TypeError):
            raise ChatBrainError('bad payload')
        content = _scrub(content, MAX_OUTPUT_CHARS)
        if not content:
            raise ChatBrainError('empty reply')
        return content

    async def reply(self, user_name, text, history=()):
        messages = build_messages(user_name, text, history)
        errors = []
        for provider in self.providers:
            if not provider.ready:
                continue
            try:
                return await self._ask(provider, messages)
            except ChatBrainError as exc:
                errors.append('{}:{}'.format(provider.label, str(exc)))
                continue
        if errors:
            raise ChatBrainError('all providers failed (' + ', '.join(errors) + ')')
        raise ChatBrainError('missing api key')

    async def select_matchday(self, fixtures):
        """One small daily call; the verified fixture card remains the fact source."""
        london = ZoneInfo('Europe/London')
        eastern = ZoneInfo('America/New_York')
        lines = ['{}. {} vs {} | {} | {} London / {} New York'.format(
                 i, f.home, f.away, f.competition,
                 f.kickoff.astimezone(london).strftime('%a %H:%M'),
                 f.kickoff.astimezone(eastern).strftime('%a %H:%M'))
                 for i, f in enumerate(fixtures, start=1)]
        messages = [
            {'role': 'system', 'content': (
                'Choose at most one standout football fixture for an English-speaking '
                'FC27 community in the UK and US. Prefer major European leagues, cups '
                'and national-team matches. Consider whether UK and US fans can join '
                'the discussion at kickoff when fixtures are otherwise comparable. '
                'If none is broadly interesting, return NONE; '
                'never fill a quota. Use only the supplied '
                'fixtures; do not add facts, scores or lineups. Reply exactly NONE or '
                'the fixture number, such as 3. No explanation.')},
            {'role': 'user', 'content': '\n'.join(lines)},
        ]
        for provider in self.providers:
            if provider.ready:
                try:
                    return await self._ask(provider, messages)
                except ChatBrainError:
                    continue
        raise ChatBrainError('matchday selection unavailable')
