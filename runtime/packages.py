"""Pure package parsing. Never import or execute handler source in the control plane."""
import ast
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ID = r'[a-z][a-z0-9-]{1,47}'
VERSION = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
ALIASES = {'python': 'python', 'read_file': 'read-file', 'write_file': 'write-file'}


def reference(value):
    if isinstance(value, str) and value in ALIASES:
        return {'id': ALIASES[value], 'version': '1.0.0'}
    if not isinstance(value, dict) or set(value) != {'id', 'version'}:
        raise ValueError('A tool reference requires id and version.')
    if not re.fullmatch(ID, str(value['id'])) or not re.fullmatch(VERSION, str(value['version'])):
        raise ValueError('Invalid tool ID or semantic version.')
    return dict(value)


def validate_schema(schema):
    if not isinstance(schema, dict) or schema.get('type') != 'object':
        raise ValueError('Input/output schemas must describe a JSON object.')
    # No references or executable schema extensions in v1. Validation never fetches URLs.
    def check(node, depth=0):
        if depth > 20:
            raise ValueError('Schema exceeds the nesting limit.')
        if isinstance(node, dict):
            if any(key in node for key in ('$ref', '$dynamicRef', '$recursiveRef')):
                raise ValueError('Schema references are not supported in Tool Package v1.')
            for item in node.values():
                check(item, depth + 1)
        elif isinstance(node, list):
            for item in node:
                check(item, depth + 1)
    check(schema)
    Draft202012Validator.check_schema(schema)


def validate_package(package):
    if not isinstance(package, dict) or set(package) != {'manifest', 'handler', 'tests'}:
        raise ValueError('Package requires manifest, handler, and tests.')
    if len(json.dumps(package).encode()) > 100_000:
        raise ValueError('Package exceeds 100 KB.')
    m = package['manifest']
    required = {'format_version', 'id', 'version', 'name', 'description', 'runtime', 'entrypoint',
                'input_schema', 'output_schema', 'limits'}
    if not isinstance(m, dict) or set(m) != required:
        raise ValueError('Manifest fields do not match Tool Package v1.')
    reference({'id': m['id'], 'version': m['version']})
    if m['format_version'] != 1 or m['runtime'] != 'python' or m['entrypoint'] != 'handler.py:run':
        raise ValueError('Supported format: version 1, Python, handler.py:run.')
    if not isinstance(m['name'], str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,63}', m['name']):
        raise ValueError('Tool name must be a function identifier of at most 64 characters.')
    if not isinstance(m['description'], str) or not 1 <= len(m['description']) <= 2000:
        raise ValueError('Description must contain 1–2000 characters.')
    limits = m['limits']
    if not isinstance(limits, dict) or set(limits) != {'timeout_seconds', 'max_output_bytes'}:
        raise ValueError('Limits require timeout_seconds and max_output_bytes.')
    if type(limits['timeout_seconds']) is not int or not 1 <= limits['timeout_seconds'] <= 30:
        raise ValueError('Tool timeout must be between 1 and 30 seconds.')
    if type(limits['max_output_bytes']) is not int or not 128 <= limits['max_output_bytes'] <= 32000:
        raise ValueError('Tool output limit must be between 128 and 32000 bytes.')
    for field in ('input_schema', 'output_schema'):
        validate_schema(m[field])
    source = package['handler']
    if not isinstance(source, str) or not 1 <= len(source.encode()) <= 32000 or '\x00' in source:
        raise ValueError('Handler source must be UTF-8 text of at most 32 KB without NUL bytes.')
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError) as exc:
        raise ValueError('Handler source is not valid Python.') from exc
    if not any(isinstance(n, ast.FunctionDef) and n.name == 'run' for n in tree.body):
        raise ValueError('Handler must define run(arguments, context).')
    tests = package['tests']
    if not isinstance(tests, list) or not 1 <= len(tests) <= 10:
        raise ValueError('Provide between 1 and 10 test fixtures.')
    for fixture in tests:
        if not isinstance(fixture, dict) or set(fixture) != {'name', 'arguments', 'expected', 'files'}:
            raise ValueError('A fixture requires name, arguments, expected, and files.')
        if not isinstance(fixture['name'], str) or not 1 <= len(fixture['name']) <= 100:
            raise ValueError('Fixture names require 1–100 characters.')
        Draft202012Validator(m['input_schema']).validate(fixture['arguments'])
        Draft202012Validator(m['output_schema']).validate(fixture['expected'])
        if not isinstance(fixture['files'], dict) or len(fixture['files']) > 10:
            raise ValueError('Each fixture supports up to 10 text input files.')
        for path, content in fixture['files'].items():
            if not re.fullmatch(r'[a-zA-Z0-9_./-]{1,150}', path) or path.startswith('/') or '..' in path.split('/'):
                raise ValueError('Fixture file paths must be relative and stay in the workspace.')
            if not isinstance(content, str) or len(content.encode()) > 32000 or '\x00' in content:
                raise ValueError('Fixture files must be UTF-8 text of at most 32 KB.')
    return package


def digest(package):
    return hashlib.sha256(json.dumps(package, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def read_folder(folder):
    folder = Path(folder)
    names = {'tool.json', 'handler.py', 'tests.json'}
    for name in names:
        path = folder / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
            raise ValueError(f'Missing, linked, or oversized package file: {name}')
    return validate_package({'manifest': json.loads((folder / 'tool.json').read_text()),
                             'handler': (folder / 'handler.py').read_text(),
                             'tests': json.loads((folder / 'tests.json').read_text())})


def definitions(packages):
    return [{'type': 'function', 'function': {'name': p['manifest']['name'],
            'description': p['manifest']['description'], 'parameters': p['manifest']['input_schema']}} for p in packages]


def validate_arguments(package, arguments):
    try:
        Draft202012Validator(package['manifest']['input_schema']).validate(arguments)
    except ValidationError as exc:
        raise ValueError('Tool arguments do not match the input schema: ' + exc.message[:200]) from None
