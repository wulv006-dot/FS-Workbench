# Candidate65 local integration

Original input: `libfile_d147c2b4fa24819185df6312c0ceea39`, ZIP SHA256 `a9719d1a7f227594e380668b4c60d4b06eafd1932830f53e70e3e674964a2bd9`; reviewed patch SHA256 `637b8cb4c7753d85425de3a96d8dd77432d3683a6b280a88f12485fde50fbbd8`, base `718ff48baac19a3c04eabd7111e26a173698d008`.

Applied as a patch to main `6e42c1f9b5e01ee0b7ef67da118fde0304cfe793`; no intervening activity-module or pr-fast delta. Other main changes retained. Existing independent review of the exact input is reused; no new review tier.

Local integration delta: restore the existing preview robots tag and regenerate CollectionPage/ItemList via the unchanged `seasonal-source/build-seo.cjs`; update one obsolete static failure-message assertion to the current same-request retry wording. No cart/pricing/business semantics changed by this delta. Public metadata contains no invented Offer prices or category URLs.

Local Windows checks: 231 affected Node tests, 209 backend tests, native-page59-browser, halloween61-browser, products-page-flow-browser and halloween52-browser passed. Browser native-add and Apply responses are explicitly simulated. Required Linux PR CI remains authoritative for POSIX publisher checks; local isolated success is not evidence of production purchase or discount application.

Operational launch inputs remain outside Git. No raw Admin responses, private policy, credentials, customer or order data in this change. Deployment, configuration, native add and Apply require their separate execution/readback records; this code/CI report does not claim those stages complete.
