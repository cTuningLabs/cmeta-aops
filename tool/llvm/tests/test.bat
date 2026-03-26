cx config set task --meta.winget_install_flags="--silent --accept-source-agreements --accept-package-agreements"

cxt test-python-numpy --use.pip-numpy.version=">=2" -v -q --extra_line
