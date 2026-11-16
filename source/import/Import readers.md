# Browser-local script readers

All file contents stay in the browser until the user chooses to convert the reviewed script with the configured AI service. The reader needs neither an access code nor network service.

Pinned official npm packages: Mammoth 1.13.0 (BSD-2-Clause) and Mozilla PDF.js 6.5.438 (Apache-2.0). Original LICENSE files and npm tarballs are retained in vendor; hashes and integrity values are in Vendor manifest.json. embed_import.py embeds the selected readers, CMaps and standard fonts as inert base64 plus both licenses. No CDN dependency or eval is used. DOCX raw text runs in a disposable Worker; PDF parsing runs in PDF.js's Worker.

The read(file,{signal}) API returns {text,title,warnings}. Limits: 5 MB compressed/file bytes, 12,000 extracted characters, 100 PDF pages, 1,000 ZIP entries and 20 MB expanded DOCX content; 30-second cancellation timeout. Imported content is plain text, never rendered as HTML. Images, Word headers/footers and comments are omitted. PDF reading order needs review. Image-only PDFs receive an OCR instruction; mixed documents warn about pages without text. Encrypted PDFs, invalid files, unsupported legacy DOC and invalid text encodings show specific errors.

Sources: https://github.com/mwilliamson/mammoth.js/blob/master/README.md and https://github.com/mozilla/pdf.js/blob/master/examples/learning/helloworld64.html .
