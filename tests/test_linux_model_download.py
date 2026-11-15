"""Download contract using the real model verifier and synthetic model bytes."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.request import Request

from installer import linux_server

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('linux_download_engine',ROOT/'server-windows/linux/install_server.py')
engine=importlib.util.module_from_spec(spec)
with mock.patch.object(sys,'path',[str(ROOT/'server-windows/linux'),*sys.path]):
    spec.loader.exec_module(engine)


class ModelDownloadTests(unittest.TestCase):
    def test_all_shipped_model_sources_are_supported_with_scoped_credentials(self):
        entries=json.loads((ROOT/'server-windows/audio-files.json').read_text())
        entries += [entry for model in json.loads((ROOT/'server-windows/models.json').read_text()).values()
                    for entry in model['files']]
        for entry in entries:
            with self.subTest(path=entry['path']):
                request=linux_server.model_request(entry,'synthetic-token')
                self.assertEqual(entry['url'],request.full_url)
                expected='Bearer synthetic-token' if request.host=='huggingface.co' else None
                self.assertEqual(expected,request.get_header('Authorization'))

    def test_unexpected_model_source_is_rejected(self):
        for url in ('http://huggingface.co/model','https://huggingface.co.evil.invalid/model',
                    'https://huggingface.co@evil.invalid/model',
                    'https://openaipublic.azureedge.net/unexpected-model'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                linux_server.model_request({'url':url,'path':'whisper/large-v3.pt'},'synthetic-token')

    def test_redirect_keeps_credentials_only_on_same_https_origin(self):
        handler=linux_server.ModelRedirectHandler()
        req=Request('https://huggingface.co/model',headers={'Authorization':'Bearer synthetic-token'})
        same=handler.redirect_request(req,None,302,'',{},'https://huggingface.co/file')
        other=handler.redirect_request(req,None,302,'',{},'https://cdn.synthetic.invalid/file')
        port=handler.redirect_request(req,None,302,'',{},'https://huggingface.co:8443/file')
        self.assertEqual('Bearer synthetic-token',same.get_header('Authorization'))
        self.assertIsNone(other.get_header('Authorization'))
        self.assertIsNone(port.get_header('Authorization'))
        for url in ('http://huggingface.co/file','file:///tmp/model','https://user@host.invalid/file'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                handler.redirect_request(req,None,302,'',{},url)

    def test_download_verifies_content_and_reuses_valid_model(self):
        data=b'synthetic model bytes'
        entry=dict(path='whisper/large-v3.pt',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        entry['url']='https://openaipublic.azureedge.net/main/whisper/models/'+entry['sha256']+'/large-v3.pt'
        with tempfile.TemporaryDirectory() as directory,mock.patch.dict(sys.modules,{'install_server':engine}):
            target=Path(directory)/'large-v3.pt'
            opener=mock.Mock();opener.open.return_value=io.BytesIO(data)
            with mock.patch.object(linux_server.urllib.request,'build_opener',return_value=opener):
                linux_server.download(entry,target,'synthetic-token')
                self.assertEqual(data,target.read_bytes())
                self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))
            with mock.patch.object(linux_server.urllib.request,'build_opener',side_effect=AssertionError('No network expected')):
                linux_server.download(entry,target,'synthetic-token')
            self.assertEqual([target],list(Path(directory).iterdir()))

    def test_bad_download_preserves_existing_file_and_cleans_temporary_file(self):
        entry=dict(path='model.bin',url='https://huggingface.co/model',bytes=3,
                   sha256=hashlib.sha256(b'new').hexdigest())
        with tempfile.TemporaryDirectory() as directory,mock.patch.dict(sys.modules,{'install_server':engine}):
            target=Path(directory)/'model.bin';target.write_bytes(b'old')
            opener=mock.Mock();opener.open.return_value=io.BytesIO(b'bad')
            with mock.patch.object(linux_server.urllib.request,'build_opener',return_value=opener):
                with self.assertRaisesRegex(ValueError,'Prüfsumme'):
                    linux_server.download(entry,target,'synthetic-token')
            self.assertEqual(b'old',target.read_bytes())
            self.assertEqual([target],list(Path(directory).iterdir()))


if __name__=='__main__':unittest.main()
