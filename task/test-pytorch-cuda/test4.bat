:: Can hold only one torch - check that doesn't follow params

cx . run ^
     --use.pip-torch.with.post_flags="--index-url https://download.pytorch.org/whl/cu129" ^
     --save_here
