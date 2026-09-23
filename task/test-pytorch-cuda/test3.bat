cx . run ^
     --use.pip-torch.new ^
     --use.pip-torch.skip_detect ^
     --use.pip-torch.with.post_flags="--no-cache-dir --force-reinstall --index-url https://download.pytorch.org/whl/cu130" ^
     --save_here
