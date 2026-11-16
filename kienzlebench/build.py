"""Build three standalone executables; never overwrite a delivered version."""
import argparse, hashlib, json, os, pathlib, re, subprocess

root = pathlib.Path(__file__).resolve().parent
version=re.search(r'const version = "([^"]+)"',(root/'src/app.go').read_text()).group(1)
if '<title>Kienzlebench '+version+'</title>' not in (root/'src/assets/index.html').read_text():raise SystemExit('UI-Version stimmt nicht mit Programmversion überein')
p=argparse.ArgumentParser();p.add_argument('--go',default='go');p.add_argument('--output',type=pathlib.Path,default=root/'dist'/version);args=p.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
targets=[('darwin','arm64',f'Kienzlebench-{version}-macOS.command'),('linux','amd64',f'Kienzlebench-{version}-Linux'),('windows','amd64',f'Kienzlebench-{version}-Windows.exe')]
for _,_,name in targets:
    if (args.output/name).exists():raise SystemExit('Vorhandenes Artefakt bleibt unverändert: '+name)
metadata={'version':version,'go':subprocess.check_output([args.go,'version'],text=True).strip(),'files':[]}
for system,arch,name in targets:
    env=dict(os.environ,GOOS=system,GOARCH=arch,CGO_ENABLED='0',GOCACHE='/private/tmp/kienzlebench-go-cache')
    target=args.output/name
    flags='-s -w -buildid=' + (' -H windowsgui' if system=='windows' else '')
    subprocess.run([args.go,'build','-trimpath','-buildvcs=false','-ldflags',flags,'-o',str(target),'.'],cwd=root/'src',env=env,check=True)
    target.chmod(0o755)
    if system=='darwin':subprocess.run(['/usr/bin/codesign','--force','--sign','-','--identifier','de.kienzle.kienzlebench',str(target)],check=True)
    metadata['files'].append(dict(file=name,os=system,arch=arch,bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
(args.output/'build-manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
(args.output/'SHA256SUMS.txt').write_text(''.join(x['sha256']+'  '+x['file']+'\n' for x in metadata['files']))
print(json.dumps(metadata,indent=2))
