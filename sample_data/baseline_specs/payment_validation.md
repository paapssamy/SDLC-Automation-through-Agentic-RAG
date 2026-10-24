# Baseline Spec: Payment Validation
Mandatory fields must be present. The amount must be greater than zero and not above the
single-payment limit. The charges option must be one of the supported values. A payment that
fails validation is rejected before any account is debited.
