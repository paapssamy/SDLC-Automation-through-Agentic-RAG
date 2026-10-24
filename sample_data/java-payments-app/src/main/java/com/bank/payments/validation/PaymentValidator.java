package com.bank.payments.validation;

import com.bank.payments.charges.ChargesCalculator;
import com.bank.payments.payment.PaymentRequest;

/** Mandatory-field and business-rule validation of incoming payments. */
public class PaymentValidator {
    private static final double MAX_AMOUNT = 10_000_000.0;
    private final ChargesCalculator chargesCalculator;

    public PaymentValidator(ChargesCalculator chargesCalculator) {
        this.chargesCalculator = chargesCalculator;
    }

    public boolean validate(PaymentRequest request) {
        return hasMandatoryFields(request) && isAmountValid(request) && isChargesValid(request);
    }

    boolean hasMandatoryFields(PaymentRequest request) {
        return request.getReference() != null
                && request.getDebtorAccount() != null
                && request.getCreditorAccount() != null;
    }

    boolean isAmountValid(PaymentRequest request) {
        double v = request.getAmount().getValue();
        return v > 0 && v <= MAX_AMOUNT;
    }

    boolean isChargesValid(PaymentRequest request) {
        return chargesCalculator.isSupportedOption(request.getChargesOption());
    }
}
