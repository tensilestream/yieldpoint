"""Reproducible size comparison; no model calls or claimed provider savings."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yieldpoint.context import compact_json


def main():
    fixtures = {
        'search-results': {'results': [{'path': f'src/module_{i}.py', 'line': i + 1,
                                      'text': '    assert invoice.total == 42'} for i in range(100)]},
        'mcp-error': {'isError': True, 'content': [{'type': 'text', 'text': 'Missing permission.\nRetry only after authorization.'}]},
        'code-string': {'source': 'def test_total(inv):\n    assert inv.total == 42\n' * 30},
    }
    rows = []
    for name, value in fixtures.items():
        for indent in (None, 2):
            source = json.dumps(value, indent=indent, ensure_ascii=False,
                                separators=(',', ':') if indent is None else None)
            result = compact_json(source)
            if json.loads(result.text) != value:
                raise AssertionError(f'{name}: data changed')
            rows.append({'fixture': name, 'pretty': indent is not None, **result.metrics(),
                         'estimated_tokens_removed': result.input_tokens - result.output_tokens})
    print(json.dumps({'basis': 'Generated payloads, 4 chars/token estimate; not billed savings',
                      'results': rows}, indent=2))


if __name__ == '__main__':
    main()
