:: Need to fix : in paths 
:: https://mlperf-dashboard-final-50577619532.us-west1.run.app/

cxt clone-git https://github.com/gfursin/inference_results_v6.0 ^
    --cache ^
    --cache_repo=fgg-work-usb ^
    --path=x:\work\mlperf-inference-results\v6.0 ^
    --cache-extra-params.version=6.0 ^
    --cache-extra-params.name=mlperf-inference-results ^
    --cache-extra-tags=mlperf,inference,results,github ^
    -j ^
    --update
