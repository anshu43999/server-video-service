"""Frozen M111 v1 shapes; dependency-free validation of this bounded schema.

Only keywords used by contract-v1.schema.json are supported. Unknown keywords
fail closed, so extending the schema cannot silently weaken validation.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

SCHEMA = json.loads(Path(__file__).with_name('contract-v1.schema.json').read_text(encoding='utf-8'))
MAX_INTEGER = 9007199254740991
ITEM_BYTES = 32 * 1024
PAGE_BYTES = 1024 * 1024
TERMINAL = {'installed', 'blocked', 'quarantined', 'rolled_back', 'invalidated', 'superseded'}
WAITING = {'available', 'waiting_user', 'waiting_project', 'waiting_network', 'waiting_storage',
           'waiting_idle', 'retry_wait'}
FLOW = {'downloading': {'verifying', 'retry_wait', 'waiting_user'},
        'verifying': {'staged', 'blocked'}, 'staged': {'warming', 'waiting_idle'},
        'warming': {'committing', 'blocked', 'waiting_idle'}, 'committing': {'installed', 'blocked'},
        'installed': {'quarantined', 'rolled_back'}, 'quarantined': {'rolled_back'}}


class UpdateError(Exception):
    def __init__(self, status, code, retry_after=None):
        self.status, self.code, self.retry_after = status, code, retry_after
        super().__init__(code)

    def payload(self):
        return {'messageType': 'error', 'contractVersion': 1, 'status': self.status,
                'errorCode': self.code, 'retryAfterSeconds': self.retry_after}


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def timestamp(value=None):
    return utc(value or now()).isoformat().replace('+00:00', 'Z')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode('utf-8')).hexdigest()


def source_identity(source):
    return digest({key: value for key, value in source.items() if key not in {'sourceEpoch', 'selection'}})


def byte_size(value):
    return len(canonical(value).encode('utf-8'))


def _matches(value, schema):
    try:
        _validate(value, schema)
        return True
    except ValueError:
        return False


def _validate(value, schema):
    supported = {'$ref', 'type', 'properties', 'required', 'additionalProperties', 'const', 'enum',
                 'minimum', 'maximum', 'minLength', 'maxLength', 'pattern', 'format', 'items',
                 'minItems', 'maxItems', 'uniqueItems', 'allOf', 'oneOf', 'anyOf', 'if', 'then', 'else',
                 'not', 'dependentRequired'}
    if set(schema) - supported:
        raise RuntimeError('unsupported update schema keyword')
    if '$ref' in schema:
        _validate(value, SCHEMA['$defs'][schema['$ref'].removeprefix('#/$defs/')])
    types = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list),
             'string': lambda x: isinstance(x, str), 'integer': lambda x: type(x) is int,
             'boolean': lambda x: type(x) is bool, 'null': lambda x: x is None}
    if 'type' in schema and not types[schema['type']](value):
        raise ValueError('type')
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise ValueError('const')
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        raise ValueError('enum')
    if isinstance(value, dict):
        if any(key not in value for key in schema.get('required', [])):
            raise ValueError('required')
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            raise ValueError('unknown field')
        for key in value.keys() & properties.keys():
            _validate(value[key], properties[key])
        for key, required in schema.get('dependentRequired', {}).items():
            if key in value and any(field not in value for field in required):
                raise ValueError('dependentRequired')
    if isinstance(value, str):
        value.encode('utf-8', errors='strict')
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', float('inf')):
            raise ValueError('length')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise ValueError('pattern')
        if schema.get('format') == 'date-time':
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d(?:\.\d{1,6})?Z', value):
                raise ValueError('UTC timestamp')
            datetime.fromisoformat(value.replace('Z', '+00:00'))
    if type(value) is int and not schema.get('minimum', -float('inf')) <= value <= schema.get('maximum', float('inf')):
        raise ValueError('number')
    if isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', float('inf')):
            raise ValueError('count')
        if schema.get('uniqueItems') and len({canonical(item) for item in value}) != len(value):
            raise ValueError('duplicate')
        for item in value:
            _validate(item, schema.get('items', {}))
    for branch in schema.get('allOf', []):
        _validate(value, branch)
    if 'oneOf' in schema and sum(_matches(value, item) for item in schema['oneOf']) != 1:
        raise ValueError('oneOf')
    if 'anyOf' in schema and not any(_matches(value, item) for item in schema['anyOf']):
        raise ValueError('anyOf')
    if 'if' in schema:
        _validate(value, schema.get('then' if _matches(value, schema['if']) else 'else', {}))
    if 'not' in schema and _matches(value, schema['not']):
        raise ValueError('not')


def validate(value, definition):
    try:
        _validate(value, SCHEMA['$defs'][definition])
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise UpdateError(400, 'invalid_request') from None
    return value


def response(kind, **fields):
    result = dict(messageType=kind, contractVersion=1, **fields)
    validate(result, kind)
    if byte_size(result) > PAGE_BYTES:
        raise UpdateError(413, 'capacity_exceeded')
    return result


def valid_transition(previous, current):
    if previous == current:
        return True
    if current in {'invalidated', 'superseded'}:
        return previous not in {'invalidated', 'superseded'}
    # A device may commit offline and only later report its final fact. The
    # server still verifies exact target/criteria and monotonically increasing
    # reportSeq; network delivery of each intermediate stage is not a precondition.
    stages = ['available', 'downloading', 'verifying', 'staged', 'warming', 'committing', 'installed']
    if current in stages[1:]:
        start = 'available' if previous in WAITING else previous
        if start in stages and stages.index(current) > stages.index(start):
            return True
    if previous in WAITING:
        return current in WAITING | {'downloading', 'blocked'}
    return current in FLOW.get(previous, set())


def target_digest(target):
    return digest({key: value for key, value in target.items()
                   if key not in {'updateId', 'targetDigest', 'supersedesUpdateId'}})
