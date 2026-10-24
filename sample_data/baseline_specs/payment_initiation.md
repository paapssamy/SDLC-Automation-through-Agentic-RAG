# Baseline Spec: Payment Initiation
A customer credit transfer is initiated through the payment API with a unique reference, debtor
account, creditor account, amount, currency and charges option. The payment service coordinates
validation, sanctions screening, debit of the debtor account, message creation and status
notification. Every payment ends in status SENT or REJECTED.
