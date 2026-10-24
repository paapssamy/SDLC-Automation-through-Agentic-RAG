package com.bank.payments.mapping;

import com.bank.payments.payment.PaymentRequest;

/** Maps a payment request to the legacy SWIFT MT103 single customer credit transfer. */
public class MT103Mapper {

    public String toMt103(PaymentRequest request) {
        return ":20:" + request.getReference() + "\n"
                + ":32A:" + request.getAmount().getCurrency() + request.getAmount().getValue() + "\n"
                + ":50K:" + request.getDebtorAccount() + "\n"
                + ":59:" + request.getCreditorAccount() + "\n"
                + ":71A:" + mapCharges(request.getChargesOption());
    }

    String mapCharges(String option) {
        return option == null ? "SHA" : option;
    }
}
