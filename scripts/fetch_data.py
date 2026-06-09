#!/usr/bin/env python3
"""
Fetch model data from AA, NVIDIA, and save to data/ as static JSON.
Run locally or via GitHub Actions.
"""
import json, re, os, sys, datetime, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; model-leaderboard-fetcher/1.0)',
    'Accept': 'text/html,application/xhtml+xml,application/json,*/*;q=0.9',
    'Accept-Language': 'en-US,en;q=0.9',
}


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


def match_brace(s, start):
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1


def parse_aa(html):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    if not chunks:
        raise ValueError('No RSC chunks found in AA HTML')
    raw = ''.join(chunks)
    unescaped = json.loads('"' + raw.replace('\\$', '$') + '"')

    models = []
    seen = set()
    for i in range(len(unescaped)):
        if unescaped[i] != '{':
            continue
        end = match_brace(unescaped, i)
        if end < 0:
            continue
        slice_ = unescaped[i:end + 1]
        if '"intelligenceIndex"' not in slice_:
            continue
        try:
            obj = json.loads(slice_)
            if not (obj and obj.get('name') and obj.get('slug') and obj.get('intelligenceIndex') is not None):
                continue
            creator_slug = ''
            if isinstance(obj.get('model_creator'), dict):
                creator_slug = obj['model_creator'].get('slug', '')
            key = f"{obj['slug']}|{creator_slug}"
            if key in seen:
                continue
            seen.add(key)

            clean = lambda v: None if v == '$undefined' else v
            m = {k: clean(v) for k, v in obj.items()}
            models.append({
                'name': m.get('name'),
                'slug': m.get('slug'),
                'creator': m.get('modelCreatorName') or m.get('modelCreatorSlug'),
                'intelligenceIndex': m.get('intelligenceIndex'),
                'codingIndex': m.get('codingIndex'),
                'agenticIndex': m.get('agenticIndex'),
                'medianOutputTokensPerSecond': m.get('medianOutputTokensPerSecond'),
                'medianTimeToFirstTokenSeconds': m.get('medianTimeToFirstTokenSeconds'),
                'blendedUsdPer1M': m.get('price1mBlended3To1'),
                'contextWindow': m.get('contextWindowTokens'),
                'releaseDate': m.get('releaseDate'),
                'openrouterApiId': m.get('openrouterApiId'),
                'isOpenWeights': m.get('isOpenWeights'),
            })
        except Exception:
            pass
    return models


def parse_nvidia_page(html):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    if not chunks:
        return []
    raw = ''.join(chunks)
    try:
        unescaped = json.loads('"' + raw.replace('\\$', '$') + '"')
    except Exception:
        return []

    results = []
    seen_keys = set()

    for i in range(len(unescaped) - 20):
        if unescaped[i] != '{':
            continue
        peek = unescaped[i:i + 60]
        if '"resourceType"' not in peek:
            continue
        end = match_brace(unescaped, i)
        if end < 0:
            continue
        slice_ = unescaped[i:end + 1]
        if '"ENDPOINT"' not in slice_:
            continue
        dedup_key = slice_[:80]
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        try:
            obj = json.loads(slice_)
            if obj.get('resourceType') != 'ENDPOINT':
                continue
            name = obj.get('name')
            if not name:
                continue
            labels = obj.get('labels', [])
            publisher = ''
            is_free = False
            for lbl in labels:
                if lbl.get('key') == 'publisher' and lbl.get('unresolvedValues'):
                    publisher = lbl['unresolvedValues'][0]
                if lbl.get('key') == 'nimType' and 'nim_type_preview' in lbl.get('unresolvedValues', []):
                    is_free = True
            full_id = f'{publisher}/{name}' if publisher else name
            results.append({'id': full_id, 'name': name, 'isFree': is_free})
        except Exception:
            pass

    return results


def main():
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    # ── AA ──
    print('Fetching AA leaderboard (~3 MB)…', flush=True)
    try:
        aa_html = fetch('https://artificialanalysis.ai/leaderboards/models')
        aa_models = parse_aa(aa_html)
        print(f'  Parsed {len(aa_models)} models')
    except Exception as e:
        print(f'  ERROR: {e}', file=sys.stderr)
        aa_models = []

    with open(os.path.join(DATA_DIR, 'aa-models.json'), 'w') as f:
        json.dump({'fetchedAt': now, 'models': aa_models}, f, separators=(',', ':'))
    print(f'  Saved data/aa-models.json  ({len(aa_models)} rows)')

    # ── NVIDIA API ──
    print('Fetching NVIDIA NIM model list…', flush=True)
    try:
        nv_raw = fetch('https://integrate.api.nvidia.com/v1/models')
        nv_api = json.loads(nv_raw)
        nv_api_ids = [m['id'] for m in nv_api.get('data', [])]
        print(f'  Got {len(nv_api_ids)} models from API')
    except Exception as e:
        print(f'  ERROR: {e}', file=sys.stderr)
        nv_api_ids = []

    # ── NVIDIA page (free endpoint info) ──
    print('Fetching build.nvidia.com page…', flush=True)
    try:
        nv_page_html = fetch('https://build.nvidia.com/models')
        nv_page_models = parse_nvidia_page(nv_page_html)
        nv_free_ids = list({m['id'] for m in nv_page_models if m['isFree']} |
                           {m['name'] for m in nv_page_models if m['isFree']})
        print(f'  Got {len(nv_page_models)} ENDPOINT objects, {len(nv_free_ids)} free IDs')
    except Exception as e:
        print(f'  ERROR: {e}', file=sys.stderr)
        nv_free_ids = []

    with open(os.path.join(DATA_DIR, 'nvidia-models.json'), 'w') as f:
        json.dump({
            'fetchedAt': now,
            'apiModels': nv_api_ids,
            'freeIds': nv_free_ids,
        }, f, separators=(',', ':'))
    print(f'  Saved data/nvidia-models.json')

    print(f'\nAll done. fetchedAt={now}')


if __name__ == '__main__':
    main()
