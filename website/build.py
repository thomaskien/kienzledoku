"""Build the homepage overlay without changing benchmark/GPU content."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True, type=Path, help='Complete existing static website')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    repo = source.parent
    baseline, output = args.baseline.resolve(), args.output.resolve()
    if baseline == output or baseline in output.parents or output in baseline.parents:
        parser.error('Baseline and output must be separate directories.')
    required = ['index.html','benchmarks.html','grafikkarten.html','assets/site.css','assets/site.js']
    for name in required:
        if not (baseline/name).is_file():
            parser.error('Missing baseline file: ' + name)
    before = {str(p.relative_to(baseline)):digest(p) for p in baseline.rglob('*') if p.is_file()}
    shutil.copytree(baseline, output, dirs_exist_ok=True)
    shutil.copy2(source/'index.html', output/'index.html')
    shutil.copytree(source/'assets', output/'assets', dirs_exist_ok=True)
    for name in ['kienzledoku-record.jpg','ki-ablauf.svg','pegel.png']:
        shutil.copy2(repo/'docs/images'/name, output/'assets'/name)
    shutil.copy2(repo/'bootstrap/install_linux.sh', output/'install_linux.sh')
    gpu = (baseline/'grafikkarten.html').read_text()
    old_notice = '<h3>Aktuelle Version und Modellwahl</h3><p><strong>Kienzledoku 1.3.1 setzt noch eine Grafikkarte mit 24 GB Grafikspeicher voraus.</strong> Die Übersicht enthält auch Karten für den neueren seriellen Betrieb ab 8 GB sowie passend konfigurierte, parallel geladene Modelle ab 16 GB.</p>'
    new_notice = '<h3>Modellwahl und Installationsstand</h3><p>Die Anforderungen richten sich nach Modell und Betriebsart: serieller Modellwechsel ab <strong>8 GB Grafikspeicher</strong> oder bei passender Modellauswahl parallel geladene Modelle ab 16 GB. Die gemeinsamen Installer werden nach Freigabe auf GitHub bereitgestellt. <a href="https://github.com/thomaskien/kienzledoku/blob/main/docs/installation.md">Aktuelle Installationshinweise ↗</a></p>'
    if gpu.count(old_notice) == 1 and new_notice not in gpu:
        (output/'grafikkarten.html').write_text(gpu.replace(old_notice, new_notice))
    else:
        assert old_notice not in gpu and gpu.count(new_notice) == 1, 'GPU baseline notice changed; review before replacing.'
    css_hash = digest(output/'assets/homepage.css')[:12]
    html = (output/'index.html').read_text().replace('/assets/homepage.css"', '/assets/homepage.css?v='+css_hash+'"')
    html = html.replace('/assets/ki-ablauf.svg"', '/assets/ki-ablauf.svg?v='+digest(output/'assets/ki-ablauf.svg')[:12]+'"')
    (output/'index.html').write_text(html)
    after = {str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    changed = [name for name in before if name != 'SHA256SUMS' and before[name] != after.get(name)]
    allowed_changes = {'index.html','assets/homepage.css','assets/ki-ablauf.svg','grafikkarten.html'}
    assert set(changed) <= allowed_changes, changed
    for name in before:
        if name not in allowed_changes | {'SHA256SUMS'}:
            assert before[name] == after[name], name
    (output/'SHA256SUMS').write_text(''.join(value+'  '+name+'\n' for name,value in sorted(after.items())))
    report = {'changed_existing_files':changed,'new_files':sorted(set(after)-set(before)),
              'benchmarks_gpu_tables_filters_and_shared_assets_unchanged':True, 'file_count':len(after)+1}
    (output.parent/'build-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
