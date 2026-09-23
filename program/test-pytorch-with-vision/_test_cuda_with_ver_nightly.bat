cx program run test-pytorch-with-vision -v -j --clean ^
     --compute=cuda --use.target--cuda.with.ver=13.2 ^
     --use.pip-torch.version="2.12.0.dev20260414+cu132" ^
     --use.pip-torch.with.flags=--pre --use.pip-torch.with.url_extra=nightly/ ^
     --use.pip-torchvision.with.flags=--pre --use.pip-torchvision.with.url_extra=nightly/ -q
