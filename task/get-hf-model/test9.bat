cxt get-hf-model ^
     --repo=facebook/convnext-small-224 ^
     --features.library=pytorch ^
     --filename="pytorch_model.bin" ^
     --filenames.config=config.json ^
     --filenames.preprocessor_config=preprocessor_config.json ^
     --filenames.readme=README.md ^
     -j --update
