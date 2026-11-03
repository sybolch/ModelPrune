#!/usr/bin/env python3
"""Render a deterministic synthetic demo; never reads model stores or private runs."""
import base64
import copy
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import modelprune as m
import report_ui


def demo_data():
    tasks = copy.deepcopy(m.suite())
    for task in tasks:
        # PNG compression varies between zlib implementations. Reuse committed
        # demo assets so documentation output stays byte-identical across hosts.
        if task.get('kind') == 'vision':
            image = (ROOT / 'docs/assets' / (task['id'] + '.png')).read_bytes()
            task['image_b64'] = base64.b64encode(image).decode()
            task['asset_sha256'] = hashlib.sha256(image).hexdigest()
        if task.get('category') in ('code-tracing', 'code-debugging'):
            task['skill'] = 'coding'
    core = ['completion', 'coding', 'tools', 'thinking']
    definitions = [
        ('demo/orbit:8b', core + ['vision', 'audio', 'speech'], '8B', 131072, 0.8, 20),
        ('demo/forge:7b', core, '7B', 65536, 0.55, 35),
        ('demo/orbit:4b', core + ['vision', 'audio', 'speech'], '4B', 131072, 1.1, 100),
        ('demo/iris:3b', core + ['vision'], '3B', 32768, 0.45, 80),
        ('demo/router:1b', ['decision'], '1B', 32768, 0.08, 0),
        ('demo/router:500m', ['decision'], '500M', 32768, 0.12, 90),
    ]
    models, results = [], []
    for name, caps, parameters, context, latency, fail_below in definitions:
        model = dict(name=name, capabilities=caps, context=context,
                     size=4_000_000_000, details=dict(parameter_size=parameters, quantization_level='Q4_K_M'),
                     architecture_type='Dense')
        if name == 'demo/orbit:8b':
            model['aliases'] = [dict(name='demo/orbit-work:8b', context_override=32768)]
        models.append(model)
        for task in tasks:
            if not m.applicable(model, task):
                continue
            passed = hashlib.sha256((name + task['id']).encode()).digest()[0] >= fail_below
            results.append(dict(model=name, task=task['id'], repeat=0, level=task['level'],
                                points=task['level'] if passed else 0, kind=task['kind'],
                                category=task['category'], seconds=round(latency * (1 + task['level'] * .2), 3),
                                note='SYNTHETIC DEMO. No inference or framework evaluation was performed.'))
    return dict(created='Illustrative preview', ollama_version='demo', host='Not connected',
                config=dict(repeats=1, seed=42), hardware={'note': 'Synthetic demo; no hardware inspected'},
                models=models, tasks=tasks, results=results,
                run_control=dict(url='', token='', start_command='Install ModelPrune to enable controls'))


def make_preview():
    data = demo_data()
    rows = m.aggregate(data)
    page = report_ui.render(data, rows, m.recommendations(data, rows))
    # Keep the actual report layout but never connect a preview to a runtime.
    page = page.replace('<script>' + __import__('report_control').SCRIPT + '</script>', '')
    page = page.replace('<button id="run-', '<button disabled aria-disabled="true" id="run-')
    page = page.replace('Connecting to local benchmark service…', 'Demo only — install ModelPrune to run discovery and benchmarks.')
    page = page.replace(' evaluations', ' illustrative task outcomes')
    page = page.replace('Legacy or unverified isolation: rerun with the current benchmark protocol before trusting comparisons.',
                        'Synthetic interface preview. No models were loaded and no evaluation was performed.')
    page = page.replace('<title>ModelPrune report</title>', '<title>ModelPrune — synthetic preview</title>')
    banner = '<aside style="padding:12px 16px;border:1px solid #8ee8bf;border-radius:8px;margin-bottom:24px;color:#8ee8bf"><strong>Illustrative demo</strong> · Fictional models and synthetic scores. Not benchmark results.</aside>'
    page = page.replace('<h1>ModelPrune</h1>', banner + '<h1>ModelPrune</h1>')
    page = page.replace('</style>', 'body::after{content:"ILLUSTRATIVE DEMO · NOT BENCHMARK RESULTS";position:fixed;bottom:12px;right:16px;background:#101621ed;border:1px solid #52637e;border-radius:6px;padding:8px 12px;font:11px system-ui;color:#8ee8bf;z-index:20}</style>', 1)
    return '\n'.join(line.rstrip() for line in page.splitlines()).rstrip() + '\n'


if __name__ == '__main__':
    destination = ROOT / 'docs/preview.html'
    destination.write_text(make_preview())
    print('Wrote docs/preview.html (synthetic data; no inference)')
