package com.bank.payments.api;

import com.bank.payments.payment.PaymentRequest;
import com.bank.payments.payment.PaymentService;
import com.bank.payments.payment.PaymentStatus;

/** REST entry point for payment initiation. */
public class PaymentController {
    private final PaymentService paymentService;

    public PaymentController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    public String initiatePayment(PaymentRequest request) {
        PaymentStatus status = paymentService.process(request);
        return "Payment " + request.getReference() + " status " + status;
    }

    public PaymentStatus getStatus(String reference) {
        return paymentService.findStatus(reference);
    }
}
