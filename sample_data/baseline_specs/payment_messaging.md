# Baseline Spec: Payment Messaging
Outgoing interbank payments are sent as ISO 20022 pacs.008 messages; legacy counterparties
receive SWIFT MT103. Messages carry group header, settlement amount, charge bearer, debtor and
creditor details. Message format changes need regression testing with the clearing partner.
