"""Check the staged homepage, documentation links and preserved baseline content."""
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import re
import sys
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=[]; self.urls=[]; self.videos=[]; self.scripts=[]
    def handle_starttag(self, tag, attrs):
        data=dict(attrs)
        if 'id' in data:self.ids.append(data['id'])
        if 'data-video-id' in data:self.videos.append(data['data-video-id'])
        for attr in ['src','href']:
            if attr in data:self.urls.append(data[attr])
        if tag=='script':self.scripts.append(data.get('src'))


def main():
    site=Path(sys.argv[1]).resolve();repo=Path(__file__).resolve().parents[1]
    page=Page();page.feed((site/'index.html').read_text())
    assert len(page.ids)==len(set(page.ids)), 'Duplicate IDs'
    sections=['aufmacher','download','videos','hardware','ablauf','pegel']
    assert [page.ids.index(x) for x in sections]==sorted(page.ids.index(x) for x in sections)
    assert page.videos==['RlPRxwvj6ks','_Mn_QjbPdmc','09TLE3R1GjU','spvwjsQWLHA','k0Zndclce9A','-isFceLORfQ','6l1U047NSwg']
    for url in page.urls:
        target=urlsplit(url)
        if target.scheme or target.netloc:continue
        if target.path:
            local=site/unquote(target.path.lstrip('/'))
            if local.is_dir():local=local/'index.html'
            assert local.is_file(),url
        elif target.fragment:assert target.fragment in page.ids,url
    assert not re.search(r'<iframe', (site/'index.html').read_text()), 'YouTube loaded before click'
    assert (site/'install_linux.sh').read_bytes()==(repo/'bootstrap/install_linux.sh').read_bytes()
    for name in ['kienzledoku-record.jpg','ki-ablauf.svg','pegel.png']:
        assert (site/'assets'/name).read_bytes()==(repo/'docs/images'/name).read_bytes()
    docs=[repo/'README.md',*(repo/'docs').glob('*.md'),*(repo/'docs/archiv').glob('*.md')]
    owned={'README.md','docs/installation.md','docs/t2med.md','docs/bedienung.md','docs/technik.md','docs/archiv/direktbetrieb.md','docs/archiv/readme-vor-2026-11-15.md'}
    for p in docs:
        if str(p.relative_to(repo)) not in owned:continue
        targets=re.findall(r'\]\(([^)]+)\)',p.read_text())+re.findall(r'<img[^>]*src="([^"]+)"',p.read_text())
        for url in targets:
            target=urlsplit(url)
            if target.scheme or target.netloc or not target.path:continue
            dest=p.parent/unquote(target.path)
            assert dest.is_file(),(p,url)
            if target.fragment and dest.suffix=='.md':
                headings=re.findall(r'^#{1,6} (.+)$',dest.read_text(),re.M)
                anchors=[re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in headings]
                assert unquote(target.fragment) in anchors,(p,url,anchors)
    for line in (site/'SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ',1)
        assert hashlib.sha256((site/name).read_bytes()).hexdigest()==digest,name
    print('PASS: section order, seven videos, lazy player, local links, shared images, documentation links/anchors and all asset checksums')


if __name__=='__main__':main()
