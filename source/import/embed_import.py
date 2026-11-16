"""Embed pinned local import readers before the app script; no CDN requests."""
from pathlib import Path
import argparse,base64,hashlib,json
ROOT=Path(__file__).resolve().parent
def make_block():
    vendor=ROOT/'vendor';pdf=vendor/'pdfjs/package';mammoth=vendor/'mammoth/package'
    encode=lambda p:base64.b64encode(p.read_bytes()).decode('ascii')
    assets={'mammoth':encode(mammoth/'mammoth.browser.min.js'),'pdf':encode(pdf/'legacy/build/pdf.min.mjs'),'pdfWorker':encode(pdf/'legacy/build/pdf.worker.min.mjs'),'cmaps':{p.name:encode(p) for p in sorted((pdf/'cmaps').glob('*.bcmap'))},'fonts':{p.name:encode(p) for p in sorted((pdf/'standard_fonts').glob('*')) if p.suffix in ('.pfb','.ttf')}}
    licenses='Mammoth 1.13.0\n'+(mammoth/'LICENSE').read_text()+'\nPDF.js 6.5.438\n'+(pdf/'LICENSE').read_text()
    return '<!-- REWIND_LOCAL_IMPORT_BEGIN -->\n<!-- '+'\n'.join(line.rstrip() for line in licenses.replace('--','—').splitlines())+' -->\n<script>\nconst REWIND_IMPORT_ASSETS='+json.dumps(assets,separators=(',',':'))+';\n'+(ROOT/'file-import.js').read_text(encoding='utf-8').replace('</script','<\\/script')+'\n</script>\n<!-- REWIND_LOCAL_IMPORT_END -->\n'
def embed(source,destination):
    import re
    text=Path(source).read_text(encoding='utf-8');text=re.sub(r'<!-- REWIND_LOCAL_IMPORT_BEGIN -->.*?<!-- REWIND_LOCAL_IMPORT_END -->\n?','',text,flags=re.S)
    # Place readers before any app code. Assets stay inert until import is used.
    text=text.replace('</head>',make_block()+'</head>',1)
    Path(destination).write_text(text,encoding='utf-8')
    print(json.dumps({'path':str(destination),'bytes':len(text.encode()),'sha256':hashlib.sha256(text.encode()).hexdigest()}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('destination');args=p.parse_args();embed(args.source,args.destination)
