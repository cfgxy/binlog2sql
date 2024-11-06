release: dist-bin
	upx dist/binlogfile2sql

dist-bin:
	pyinstaller --distpath dist/ -F binlogfile2sql.py -s --optimize 2 -p . --exclude-module dist