import zipfile
import xml.etree.ElementTree as ET

def extract(docx_path, out_path):
    z = zipfile.ZipFile(docx_path)
    w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    doc = ET.fromstring(z.read('word/document.xml'))
    text = [node.text for node in doc.iter() if node.tag == f'{{{w}}}t' and node.text]
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(text))

extract('omniprof_v3_spec.docx', 'spec_clean.txt')
