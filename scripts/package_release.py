"""Create a local review package from an explicit source-only allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('README.md','LICENSE','THIRD_PARTY_NOTICES.md','.gitignore','.env.example',
       'requirements.txt','requirements.lock','requirements.linux.lock','run.ps1')
FOLDERS=('src','tests','scripts','data/fixtures')
SECRET=re.compile(rb'tvly-[A-Za-z0-9_-]{24,}|lsv2_pt_[A-Za-z0-9_]{24,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----')


def package(destination):
    from dotenv import dotenv_values
    destination=Path(destination).resolve()
    if not destination.is_relative_to(ROOT.parent/'deliverables'):
        raise ValueError('Release packages must stay inside this event deliverables directory.')
    selected=[ROOT/name for name in FILES]
    selected += [p for name in FOLDERS for p in (ROOT/name).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.cjs','.js','.html','.css','.json','.md','.png')]
    selected += [ROOT/'deployment/vps/Dockerfile']
    payload={}
    local_secrets=[str(value).encode() for name,value in dotenv_values(ROOT/'.env').items()
                   if value and name.endswith(('_KEY','_TOKEN','_SECRET')) and len(str(value))>=12]
    for path in sorted(set(selected)):
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('Package source must be a regular application file: '+str(path.relative_to(ROOT)))
        body=path.read_bytes()
        if SECRET.search(body) or any(value in body for value in local_secrets):
            raise ValueError('Credential-like content in '+str(path.relative_to(ROOT)))
        payload[path.relative_to(ROOT).as_posix()]=body
    manifest={name:hashlib.sha256(body).hexdigest() for name,body in payload.items()}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,body in payload.items():archive.writestr('price-alert-investigator/'+name,body)
        archive.writestr('price-alert-investigator/SOURCE_MANIFEST.json',json.dumps(manifest,indent=2))
    # Verify exact contents after writing; no .env, runtime state, captures or credentials.
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())=={'price-alert-investigator/'+n for n in (*manifest,'SOURCE_MANIFEST.json')}
        for name,digest in manifest.items():
            assert hashlib.sha256(archive.read('price-alert-investigator/'+name)).hexdigest()==digest
    return {'path':str(destination),'files':len(manifest),'bytes':destination.stat().st_size,
            'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'manifest':manifest}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT.parent/'deliverables/price-alert-investigator-source.zip'))
    report=package(parser.parse_args().output)
    print(json.dumps({k:v for k,v in report.items() if k!='manifest'},indent=2))
